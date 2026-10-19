import glob
import json
import math
import os
import sys
import time

import numpy as np
import sionna.rt
import mitsuba as mi
from sionna.rt import load_scene, Transmitter, Receiver, PlanarArray, PathSolver, RadioMapSolver

if not mi.variant().startswith("cuda"):
    print(f"no CUDA variant on this machine: {mi.variant()}", file=sys.stderr)
    sys.exit(3)


def log(text):
    print(text, flush=True)


def wrote(path):
    log(f"wrote {os.path.basename(path)} ({os.path.getsize(path) / 1024:.1f} kB)")


def find(folder, suffix):
    return glob.glob(os.path.join(folder, "*" + suffix))[0]


def out_path(folder, suffix):
    return find(folder, "_scene.xml").replace("_scene.xml", suffix)


def num(x):
    return float(np.array(x).ravel()[0])


def vec(x):
    return [float(c) for c in np.array(x).ravel()]


def db(amplitude):
    return 20 * math.log10(amplitude) if amplitude > 0 else None


def load(folder):
    t0 = time.time()
    log(f"sionna {sionna.rt.__version__}, {mi.variant()}")
    scene = load_scene(find(folder, "_scene.xml"), merge_shapes=False)
    with open(find(folder, "_txrx.json")) as fh:
        devs = json.load(fh)
    for d in devs["tx"]:
        kw = {"power_dbm": d["power_dbm"]} if "power_dbm" in d else {}
        scene.add(Transmitter(name=d["name"], position=d["position"], orientation=d["orientation"], **kw))
    for d in devs["rx"]:
        scene.add(Receiver(name=d["name"], position=d["position"], orientation=d["orientation"]))
    log(f"scene: {len(scene.objects)} objects, {len(scene.radio_materials)} materials, "
        f"{len(scene.transmitters)} tx, {len(scene.receivers)} rx ({time.time() - t0:.1f} s)")
    return scene, devs


def dump(folder):
    scene, _ = load(folder)
    objects = []
    for name, obj in scene.objects.items():
        params = mi.traverse(obj.mi_mesh)
        m = obj.radio_material
        objects.append({
            "name": name,
            "material": m.name,
            "itu_type": getattr(m, "itu_type", None),
            "thickness": num(m.thickness),
            "scattering_coefficient": num(m.scattering_coefficient),
            "relative_permittivity": num(m.relative_permittivity),
            "conductivity": num(m.conductivity),
            "vertices": np.array(params["vertex_positions"]).reshape(-1, 3).tolist(),
            "faces": np.array(params["faces"]).reshape(-1, 3).tolist(),
        })
    out = {
        "sionna_rt": sionna.rt.__version__,
        "variant": mi.variant(),
        "frequency": num(scene.frequency),
        "objects": objects,
        "tx": [{"name": n, "position": vec(d.position), "orientation": vec(d.orientation)}
               for n, d in scene.transmitters.items()],
        "rx": [{"name": n, "position": vec(d.position), "orientation": vec(d.orientation)}
               for n, d in scene.receivers.items()],
    }
    path = out_path(folder, "_dump.json")
    with open(path, "w") as fh:
        json.dump(out, fh)
    wrote(path)


def configure(folder):
    with open(find(folder, "_settings.json")) as fh:
        s = json.load(fh)
    scene, devs = load(folder)
    scene.frequency = s["frequency"]
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    common = {k: s[k] for k in ("max_depth", "los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction")}
    on = [k for k in ("los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction") if s[k]]
    log(f"settings: {s['frequency'] / 1e9:g} GHz, max_depth {s['max_depth']}, {', '.join(on)}")
    return scene, devs, s, common


def radiomap(folder, scene, s, common, names):
    maps = []
    for name in names:
        t0 = time.time()
        mesh = mi.load_dict({
            "type": "ply",
            "filename": os.path.join(folder, "meshes", name + ".ply"),
            "face_normals": True,
        })
        log(f"radio map '{name}': {mesh.face_count()} cells, {s['radiomap_samples']:.0e} samples per tx")
        rm = RadioMapSolver()(scene, measurement_surface=mesh, samples_per_tx=s["radiomap_samples"], **common)
        gain = rm.path_gain.numpy()
        with np.errstate(divide="ignore"):
            gain_db = 10 * np.log10(gain)
        gain_db[~np.isfinite(gain_db)] = -999.0
        params = mi.traverse(mesh)
        maps.append({
            "name": name,
            "vertices": np.array(params["vertex_positions"]).reshape(-1, 3).tolist(),
            "faces": np.array(params["faces"]).reshape(-1, 3).tolist(),
            "path_gain_db": np.round(gain_db, 2).T.tolist(),
        })
        reached = int((gain_db > -999).any(axis=0).sum())
        log(f"radio map '{name}': {reached} of {gain_db.shape[1]} cells reached ({time.time() - t0:.1f} s)")
    result = {
        "sionna_rt": sionna.rt.__version__,
        "settings": s,
        "tx": list(scene.transmitters),
        "maps": maps,
    }
    path = out_path(folder, "_radiomap.json")
    with open(path, "w") as fh:
        json.dump(result, fh)
    wrote(path)


def solve(folder):
    scene, devs, s, common = configure(folder)
    if devs["rx"]:
        trace(folder, scene, devs, s, common)
    else:
        log("paths: skipped, no rx")
    measure = out_path(folder, "_measure.json")
    names = []
    if os.path.isfile(measure):
        with open(measure) as fh:
            names = json.load(fh)
    if names:
        radiomap(folder, scene, s, common, names)
    else:
        log("radio map: skipped, no measurement surface")


def trace(folder, scene, devs, s, common):
    t0 = time.time()
    log(f"paths: {len(devs['tx'])} tx x {len(devs['rx'])} rx, {s['samples']:.0e} samples per tx")
    paths = PathSolver()(
        scene,
        samples_per_src=s["samples"],
        max_num_paths_per_src=s["max_paths_per_tx"],
        synthetic_array=False,
        **common,
    )

    a = paths.a[0].numpy()[:, 0, :, 0, :] + 1j * paths.a[1].numpy()[:, 0, :, 0, :]
    tau = paths.tau.numpy()[:, 0, :, 0, :]
    valid = paths.valid.numpy()[:, 0, :, 0, :]
    inter = paths.interactions.numpy()[:, :, 0, :, 0, :]
    objs = paths.objects.numpy()[:, :, 0, :, 0, :]
    verts = paths.vertices.numpy()[:, :, 0, :, 0, :, :]

    prims = paths.primitives.numpy()[:, :, 0, :, 0, :]
    extra = {
        k: getattr(paths, k).numpy()[:, 0, :, 0, :]
        for k in ("theta_t", "phi_t", "theta_r", "phi_r", "doppler")
    }

    names = {int(o.object_id): n for n, o in scene.objects.items()}
    tx_pos = {d["name"]: d["position"] for d in devs["tx"]}
    rx_pos = {d["name"]: d["position"] for d in devs["rx"]}
    fc = s["frequency"]
    freqs = fc + np.linspace(-s["bandwidth"] / 2, s["bandwidth"] / 2, s["cfr_points"])

    out, links = [], []
    for r, rx in enumerate(scene.receivers):
        for t, tx in enumerate(scene.transmitters):
            for p in range(a.shape[-1]):
                if not valid[r, t, p]:
                    continue
                hops = [d for d in range(inter.shape[0]) if inter[d, r, t, p] != 0]
                c = complex(a[r, t, p])
                path = {
                    "tx": tx,
                    "rx": rx,
                    "vertices": [tx_pos[tx]] + [verts[d, r, t, p].tolist() for d in hops] + [rx_pos[rx]],
                    "interactions": [int(inter[d, r, t, p]) for d in hops],
                    "objects": [names.get(int(objs[d, r, t, p]), "") for d in hops],
                    "primitives": [int(prims[d, r, t, p]) for d in hops],
                    "a_re": c.real,
                    "a_im": c.imag,
                    "gain_db": db(abs(c)),
                    "tau": float(tau[r, t, p]),
                }
                path.update({k: float(v[r, t, p]) for k, v in extra.items()})
                out.append(path)

            m = valid[r, t].astype(bool)
            ai = a[r, t][m].astype(np.complex128)
            ti = tau[r, t][m].astype(np.float64)
            link = {"tx": tx, "rx": rx, "vertices": [tx_pos[tx], rx_pos[rx]], "num_paths": int(m.sum())}
            if len(ai):
                pw = np.abs(ai) ** 2
                h = (ai[None, :] * np.exp(-2j * np.pi * freqs[:, None] * ti[None, :])).sum(axis=1)
                h0 = (ai * np.exp(-2j * np.pi * fc * ti)).sum()
                mean = (pw * ti).sum() / pw.sum()
                link.update({
                    "gain_db_coherent": db(abs(h0)),
                    "gain_db_incoherent": db(math.sqrt(pw.sum())),
                    "delay_spread": math.sqrt((pw * (ti - mean) ** 2).sum() / pw.sum()),
                    "cfr_db": [db(x) for x in np.abs(h)],
                })
            links.append(link)

    log(f"paths: {len(out)} valid paths over {len(links)} links ({time.time() - t0:.1f} s)")
    result = {
        "sionna_rt": sionna.rt.__version__,
        "variant": mi.variant(),
        "settings": s,
        "cfr_frequencies": freqs.tolist(),
        "paths": out,
        "links": links,
    }
    path = out_path(folder, "_result.json")
    with open(path, "w") as fh:
        json.dump(result, fh)
    wrote(path)


if __name__ == "__main__":
    {"dump": dump, "solve": solve}[sys.argv[1]](sys.argv[2])
