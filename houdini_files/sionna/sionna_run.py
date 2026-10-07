import glob
import json
import math
import os
import sys

import numpy as np
import sionna.rt
import mitsuba as mi
from sionna.rt import load_scene, Transmitter, Receiver, PlanarArray, PathSolver, RadioMapSolver


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
    scene = load_scene(find(folder, "_scene.xml"), merge_shapes=False)
    with open(find(folder, "_txrx.json")) as fh:
        devs = json.load(fh)
    for d in devs["tx"]:
        kw = {"power_dbm": d["power_dbm"]} if "power_dbm" in d else {}
        scene.add(Transmitter(name=d["name"], position=d["position"], orientation=d["orientation"], **kw))
    for d in devs["rx"]:
        scene.add(Receiver(name=d["name"], position=d["position"], orientation=d["orientation"]))
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
    with open(out_path(folder, "_dump.json"), "w") as fh:
        json.dump(out, fh)


def configure(folder):
    with open(find(folder, "_settings.json")) as fh:
        s = json.load(fh)
    scene, devs = load(folder)
    scene.frequency = s["frequency"]
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    common = {k: s[k] for k in ("max_depth", "los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction")}
    return scene, devs, s, common


def radiomap(folder):
    scene, devs, s, common = configure(folder)
    with open(find(folder, "_measure.json")) as fh:
        names = json.load(fh)
    maps = []
    for name in names:
        mesh = mi.load_dict({
            "type": "ply",
            "filename": os.path.join(folder, "meshes", name + ".ply"),
            "face_normals": True,
        })
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
    result = {
        "sionna_rt": sionna.rt.__version__,
        "settings": s,
        "tx": list(scene.transmitters),
        "maps": maps,
    }
    with open(out_path(folder, "_radiomap.json"), "w") as fh:
        json.dump(result, fh)


def solve(folder):
    scene, devs, s, common = configure(folder)
    paths = PathSolver()(scene, samples_per_src=s["samples"], synthetic_array=False, **common)

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

    result = {
        "sionna_rt": sionna.rt.__version__,
        "variant": mi.variant(),
        "settings": s,
        "cfr_frequencies": freqs.tolist(),
        "paths": out,
        "links": links,
    }
    with open(out_path(folder, "_result.json"), "w") as fh:
        json.dump(result, fh)


if __name__ == "__main__":
    {"dump": dump, "solve": solve, "radiomap": radiomap}[sys.argv[1]](sys.argv[2])