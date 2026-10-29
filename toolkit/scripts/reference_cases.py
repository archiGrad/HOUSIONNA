"""Analytical reference cases for the Sionna RT setup used by HOUSIONNA.

    python scripts/reference_cases.py            # results in outputs/validation/

A. Free space: path gain and delay against (c / 4 pi f d)^2 and d / c.
B. One wall, modelled as a single surface whose radio material has thickness t: transmission against the
   finite-slab solution at normal incidence (ITU-R P.2040).
C. The same material as a closed block of depth t (a front and a back surface). Sionna treats every surface a ray
   crosses as a slab of the material's full thickness, so the block costs about twice the slab of case B.
   With thickness t/2 per surface the block comes close to one slab of depth t.
D. Thin objects: a closed glass block and two parallel sheets, 0.3 mm to 50 mm apart. Sionna RT 2.2 discards every
   path with a segment shorter than MIN_SEGMENT_LENGTH = 1 cm (sionna/rt/constants.py), so anything thinner than
   that along the ray blocks completely. Repeated with the constant lowered to 10 um: closed objects then pass down
   to about 1 mm; below that the ray spawn offset (~1e-4 x scene coordinate) skips the back face.

Only refraction is enabled in B and C, and the wall is perpendicular to the TX-RX axis, so each case has one path.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rt_backend import load_rt  # noqa: E402

C0, EPS0 = 299_792_458.0, 8.8541878128e-12
FREQUENCIES_HZ = [433e6, 868e6, 2.4e9, 3.5e9, 5.0e9]
DISTANCES_M = [1.0, 3.0, 10.0]
# Radio materials for B and C (relative permittivity, conductivity S/m, depth m). The first is the coarse canopy
# block used in the vertical-farm demo until Oct 2026, the second the leaf-volume estimate proposed for it, the
# third a 4 mm glass pane.
MATERIALS = {
    "canopy_block_old": (8.0, 0.25, 0.34),
    "canopy_block_estimate": (1.3, 0.010, 0.34),
    "glass_4mm": (6.3, 0.02, 0.004),
}
OUT = ROOT / "outputs" / "validation"


def free_space_gain(distance_m: float, frequency_hz: float) -> float:
    return (C0 / (4 * np.pi * frequency_hz * distance_m)) ** 2


def slab_transmission(eps_r: float, sigma: float, depth_m: float, frequency_hz: float) -> float:
    """|T|^2 of a homogeneous slab at normal incidence, including multiple internal reflections (ITU-R P.2040)."""
    n = np.sqrt(eps_r - 1j * sigma / (2 * np.pi * frequency_hz * EPS0))
    gamma = (1 - n) / (1 + n)
    q = 2 * np.pi * frequency_hz / C0 * depth_m * n
    t = (1 - gamma ** 2) * np.exp(-1j * q) / (1 - gamma ** 2 * np.exp(-2j * q))
    return float(abs(t) ** 2)


def _write_obj(path: Path, vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for x, y, z in vertices:
            handle.write(f"v {x:.9g} {y:.9g} {z:.9g}\n")
        for face in faces:
            handle.write("f " + " ".join(str(index + 1) for index in face) + "\n")
    return path


def wall_obj(path: Path, x: float, half: float = 4.0) -> Path:
    """One square surface in the plane x = const, large enough that edges do not matter."""
    vertices = [(x, -half, -half), (x, half, -half), (x, half, half), (x, -half, half)]
    return _write_obj(path, vertices, [(0, 1, 2), (0, 2, 3)])


def block_obj(path: Path, x0: float, x1: float, half: float = 4.0) -> Path:
    """Closed box between x0 and x1 (outward normals)."""
    v = [(x0, -half, -half), (x1, -half, -half), (x1, half, -half), (x0, half, -half),
         (x0, -half, half), (x1, -half, half), (x1, half, half), (x0, half, half)]
    faces = [(0, 3, 2), (0, 2, 1), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (2, 3, 7), (2, 7, 6), (1, 2, 6), (1, 6, 5), (0, 4, 7), (0, 7, 3)]
    return _write_obj(path, v, faces)


def solve(rt, mi, frequency_hz: float, rx_x: float, objects=()) -> tuple[float, float, int]:
    """Total path gain sum |a|^2, delay of the strongest path, and number of valid paths, TX at x=0, RX at x=rx_x."""
    scene = rt.load_scene()
    if objects:
        scene.add([obj.radio_material for obj in objects])
        scene.add(list(objects))
    scene.frequency = frequency_hz
    scene.tx_array = rt.PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.rx_array = rt.PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.add(rt.Transmitter(name="tx", position=mi.Point3f(0.0, 0.0, 0.0)))
    scene.add(rt.Receiver(name="rx", position=mi.Point3f(rx_x, 0.0, 0.0)))
    paths = rt.PathSolver()(scene, max_depth=2, samples_per_src=10**5, los=True, specular_reflection=False,
                            diffuse_reflection=False, refraction=True, diffraction=False)
    a, tau = paths.cir(normalize_delays=False, out_type="numpy")
    a, tau = np.asarray(a).reshape(-1), np.asarray(tau).reshape(-1)
    power = np.abs(a) ** 2
    keep = power > 0
    if not keep.any():
        return 0.0, float("nan"), 0
    return float(power[keep].sum()), float(tau[keep][np.argmax(power[keep])]), int(keep.sum())


def main() -> int:
    rt, backend = load_rt()
    import mitsuba as mi
    OUT.mkdir(parents=True, exist_ok=True)
    meshes = OUT / "meshes"
    rows: list[dict] = []
    db = lambda value: 10 * np.log10(value) if value > 0 else float("-inf")  # noqa: E731

    for f in FREQUENCIES_HZ:
        for d in DISTANCES_M:
            gain, delay, count = solve(rt, mi, f, d)
            expected = free_space_gain(d, f)
            rows.append({"case": "A_free_space", "material": "", "frequency_hz": f, "distance_m": d,
                         "paths": count, "sionna_gain_db": db(gain), "reference_gain_db": db(expected),
                         "error_db": db(gain) - db(expected), "sionna_delay_ns": delay * 1e9,
                         "reference_delay_ns": d / C0 * 1e9, "delay_error_ps": (delay - d / C0) * 1e12})

    d = 10.0
    for name, (eps_r, sigma, depth) in MATERIALS.items():
        for f in FREQUENCIES_HZ:
            reference_db = db(free_space_gain(d, f) * slab_transmission(eps_r, sigma, depth, f))
            variants = [("B_single_surface", depth, wall_obj(meshes / "wall.obj", d / 2)),
                        ("C_closed_block", depth, block_obj(meshes / f"block_{name}.obj", d / 2 - depth / 2, d / 2 + depth / 2)),
                        ("C_closed_block_half_thickness", depth / 2, block_obj(meshes / f"block_{name}.obj", d / 2 - depth / 2, d / 2 + depth / 2))]
            for case, thickness, mesh in variants:
                material = rt.RadioMaterial(name=f"m_{name}_{case}", relative_permittivity=eps_r, conductivity=sigma,
                                            thickness=thickness)
                obj = rt.SceneObject(fname=str(mesh), name=f"obj_{name}_{case}", radio_material=material)
                gain, delay, count = solve(rt, mi, f, d, [obj])
                rows.append({"case": case, "material": name, "frequency_hz": f, "distance_m": d, "paths": count,
                             "sionna_gain_db": db(gain), "reference_gain_db": reference_db,
                             "error_db": db(gain) - reference_db,
                             "slab_loss_db": -db(slab_transmission(eps_r, sigma, depth, f)),
                             "sionna_excess_loss_db": db(free_space_gain(d, f)) - db(gain)})

    glass = MATERIALS["glass_4mm"][:2]
    for patched in (False, True):
        if patched:
            import sionna.rt.constants as constants
            import sionna.rt.path_solvers.image_method as image_method
            import sionna.rt.path_solvers.sb_candidate_generator as candidates
            import sionna.rt.path_solvers.sb_deterministic as deterministic
            for module in (constants, image_method, candidates, deterministic):
                module.MIN_SEGMENT_LENGTH = 1e-5
        for gap in (0.0003, 0.001, 0.004, 0.008, 0.010, 0.012, 0.016, 0.05):
            tag = f"{int(gap * 1e5)}_{int(patched)}"
            x0, x1 = d / 2 - gap / 2, d / 2 + gap / 2
            sheets = [(x0, -4, -4), (x0, 4, -4), (x0, 4, 4), (x0, -4, 4), (x1, -4, -4), (x1, 4, -4), (x1, 4, 4), (x1, -4, 4)]
            for case, mesh in (("D_closed_block", block_obj(meshes / f"thin_block_{tag}.obj", x0, x1)),
                               ("D_two_sheets", _write_obj(meshes / f"thin_sheets_{tag}.obj", sheets,
                                                           [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6)]))):
                material = rt.RadioMaterial(name=f"m_thin_{case}_{tag}", relative_permittivity=glass[0],
                                            conductivity=glass[1], thickness=gap)
                obj = rt.SceneObject(fname=str(mesh), name=f"thin_{case}_{tag}", radio_material=material)
                gain, delay, count = solve(rt, mi, 2.4e9, d, [obj])
                rows.append({"case": case, "material": "glass", "frequency_hz": 2.4e9, "distance_m": d, "paths": count,
                             "gap_mm": gap * 1e3, "min_segment_length_m": 1e-5 if patched else 1e-2,
                             "sionna_excess_loss_db": db(free_space_gain(d, 2.4e9)) - db(gain),
                             "slab_loss_db": -db(slab_transmission(glass[0], glass[1], gap, 2.4e9))})

    with (OUT / "reference_cases.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = sorted({key for row in rows for key in row}, key=lambda key: list(rows[-1]).index(key) if key in rows[-1] else 99)
        writer = csv.DictWriter(handle, fieldnames=list(dict.fromkeys(list(rows[0]) + fields)))
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "reference_cases.json").write_text(json.dumps({"backend": str(backend), "rows": rows}, indent=2), encoding="utf-8")

    print(f"backend: {backend}")
    print("A. free space (worst absolute errors):",
          f"gain {max(abs(r['error_db']) for r in rows if r['case'] == 'A_free_space'):.4f} dB,",
          f"delay {max(abs(r['delay_error_ps']) for r in rows if r['case'] == 'A_free_space'):.2f} ps")
    print(f"\n{'material':24s}{'f (GHz)':>8s}{'slab loss':>11s}{'1 surface':>11s}{'block':>9s}{'block t/2':>11s}   (excess loss over free space, dB)")
    for name in MATERIALS:
        for f in FREQUENCIES_HZ:
            pick = {r["case"]: r for r in rows if r["material"] == name and r["frequency_hz"] == f}
            excess = lambda case: pick[case]["sionna_excess_loss_db"]  # noqa: E731
            print(f"{name:24s}{f/1e9:8.3f}{pick['B_single_surface']['slab_loss_db']:11.2f}{excess('B_single_surface'):11.2f}"
                  f"{excess('C_closed_block'):9.2f}{excess('C_closed_block_half_thickness'):11.2f}")
    print("\nD. thin glass objects at 2.4 GHz: excess loss in dB (inf = no path)")
    for row in (r for r in rows if r["case"].startswith("D_")):
        print(f"  {row['case']:15s} gap {row['gap_mm']:5.1f} mm  min segment {row['min_segment_length_m']:g} m:"
              f"  {row['sionna_excess_loss_db']:7.2f}   (one slab {row['slab_loss_db']:.2f})")
    print(f"\nwritten: {OUT / 'reference_cases.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
