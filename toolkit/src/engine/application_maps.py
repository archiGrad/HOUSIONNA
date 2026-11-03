"""Application maps: communication margin and wireless-power metrics over the radio-map surface of a run.

    python run.py maps --run 20261020_183214Z                   # all transmitters of the run
    python run.py maps --run 20261020_183214Z --placement-k 3   # the best 3 from run.py placement
    python run.py maps --run 20261020_183214Z --tx tx_4 --tx tx_7
    python run.py maps --batch <batch> --infrastructure ap_    # every crop configuration and the worst case per cell

Radio maps hold the local-average path gain g_i of each transmitter per surface triangle, without phase. The maps
therefore show local averages:

    single_best          P max_i g_i
    equal_incoherent     (P/N) sum_i g_i
    coherent_mrt_mean    P sum_i g_i, the expected power of coherent maximum-ratio transmission over small-scale
                         fading (E|h_i|^2 = g_i). Exact coherent values need the phase, so receiver points only.

Area shares are weighted by triangle area.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import numpy as np

from engine.application_engine import ROOT, _jsonable, db, harvest_w, load_config, reporting_interval_s, transmit_power_dbm

MAP_STRATEGIES = {
    "single_best": "Best single TX",
    "equal_incoherent": "Equal split, incoherent",
    "coherent_mrt_mean": "Coherent MRT (mean)",
}
INTERVALS_S = (60.0, 600.0, 3600.0)
COLORS = {"single_best": "tab:blue", "equal_incoherent": "tab:orange", "coherent_mrt_mean": "tab:red"}  # as placement


@dataclass
class MapChannels:
    import_id: str
    run_id: str
    frequency_hz: float
    tx_names: list[str]
    tx_power_dbm: np.ndarray
    tx_positions_m: np.ndarray
    vertices_m: np.ndarray        # (V, 3)
    faces: np.ndarray             # (F, 3) vertex indices
    gain: np.ndarray              # (n_tx, F) linear local-average path gain; 0 where the map has no value
    surface: str
    parameters: dict[str, Any] = field(default_factory=dict)   # work-item parameters, e.g. the crop configuration

    @property
    def areas_m2(self) -> np.ndarray:
        a, b, c = (self.vertices_m[self.faces[:, k]] for k in range(3))
        return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)

    @property
    def centroids_m(self) -> np.ndarray:
        return self.vertices_m[self.faces].mean(axis=1)


def map_channels_from_payload(payload: dict[str, Any]) -> MapChannels:
    scenarios = [payload["scenarios"][name] for name in payload["scenario_order"]]
    surfaces = [scenario["radio_map"]["surfaces"][0] for scenario in scenarios if scenario.get("radio_map", {}).get("surfaces")]
    if len(surfaces) != len(scenarios):
        raise ValueError("Every transmitter needs a radio-map surface")
    refs = {surface["mesh_ref"] for surface in surfaces}
    if len(refs) != 1:
        raise ValueError(f"Transmitters use different measurement surfaces: {sorted(refs)}")
    mesh = payload["assets"]["meshes"][refs.pop()]
    faces = np.asarray(mesh["faces"], dtype=int)
    gain = np.zeros((len(scenarios), len(faces)))
    for i, surface in enumerate(surfaces):
        values = np.array([np.nan if value is None else float(value) for value in surface["values_db"]])
        if len(values) != len(faces):
            raise ValueError("Radio-map values do not match the surface triangles")
        valid = np.isfinite(values) & (values > -900)
        gain[i, valid] = 10 ** (values[valid] / 10)
    first = scenarios[0]
    meta = first.get("run_metadata") or {}
    return MapChannels(
        import_id=str(payload.get("import_id") or first.get("import_id")),
        run_id=str(meta.get("run_id") or first.get("import_id")),
        frequency_hz=float(first["frequency_hz"]),
        tx_names=[scenario["transmitter"]["name"] for scenario in scenarios],
        tx_power_dbm=np.array([float(scenario["transmitter"].get("power_dbm", 0.0)) for scenario in scenarios]),
        tx_positions_m=np.array([scenario["transmitter"]["position_m"] for scenario in scenarios], dtype=float),
        vertices_m=np.asarray(mesh["vertices_m"], dtype=float), faces=faces, gain=gain,
        surface=str(surfaces[0].get("name") or "surface"),
        parameters=dict(meta.get("parameters") or {}),
    )


def load_map_channels(project_root: Path, import_id: str) -> MapChannels:
    from server.digital_twin_data import housionna_viewer_payload
    return map_channels_from_payload(housionna_viewer_payload(Path(project_root), import_id))


def select_transmitters(maps: MapChannels, names: list[str] | None) -> MapChannels:
    if not names:
        return maps
    missing = [name for name in names if name not in maps.tx_names]
    if missing:
        raise ValueError(f"Unknown transmitters: {', '.join(missing)}")
    index = [maps.tx_names.index(name) for name in names]
    return MapChannels(maps.import_id, maps.run_id, maps.frequency_hz, [maps.tx_names[i] for i in index],
                       maps.tx_power_dbm[index], maps.tx_positions_m[index], maps.vertices_m, maps.faces,
                       maps.gain[index], maps.surface, maps.parameters)


def select_prefix(maps: MapChannels, prefix: str | None) -> MapChannels | None:
    """The transmitters whose name starts with prefix (e.g. ap_ for the access points); None if there are none.

    A radio map holds the gain from one transmitter to every cell, so infrastructure that was simulated as a
    receiver has no map: unlike the point links, a map cannot be turned around by reciprocity.
    """
    if not prefix:
        return maps
    names = [name for name in maps.tx_names if name.startswith(prefix)]
    return select_transmitters(maps, names) if names else None


def same_surface(a: MapChannels, b: MapChannels) -> bool:
    return (a.faces.shape == b.faces.shape and a.vertices_m.shape == b.vertices_m.shape
            and np.array_equal(a.faces, b.faces) and np.allclose(a.vertices_m, b.vertices_m, atol=1e-4))


def combine_configurations(evaluated: list[tuple[MapChannels, dict[str, Any]]]) -> dict[str, Any] | None:
    """Worst case per cell over crop configurations: min_s of the margin and max_s of the reporting interval.

    Needs the same measurement surface in every configuration; None otherwise.
    """
    first = evaluated[0][0]
    if not all(same_surface(first, maps) for maps, _ in evaluated[1:]):
        return None
    areas = first.areas_m2
    share = lambda mask: float(areas[mask].sum() / areas.sum())  # noqa: E731
    out: dict[str, Any] = {"communication": {}, "wpt": {}}
    for name in evaluated[0][1]["communication"]:
        margin = np.min([result["communication"][name]["margin_db"] for _, result in evaluated], axis=0)
        out["communication"][name] = {"margin_db": margin, "coverage_area_share": share(margin >= 0),
                                      "worst_margin_db": float(margin.min())}
    for strategy in evaluated[0][1]["wpt"]:
        interval = np.max([result["wpt"][strategy]["interval_s"] for _, result in evaluated], axis=0)
        out["wpt"][strategy] = {"interval_s": interval, "feasible_area_share": share(np.isfinite(interval)),
                                "area_share_within_s": {f"{limit:g}": share(interval <= limit) for limit in INTERVALS_S}}
    return out


def coverage_figure(maps: MapChannels, margins: dict[str, np.ndarray], config: dict[str, Any], out: Path,
                    tag: str) -> list[Path]:
    """Worst-case link margin per triangle for each communication profile (white: no value)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.tri import Triangulation
    extent = np.ptp(maps.vertices_m, axis=0)
    axes2 = np.sort(np.argsort(extent)[-2:])
    triangulation = Triangulation(maps.vertices_m[:, axes2[0]], maps.vertices_m[:, axes2[1]], maps.faces)
    finite = np.concatenate([values[np.isfinite(values)] for values in margins.values()])
    limit = max(abs(finite).max(), 1.0) if finite.size else 1.0
    fig, axes = plt.subplots(1, len(margins), figsize=(3.6 * len(margins), 3.0), squeeze=False, layout="constrained")
    for ax, (name, values) in zip(axes[0], margins.items()):
        image = ax.tripcolor(triangulation, facecolors=np.ma.masked_invalid(np.where(np.isfinite(values), values, np.nan)),
                             cmap="RdBu", vmin=-limit, vmax=limit, edgecolors="none")
        ax.scatter(maps.tx_positions_m[:, axes2[0]], maps.tx_positions_m[:, axes2[1]], marker="^", s=28,
                   color="black", edgecolors="white", linewidths=0.5)
        ax.set_title(config["communication"][name].get("label", name), fontsize=7)
        ax.set_aspect("equal")
        ax.set_xlabel(f"{'xyz'[axes2[0]]} (m)", fontsize=7)
        ax.set_ylabel(f"{'xyz'[axes2[1]]} (m)", fontsize=7)
        ax.tick_params(labelsize=6)
        bar = fig.colorbar(image, ax=ax, shrink=0.85, pad=0.02)
        bar.set_label("Worst-case margin (dB)", fontsize=7)
        bar.ax.tick_params(labelsize=6)
    written = []
    for suffix in ("pdf", "png"):
        fig.savefig(out / f"map_coverage_{tag}.{suffix}", dpi=200, bbox_inches="tight")
        written.append(out / f"map_coverage_{tag}.{suffix}")
    plt.close(fig)
    return written


def batch_main(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """Maps of every run of a batch (one crop configuration each) and their worst case per cell."""
    from engine.application_engine import _imports_in_scope
    ids = _imports_in_scope(ROOT, [args.batch], None)
    if not ids:
        print(f"No imported runs of batch {args.batch}")
        return 2
    evaluated, skipped = [], []
    for import_id in ids:
        maps = select_prefix(load_map_channels(ROOT, import_id), args.infrastructure)
        if maps is None:
            skipped.append(import_id)
            continue
        evaluated.append((maps, evaluate_maps(maps, config)))
    for import_id in skipped:
        print(f"skipped {import_id}: no transmitter named {args.infrastructure}*; infrastructure simulated as a "
              "receiver has no radio map, so rerun it as a transmitter")
    if not evaluated:
        return 2
    tag = (args.infrastructure.rstrip("_") if args.infrastructure else "all") + (f"_{args.harvester}" if args.harvester else "")
    out = args.out or ROOT / "outputs" / "applications" / "maps" / args.batch
    out.mkdir(parents=True, exist_ok=True)
    per_run = [{"run_id": maps.run_id, "import_id": maps.import_id, "parameters": maps.parameters,
                "transmitters": maps.tx_names,
                "communication": {name: {key: value for key, value in item.items() if key != "margin_db"}
                                  for name, item in result["communication"].items()},
                "wpt": {strategy: {key: value for key, value in item.items() if key not in ("p_rf_dbm", "p_dc_w", "interval_s")}
                        for strategy, item in result["wpt"].items()}}
               for maps, result in evaluated]
    worst = combine_configurations(evaluated)
    summary = {"batch": args.batch, "frequency_hz": evaluated[0][0].frequency_hz, "surface": evaluated[0][0].surface,
               "area_m2": evaluated[0][1]["area_m2"], "runs": per_run, "skipped": skipped,
               "worst_case": None if worst is None else {
                   "communication": {name: {key: value for key, value in item.items() if key != "margin_db"}
                                     for name, item in worst["communication"].items()},
                   "wpt": {strategy: {key: value for key, value in item.items() if key != "interval_s"}
                           for strategy, item in worst["wpt"].items()}}}
    (out / f"maps_batch_{tag}.json").write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8")
    written = [out / f"maps_batch_{tag}.json"]
    for row in per_run:
        cover = ", ".join(f"{name} {item['coverage_area_share']*100:.0f}%" for name, item in row["communication"].items())
        print(f"{row['run_id']} {row['parameters']}: coverage {cover}")
    if worst is None:
        print("The runs use different measurement surfaces; no worst case per cell")
    else:
        maps = evaluated[0][0]
        written += coverage_figure(maps, {name: item["margin_db"] for name, item in worst["communication"].items()},
                                   config, out, tag)
        cover = ", ".join(f"{name} {item['coverage_area_share']*100:.0f}% (worst {item['worst_margin_db']:.1f} dB)"
                          for name, item in worst["communication"].items())
        print(f"worst case over {len(evaluated)} configurations: coverage {cover}")
    print("written:", ", ".join(str(path.relative_to(ROOT)) for path in written))
    return 0


def evaluate_maps(maps: MapChannels, config: dict[str, Any]) -> dict[str, Any]:
    areas = maps.areas_m2
    share = lambda mask: float(areas[mask].sum() / areas.sum())  # noqa: E731
    out: dict[str, Any] = {"communication": {}, "wpt": {}, "area_m2": float(areas.sum())}
    for name, profile in config.get("communication", {}).items():
        received = transmit_power_dbm(maps.tx_power_dbm, profile)[:, None] + db(maps.gain)
        margin = (received - float(profile["sensitivity_dbm"]) - float(profile.get("implementation_loss_db", 0.0))
                  - float(profile.get("reserve_db", 0.0))).max(axis=0)
        out["communication"][name] = {"margin_db": margin, "coverage_area_share": share(margin >= 0),
                                      "worst_margin_db": float(margin.min())}
    wpt = config.get("wpt")
    if wpt:
        total_w = 10 ** ((float(wpt["total_power_dbm"]) - 30) / 10) * 10 ** (float(wpt.get("rx_antenna_gain_dbi", 0.0)) / 10)
        n = maps.gain.shape[0]
        p_rf = {"single_best": total_w * maps.gain.max(axis=0),
                "equal_incoherent": total_w / n * maps.gain.sum(axis=0),
                "coherent_mrt_mean": total_w * maps.gain.sum(axis=0)}
        cycle_name, cycle_energy = next(iter(wpt["cycles_j"].items()))
        for strategy, values in p_rf.items():
            p_dc = harvest_w(values, wpt["harvester"])
            interval = reporting_interval_s(p_dc, float(cycle_energy), float(wpt.get("quiescent_power_w", 0.0)))
            out["wpt"][strategy] = {
                "p_rf_dbm": db(values) + 30, "p_dc_w": p_dc, "interval_s": interval, "cycle": cycle_name,
                "feasible_area_share": share(np.isfinite(interval)),
                "area_share_within_s": {f"{limit:g}": share(interval <= limit) for limit in INTERVALS_S},
            }
    return out


def figures(maps: MapChannels, result: dict[str, Any], config: dict[str, Any], out: Path, tag: str) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    from matplotlib.tri import Triangulation
    written = []
    extent = np.ptp(maps.vertices_m, axis=0)
    axes2 = np.argsort(extent)[-2:][::-1]          # the two widest axes of the (planar) surface
    axes2 = np.sort(axes2)
    triangulation = Triangulation(maps.vertices_m[:, axes2[0]], maps.vertices_m[:, axes2[1]], maps.faces)
    labels = "xyz"

    # Reporting interval per triangle for each strategy (white = the node cannot run there).
    intervals = [result["wpt"][strategy]["interval_s"] for strategy in MAP_STRATEGIES]
    finite = np.concatenate([values[np.isfinite(values)] for values in intervals])
    norm = LogNorm(vmin=max(finite.min(), 1.0), vmax=finite.max()) if finite.size else None
    aspect = extent[axes2[1]] / max(extent[axes2[0]], 1e-9)
    fig, axes = plt.subplots(1, 3, figsize=(7.16, 0.9 + 2.15 * min(max(aspect, 0.6), 1.6)), sharey=True)
    for ax, strategy, values in zip(axes, MAP_STRATEGIES, intervals):
        masked = np.ma.masked_invalid(np.where(np.isfinite(values), values, np.nan))
        image = ax.tripcolor(triangulation, facecolors=masked, cmap="viridis_r", norm=norm, edgecolors="none")
        ax.scatter(maps.tx_positions_m[:, axes2[0]], maps.tx_positions_m[:, axes2[1]], marker="^", s=28, color="tab:red",
                   edgecolors="white", linewidths=0.5)
        share = result["wpt"][strategy]["feasible_area_share"]
        ax.set_title(f"{MAP_STRATEGIES[strategy]}\nfeasible on {share*100:.0f}% of the area", fontsize=7)
        ax.set_aspect("equal")
        ax.set_xlabel(f"{labels[axes2[0]]} (m)", fontsize=7)
        ax.tick_params(labelsize=6)
    axes[0].set_ylabel(f"{labels[axes2[1]]} (m)", fontsize=7)
    if norm:
        bar = fig.colorbar(image, ax=axes, shrink=0.85, pad=0.015)
        energy = config["wpt"]["cycles_j"][result["wpt"]["single_best"]["cycle"]]
        bar.set_label(f"Reporting interval (s), {energy*1e3:g} mJ cycle", fontsize=7)
        bar.ax.tick_params(labelsize=6)
    for suffix in ("pdf", "png"):
        fig.savefig(out / f"map_interval_{tag}.{suffix}", dpi=200, bbox_inches="tight")
        written.append(out / f"map_interval_{tag}.{suffix}")
    plt.close(fig)

    # Share of the area that can report at least every T, per strategy.
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    areas = maps.areas_m2
    grid = np.logspace(0, 5, 200)
    for strategy, label in MAP_STRATEGIES.items():
        values = result["wpt"][strategy]["interval_s"]
        ax.plot(grid, [areas[values <= limit].sum() / areas.sum() for limit in grid], label=label, linewidth=1.4,
                color=COLORS[strategy])
    ax.set_xscale("log")
    ax.set_xlabel("Reporting interval T (s)")
    ax.set_ylabel("Area share reporting\nat least every T")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3, linewidth=0.5)
    ax.legend(fontsize=6.5, frameon=False, loc="upper left")
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(out / f"map_area_share_{tag}.{suffix}", dpi=200)
        written.append(out / f"map_area_share_{tag}.{suffix}")
    plt.close(fig)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py maps", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--run", help="run id (newest import of it) or import id")
    scope.add_argument("--batch", help="every run of this batch (one crop configuration each) and the worst case "
                       "per cell over them")
    parser.add_argument("--infrastructure", help="with --batch: name prefix of the access points, e.g. ap_ "
                        "(default: all transmitters)")
    parser.add_argument("--tx", action="append", help="use only these transmitters (repeatable)")
    parser.add_argument("--placement-k", type=int, help="use the best k coherent transmitters from run.py placement")
    parser.add_argument("--config", type=Path, help="application profiles (default config/applications.yaml)")
    parser.add_argument("--harvester", help="harvester from the config's harvesters section (default wpt.harvester)")
    parser.add_argument("--out", type=Path, help="output folder (default outputs/applications/maps/<run>)")
    args = parser.parse_args(argv)
    if args.batch:
        return batch_main(args, load_config(args.config, args.harvester))
    from housionna.importer import list_imports
    rows = sorted((row for row in list_imports(ROOT) if args.run in (row["run_id"], row["import_id"])),
                  key=lambda row: row.get("imported_at_utc") or "")
    if not rows:
        print(f"No import found for {args.run}")
        return 2
    config = load_config(args.config, args.harvester)
    maps = load_map_channels(ROOT, rows[-1]["import_id"])
    names = args.tx
    if args.placement_k:
        placement = ROOT / "outputs" / "placement" / maps.run_id.replace(".", "_") / "placement.json"
        if not placement.is_file():
            print(f"Run python run.py placement --run {maps.run_id} first")
            return 2
        row = json.loads(placement.read_text(encoding="utf-8"))["sizes"][args.placement_k - 1]
        names = row["objectives"]["wpt_coherent"].get("best_subset") or row["objectives"]["wpt_coherent"]["greedy_subset"]
    maps = select_transmitters(maps, names)
    result = evaluate_maps(maps, config)
    tag = f"k{len(maps.tx_names)}" if (names and args.placement_k) else ("custom" if names else "all")
    if args.harvester:
        tag += f"_{args.harvester}"
    out = args.out or ROOT / "outputs" / "applications" / "maps" / maps.run_id.replace(".", "_")
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / f"maps_{tag}.npz", centroids_m=maps.centroids_m, areas_m2=maps.areas_m2,
                        **{f"{strategy}_{key}": values[key] for strategy, values in result["wpt"].items()
                           for key in ("p_rf_dbm", "interval_s")},
                        **{f"{name}_margin_db": values["margin_db"] for name, values in result["communication"].items()})
    summary = {"run_id": maps.run_id, "import_id": maps.import_id, "frequency_hz": maps.frequency_hz,
               "transmitters": maps.tx_names, "surface": maps.surface, "triangles": len(maps.faces),
               "area_m2": result["area_m2"],
               "communication": {name: {key: value for key, value in item.items() if key != "margin_db"}
                                 for name, item in result["communication"].items()},
               "wpt": {strategy: {key: value for key, value in item.items() if key not in ("p_rf_dbm", "p_dc_w", "interval_s")}
                       for strategy, item in result["wpt"].items()}}
    (out / f"maps_{tag}.json").write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8")
    written = [out / f"maps_{tag}.npz", out / f"maps_{tag}.json"] + figures(maps, result, config, out, tag)
    print(f"{maps.run_id}: {len(maps.tx_names)} TX ({', '.join(maps.tx_names)}), {len(maps.faces)} triangles, "
          f"{result['area_m2']:.1f} m2 at {maps.frequency_hz/1e9:.3g} GHz")
    for name, item in result["communication"].items():
        print(f"  {config['communication'][name].get('label', name)}: coverage {item['coverage_area_share']*100:.0f}% "
              f"of the area, worst margin {item['worst_margin_db']:.1f} dB")
    for strategy, item in result["wpt"].items():
        within = ", ".join(f"<= {float(limit):g} s: {value*100:.0f}%" for limit, value in item["area_share_within_s"].items())
        print(f"  WPT {MAP_STRATEGIES[strategy]}: node runs on {item['feasible_area_share']*100:.0f}% of the area ({within})")
    print("written:", ", ".join(str(path.relative_to(ROOT)) for path in written))
    return 0
