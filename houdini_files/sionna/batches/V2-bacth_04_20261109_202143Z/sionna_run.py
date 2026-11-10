import gc
import glob
import json
import math
import os
import subprocess
import sys
import time

import numpy as np

DEVICE = sys.argv[3] if len(sys.argv) > 3 else "gpu"
NO_BACKEND = {"gpu": 13, "cpu": 14}
dr = mi = sionna = None
load_scene = Transmitter = Receiver = PlanarArray = PathSolver = RadioMapSolver = None


def backend():
    global dr, mi, sionna, load_scene, Transmitter, Receiver, PlanarArray, PathSolver, RadioMapSolver
    import drjit as dr
    import mitsuba as mi
    try:
        mi.set_variant("cuda_ad_mono_polarized" if DEVICE == "gpu" else "llvm_ad_mono_polarized")
        dr.eval(mi.Float(1.0) + 1.0)
    except Exception as e:
        name = "CUDA (gpu)" if DEVICE == "gpu" else "LLVM (cpu)"
        print(f"no {name} backend on this machine: {(str(e).strip().splitlines() or [type(e).__name__])[-1].split('. ')[0]}",
              file=sys.stderr)
        sys.exit(NO_BACKEND[DEVICE])
    import sionna.rt
    from sionna.rt import load_scene, Transmitter, Receiver, PlanarArray, PathSolver, RadioMapSolver


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


CHUNK = {}
REDUCED = {}
PROGRESS = None


def set_tx(scene, devs):
    scene.remove(list(scene.transmitters))
    for d in devs:
        kw = {"power_dbm": d["power_dbm"]} if "power_dbm" in d else {}
        scene.add(Transmitter(name=d["name"], position=d["position"], orientation=d["orientation"], **kw))


def out_of_memory(e):
    while e is not None:
        if "out of memory" in str(e):
            return True
        e = e.__cause__ or e.__context__
    return False


def note(kind, size, per_tx):
    if PROGRESS:
        with open(PROGRESS, "w") as fh:
            json.dump({"stage": kind, "size": size, "per_tx": per_tx, "reduced": REDUCED}, fh)


def chunked(kind, scene, devs, run, per_tx):
    size = max(1, min(len(devs), CHUNK.get(kind, len(devs) * per_tx) // per_tx))
    parts, i = [], 0
    while i < len(devs):
        set_tx(scene, devs[i:i + size])
        note(kind, size, per_tx)
        try:
            parts.append(run(i))
        except RuntimeError as e:
            if size == 1 or not out_of_memory(e):
                raise
            size = max(1, size // 2)
            CHUNK[kind] = REDUCED[kind] = size * per_tx
            gc.collect()
            dr.flush_malloc_cache()
            log(f"{kind}: out of memory, retrying with {size} tx per call")
            continue
        gc.collect()
        dr.flush_malloc_cache()
        i += size
    set_tx(scene, devs)
    if len(parts) > 1:
        log(f"{kind}: solved in {len(parts)} calls of up to {size} tx")
    return parts


def load(folder):
    t0 = time.time()
    log(f"sionna {sionna.rt.__version__}, {mi.variant()}, on the {DEVICE}")
    scene = load_scene(find(folder, "_scene.xml"), merge_shapes=False)
    with open(find(folder, "_txrx.json")) as fh:
        devs = json.load(fh)
    set_tx(scene, devs["tx"])
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
    ant = {}
    for role in ("tx", "rx"):
        own = devs.get("antenna", {}).get(role, {})
        ant[role] = (own.get("antenna_pattern") or s.get(f"base_{role}_antenna_pattern", "iso"),
                     own.get("polarization") or s.get(f"base_{role}_polarization", "V"))
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern=ant["tx"][0], polarization=ant["tx"][1])
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern=ant["rx"][0], polarization=ant["rx"][1])
    common = {k: s[k] for k in ("max_depth", "los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction")}
    common["seed"] = s.get("seed", 42)
    on = [k for k in ("los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction") if s[k]]
    log(f"settings: {s['frequency'] / 1e9:g} GHz, max_depth {s['max_depth']}, {', '.join(on)}, "
        f"antenna tx {' '.join(ant['tx'])}, rx {' '.join(ant['rx'])}, seed {common['seed']}")
    return scene, devs, s, common


def radiomap(folder, scene, devs, s, common, names):
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

        def run(offset):
            rm = RadioMapSolver()(scene, measurement_surface=mesh, samples_per_tx=s["radiomap_samples"], **common)
            return db(rm.path_gain.numpy(), 10)

        gain_db = np.concatenate(chunked("radio map", scene, devs["tx"], run, s["radiomap_samples"]), axis=0)
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
        tx=np.array([d["name"] for d in devs["tx"]], dtype=str),
        map_names=np.array(names, dtype=str),
        vertices=np.concatenate(verts).astype(np.float32),
        faces=np.concatenate(faces).astype(np.int32),
        cell_map=np.concatenate(cells).astype(np.int32),
        path_gain_db=np.concatenate(gains).astype(np.float32),
    )
    wrote(path)


def compute(folder):
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
        radiomap(folder, scene, devs, s, common, names)
    else:
        log("radio map: skipped, no measurement surface")


def trace(folder, scene, devs, s, common):
    t0 = time.time()
    log(f"paths: {len(devs['tx'])} tx x {len(devs['rx'])} rx, {s['samples']:.0e} samples per tx")
    by_id = {int(o.object_id): n for n, o in scene.objects.items()}
    ids = np.array(sorted(by_id), dtype=np.int64)
    fc = s["frequency"]
    freqs = fc + np.linspace(-s["bandwidth"] / 2, s["bandwidth"] / 2, s["cfr_points"])

    def run(offset):
        paths = PathSolver()(
            scene,
            samples_per_src=s["samples"],
            max_num_paths_per_src=s["max_paths_per_tx"],
            synthetic_array=False,
            **common,
        )
        return extract(paths, offset, ids, fc, freqs)

    parts = chunked("paths", scene, devs["tx"], run, s["samples"])
    out = {k: np.concatenate([p[0][k] for p in parts]) for k in parts[0][0]}
    order = np.lexsort((out["path_tx"], out["path_rx"]))
    out = {k: v[order] for k, v in out.items()}
    out.update({k: np.concatenate([p[1][k] for p in parts], axis=1) for k in parts[0][1]})
    num = out["link_num_paths"]

    log(f"paths: {len(out['path_tx'])} valid paths over {num.size} links ({time.time() - t0:.1f} s)")
    path = out_path(folder, "_result.npz")
    ints = ("path_tx", "path_rx", "path_interactions", "path_objects", "path_primitives", "link_num_paths")
    np.savez_compressed(
        path,
        info=np.array(json.dumps({"sionna_rt": sionna.rt.__version__, "variant": mi.variant(), "settings": s})),
        tx=np.array([d["name"] for d in devs["tx"]], dtype=str),
        rx=np.array(list(scene.receivers), dtype=str),
        tx_position=np.array([d["position"] for d in devs["tx"]], dtype=np.float32).reshape(-1, 3),
        rx_position=np.array([d["position"] for d in devs["rx"]], dtype=np.float32).reshape(-1, 3),
        object_names=np.array([by_id[i] for i in ids], dtype=str),
        cfr_frequencies=freqs,
        **{n: v.astype(np.int32 if n in ints else np.float32) for n, v in out.items()},
    )
    wrote(path)


def extract(paths, offset, ids, fc, freqs):
    a = paths.a[0].numpy()[:, 0, :, 0, :] + 1j * paths.a[1].numpy()[:, 0, :, 0, :]
    tau = paths.tau.numpy()[:, 0, :, 0, :]
    valid = paths.valid.numpy()[:, 0, :, 0, :].astype(bool)
    r, t, p = np.nonzero(valid)
    inter = paths.interactions.numpy()[:, :, 0, :, 0, :][:, r, t, p].T.astype(np.int64)
    objs = paths.objects.numpy()[:, :, 0, :, 0, :][:, r, t, p].T.astype(np.int64)
    prims = paths.primitives.numpy()[:, :, 0, :, 0, :][:, r, t, p].T.astype(np.int64)
    verts = paths.vertices.numpy()[:, :, 0, :, 0, :, :][:, r, t, p].transpose(1, 0, 2)
    hop = inter != 0
    k = np.clip(np.searchsorted(ids, objs), 0, max(len(ids) - 1, 0))
    obj = np.where(hop & (ids[k] == objs), k, -1) if len(ids) else np.full(objs.shape, -1)

    ap = a[r, t, p]
    flat = {
        "path_tx": t + offset, "path_rx": r,
        "path_interactions": inter, "path_objects": obj, "path_primitives": np.where(hop, prims, -1),
        "path_vertices": np.where(hop[..., None], verts, 0).astype(np.float32),
        "path_a_re": ap.real, "path_a_im": ap.imag, "path_gain_db": db(np.abs(ap)), "path_tau": tau[r, t, p],
    }
    for name in ("theta_t", "phi_t", "theta_r", "phi_r", "doppler"):
        flat["path_" + name] = getattr(paths, name).numpy()[:, 0, :, 0, :][r, t, p]

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
    link = {
        "link_num_paths": num, "link_gain_db_coherent": coherent,
        "link_gain_db_incoherent": incoherent, "link_delay_spread": spread, "link_cfr_db": cfr,
    }
    return flat, link


def work(folder):
    global PROGRESS
    PROGRESS = os.path.join(folder, "progress.json")
    CHUNK.update(json.loads(os.environ.get("SIONNA_CHUNK") or "{}"))
    compute(folder)


def supervise(folder, limit):
    progress = os.path.join(folder, "progress.json")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    while True:
        if os.path.isfile(progress):
            os.remove(progress)
        p = subprocess.Popen(
            [sys.executable, "-u", os.path.abspath(__file__), "work", folder, DEVICE],
            env=dict(os.environ, SIONNA_CHUNK=json.dumps(limit)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=flags,
        )
        tail = []
        for line in p.stdout:
            line = line.rstrip()
            log(line)
            tail = (tail + [line])[-50:]
        code = p.wait()
        state = {}
        if os.path.isfile(progress):
            with open(progress) as fh:
                state = json.load(fh)
            os.remove(progress)
        if code == 0:
            for kind, rays in state.get("reduced", {}).items():
                limit[kind] = max(1, rays * 3 // 4)
            return 0, ""
        stage, size, per_tx = state.get("stage"), state.get("size", 0), state.get("per_tx", 1)
        if stage and size > 1 and any("out of memory" in line.lower() for line in tail):
            limit[stage] = max(1, size // 2) * per_tx
            log(f"{stage}: process ran out of memory with {size} tx per call, restarting with {max(1, size // 2)}")
            continue
        return code, next((line for line in reversed(tail) if line.strip()), f"exit code {code}")


def solve(folder):
    code, _ = supervise(folder, {})
    sys.exit(code if 0 <= code < 256 else 1)


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
        for _ in range(50):
            try:
                os.replace(path + ".tmp", path)
                break
            except PermissionError:
                time.sleep(0.1)

    save()
    log(f"batch: {len(queue)} work items, pid {os.getpid()}")
    limit = {}
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
        code, err = supervise(item, limit)
        if code == 0:
            with open(done, "w") as fh:
                json.dump(s, fh, indent=2)
            status["done"].append(name)
            status["solve_seconds"] += time.time() - t0
        else:
            err = err.strip()[:300]
            with open(os.path.join(item, "failed.json"), "w") as fh:
                json.dump({"error": err}, fh, indent=2)
            status["failed"][name] = err
            log(f"[{n}/{len(queue)}] {name}: failed, {err}")
    status["current"], status["finished"] = None, True
    save()
    log(f"batch: finished, {len(status['done'])} solved, {len(status['skipped'])} skipped, "
        f"{len(status['failed'])} failed")


if __name__ == "__main__":
    if sys.argv[1] in ("dump", "work"):
        backend()
    {"dump": dump, "work": work, "solve": solve, "batch": batch}[sys.argv[1]](sys.argv[2])
