import gc
import glob
import json
import math
import os
import sys
import time
import traceback

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
    log(f"wrote {os.path.basename(path)} ({os.path.getsize(path) / 1048576:.2f} MB)")


def find(folder, suffix):
    return glob.glob(os.path.join(folder, "*" + suffix))[0]


def out_path(folder, suffix):
    return find(folder, "_scene.xml").replace("_scene.xml", suffix)


def num(x):
    return float(np.array(x).ravel()[0])


def vec(x):
    return [float(c) for c in np.array(x).ravel()]


def db(x, k=20):
    x = np.asarray(x, dtype=np.float64)
    return np.where(x > 0, k * np.log10(np.where(x > 0, x, 1)), -999.0)


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
    verts, faces, cells, gains = [], [], [], []
    offset = 0
    for i, name in enumerate(names):
        t0 = time.time()
        mesh = mi.load_dict({
            "type": "ply",
            "filename": os.path.join(folder, "meshes", name + ".ply"),
            "face_normals": True,
        })
        log(f"radio map '{name}': {mesh.face_count()} cells, {s['radiomap_samples']:.0e} samples per tx")
        rm = RadioMapSolver()(scene, measurement_surface=mesh, samples_per_tx=s["radiomap_samples"], **common)
        gain_db = db(rm.path_gain.numpy(), 10)
        params = mi.traverse(mesh)
        v = np.array(params["vertex_positions"]).reshape(-1, 3)
        f = np.array(params["faces"]).reshape(-1, 3)
        verts.append(v)
        faces.append(f + offset)
        offset += len(v)
        cells.append(np.full(len(f), i))
        gains.append(gain_db.T)
        reached = int((gain_db > -999).any(axis=0).sum())
        log(f"radio map '{name}': {reached} of {gain_db.shape[1]} cells reached ({time.time() - t0:.1f} s)")
    path = out_path(folder, "_radiomap.npz")
    np.savez_compressed(
        path,
        info=np.array(json.dumps({"sionna_rt": sionna.rt.__version__, "variant": mi.variant(), "settings": s})),
        tx=np.array(list(scene.transmitters), dtype=str),
        map_names=np.array(names, dtype=str),
        vertices=np.concatenate(verts).astype(np.float32),
        faces=np.concatenate(faces).astype(np.int32),
        cell_map=np.concatenate(cells).astype(np.int32),
        path_gain_db=np.concatenate(gains).astype(np.float32),
    )
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
    valid = paths.valid.numpy()[:, 0, :, 0, :].astype(bool)
    r, t, p = np.nonzero(valid)
    inter = paths.interactions.numpy()[:, :, 0, :, 0, :][:, r, t, p].T.astype(np.int64)
    objs = paths.objects.numpy()[:, :, 0, :, 0, :][:, r, t, p].T.astype(np.int64)
    prims = paths.primitives.numpy()[:, :, 0, :, 0, :][:, r, t, p].T.astype(np.int64)
    verts = paths.vertices.numpy()[:, :, 0, :, 0, :, :][:, r, t, p].transpose(1, 0, 2)
    hop = inter != 0

    by_id = {int(o.object_id): n for n, o in scene.objects.items()}
    ids = np.array(sorted(by_id), dtype=np.int64)
    k = np.clip(np.searchsorted(ids, objs), 0, max(len(ids) - 1, 0))
    obj = np.where(hop & (ids[k] == objs), k, -1) if len(ids) else np.full(objs.shape, -1)

    ap = a[r, t, p]
    out = {
        "path_tx": t, "path_rx": r,
        "path_interactions": inter, "path_objects": obj, "path_primitives": np.where(hop, prims, -1),
        "path_vertices": np.where(hop[..., None], verts, 0).astype(np.float32),
        "path_a_re": ap.real, "path_a_im": ap.imag, "path_gain_db": db(np.abs(ap)), "path_tau": tau[r, t, p],
    }
    for name in ("theta_t", "phi_t", "theta_r", "phi_r", "doppler"):
        out["path_" + name] = getattr(paths, name).numpy()[:, 0, :, 0, :][r, t, p]

    fc = s["frequency"]
    freqs = fc + np.linspace(-s["bandwidth"] / 2, s["bandwidth"] / 2, s["cfr_points"])
    num = valid.sum(axis=-1)
    coherent, incoherent, spread = (np.full(num.shape, -999.0) for _ in range(3))
    cfr = np.full(num.shape + (len(freqs),), -999.0)
    for i, j in zip(*np.nonzero(num)):
        m = valid[i, j]
        ai = a[i, j][m].astype(np.complex128)
        ti = tau[i, j][m].astype(np.float64)
        pw = np.abs(ai) ** 2
        mean = (pw * ti).sum() / pw.sum()
        coherent[i, j] = db(abs((ai * np.exp(-2j * np.pi * fc * ti)).sum()))
        incoherent[i, j] = db(math.sqrt(pw.sum()))
        spread[i, j] = math.sqrt((pw * (ti - mean) ** 2).sum() / pw.sum())
        if len(freqs):
            cfr[i, j] = db(np.abs((ai[None, :] * np.exp(-2j * np.pi * freqs[:, None] * ti[None, :])).sum(axis=1)))
    out.update({
        "link_num_paths": num, "link_gain_db_coherent": coherent,
        "link_gain_db_incoherent": incoherent, "link_delay_spread": spread, "link_cfr_db": cfr,
    })

    log(f"paths: {len(r)} valid paths over {num.size} links ({time.time() - t0:.1f} s)")
    path = out_path(folder, "_result.npz")
    ints = ("path_tx", "path_rx", "path_interactions", "path_objects", "path_primitives", "link_num_paths")
    np.savez_compressed(
        path,
        info=np.array(json.dumps({"sionna_rt": sionna.rt.__version__, "variant": mi.variant(), "settings": s})),
        tx=np.array(list(scene.transmitters), dtype=str),
        rx=np.array(list(scene.receivers), dtype=str),
        tx_position=np.array([d["position"] for d in devs["tx"]], dtype=np.float32).reshape(-1, 3),
        rx_position=np.array([d["position"] for d in devs["rx"]], dtype=np.float32).reshape(-1, 3),
        object_names=np.array([by_id[i] for i in ids], dtype=str),
        cfr_frequencies=freqs,
        **{n: v.astype(np.int32 if n in ints else np.float32) for n, v in out.items()},
    )
    wrote(path)


def batch(folder):
    with open(os.path.join(folder, "queue.json")) as fh:
        queue = json.load(fh)
    status = {"pid": os.getpid(), "started": time.strftime("%Y-%m-%d %H:%M:%S"), "total": len(queue),
              "done": [], "skipped": [], "failed": {}, "solve_seconds": 0.0, "current": None, "finished": False}

    def save():
        status["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        path = os.path.join(folder, "status.json")
        with open(path + ".tmp", "w") as fh:
            json.dump(status, fh, indent=2)
        os.replace(path + ".tmp", path)

    save()
    log(f"batch: {len(queue)} work items, pid {os.getpid()}")
    for n, name in enumerate(queue, 1):
        item = os.path.join(folder, name)
        done = os.path.join(item, "done.json")
        with open(find(item, "_settings.json")) as fh:
            s = json.load(fh)
        if os.path.isfile(done):
            with open(done) as fh:
                if json.load(fh) == s:
                    status["skipped"].append(name)
                    log(f"[{n}/{len(queue)}] {name}: already solved with these settings, skipped")
                    continue
        status["current"] = name
        save()
        log(f"[{n}/{len(queue)}] {name}")
        for old in ("_result.npz", "_radiomap.npz"):
            for path in glob.glob(os.path.join(item, "*" + old)):
                os.remove(path)
        for path in (done, os.path.join(item, "failed.json")):
            if os.path.isfile(path):
                os.remove(path)
        t0 = time.time()
        try:
            solve(item)
            with open(done, "w") as fh:
                json.dump(s, fh, indent=2)
            status["done"].append(name)
            status["solve_seconds"] += time.time() - t0
        except Exception as e:
            traceback.print_exc()
            err = f"{type(e).__name__}: {e}".strip()[:300]
            with open(os.path.join(item, "failed.json"), "w") as fh:
                json.dump({"error": err}, fh, indent=2)
            status["failed"][name] = err
            log(f"[{n}/{len(queue)}] {name}: failed, {err}")
        gc.collect()
    status["current"], status["finished"] = None, True
    save()
    log(f"batch: finished, {len(status['done'])} solved, {len(status['skipped'])} skipped, "
        f"{len(status['failed'])} failed")


if __name__ == "__main__":
    {"dump": dump, "solve": solve, "batch": batch}[sys.argv[1]](sys.argv[2])
