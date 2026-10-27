import glob
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import zipfile
import hou

ITU = {
    "marble", "concrete", "wood", "metal", "brick", "glass", "floorboard",
    "ceiling_board", "chipboard", "plasterboard", "plywood", "clear_acrylic",
    "vinyl_tile", "carpet_tile", "asphalt_concrete", "very_dry_ground",
    "medium_dry_ground", "wet_ground",
}
MAT_ATTRS = ("material", "thickness", "scattering_coefficient")
MEASURE = "measure"
EPS0 = 8.8541878128e-12
OUT = "$HIP/sionna"
FREQUENCY = 3.5e9
PYTHON_EXE = "$HIP/../venv/Scripts/python.exe" if os.name == "nt" else "$HIP/../venv/bin/python3"
REMOTE_ROOT = "~/Documents/HyROPA"
TIMEOUT = 1800
MAX_RAYS = 4294967295
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
STARTED = time.time()
TOPNET = "../topnet1"
LLVM_MIN = 17
LOG = hou.expandString(OUT + "/log.txt")
WATCH_SECONDS = 15
STAMP = r"\d{8}_\d{6}Z"
SETTINGS = {
    "frequency": FREQUENCY,
    "max_depth": 3,
    "samples": 1000000,
    "max_paths_per_tx": 100000,
    "los": True,
    "specular_reflection": True,
    "diffuse_reflection": False,
    "refraction": True,
    "diffraction": False,
    "bandwidth": 100e6,
    "cfr_points": 256,
    "radiomap_samples": 10000000,
}

INTERACTIONS = {"los": 1, "specular_reflection": 1, "refraction": 1, "diffuse_reflection": 0, "diffraction": 0}
PRESETS = {
    "quality": {
        "laptop_test": dict(INTERACTIONS, target="local", use_gpu=0, max_depth=3, samples=100000, max_paths_per_tx=10000,
                            radiomap_samples=1000000, cfr_points=0, timeout=1800),
        "spark_quick": dict(INTERACTIONS, target="spark", use_gpu=1, max_depth=3, samples=1000000, max_paths_per_tx=100000,
                            radiomap_samples=10000000, cfr_points=0, timeout=1800),
        "spark_standard": dict(INTERACTIONS, target="spark", use_gpu=1, max_depth=5, samples=1000000,
                               max_paths_per_tx=100000, radiomap_samples=20000000, cfr_points=64, timeout=1800),
        "dense_canopy": dict(INTERACTIONS, target="spark", use_gpu=1, max_depth=8, samples=3000000, max_paths_per_tx=200000,
                             radiomap_samples=30000000, cfr_points=64, timeout=3600),
        "batch": dict(INTERACTIONS, target="spark", use_gpu=1, max_depth=5, samples=1000000, max_paths_per_tx=100000,
                      radiomap_samples=10000000, cfr_points=0, timeout=1800),
        "final": dict(INTERACTIONS, target="spark", use_gpu=1, max_depth=8, samples=10000000, max_paths_per_tx=200000,
                      radiomap_samples=100000000, cfr_points=64, diffraction=1, timeout=7200),
    },
    "band": {
        "lora_868": {"frequency": 868e6, "bandwidth": 125e3},
        "lora_915": {"frequency": 915e6, "bandwidth": 125e3},
        "wifi_2g4": {"frequency": 2.437e9, "bandwidth": 20e6},
        "wifi_5g": {"frequency": 5.18e9, "bandwidth": 20e6},
    },
}

CODES = {
    "N001": "scene size: x {x:.2f} m, y {y:.2f} m, z {z:.2f} m (sionna axes, z up)",
    "N002": "exported to {path}",
    "N003": "sionna dump written to {path}",
    "N004": "{count} paths, result written to {path}",
    "N005": "imported {paths} paths, {links} links",
    "N006": "radio map: {cells} cells on {maps} surfaces, {tx} transmitters",
    "N007": "{mode} on target '{target}'",
    "N008": "target '{target}': sionna {version}, runs on the {device}",
    "N009": "batch '{name}': {ok} exported, {failed} failed, written to {path}",
    "N010": "batch '{name}' started on '{target}' (pid {pid}): {count} work items queued, finished ones are skipped",
    "N011": "batch '{name}': {done} solved, {failed} failed, {missing} without result",
    "N012": "cleared {folders} ({size}) on '{target}'",
    "N013": "nothing to clear on '{target}': no {what}",
    "W004": "no rx point: only the radio map will be computed",
    "W005": "material '{material}' is not confirmed: {status}",
    "W006": "gpu on '{target}' in use by other processes: {apps}",
    "W008": "node '{name}' exists but is not a File SOP: result saved to {path} but not loaded; rename that node",
    "W013": "target '{target}': LLVM {version} is older than {minimum}, cpu solves can abort with 'LLVM ERROR: Cannot select'; install libllvm{minimum} or newer",
    "W014": "running batches on '{target}' not cleared: {names}",
    "W012": "{kind} preset '{name}': parms not on this node, left unchanged: {parms}",
    "W010": "material '{material}' at {f:g} GHz is outside its measured range ({ranges} GHz): values extrapolated",
    "W011": "material '{material}' does not use moisture: attribute ignored on {count} primitives",
    "W009": "no string parm 'batch' on this node: add it, the sionna_batch File SOPs read the batch name from it",
    "W001": "scene diagonal is {diag:.3g} m (expected 1 m to 50 km): check units",
    "W002": "{name}: smaller than one wavelength ({lam:.3f} m)",
    "W003": "device '{name}': {dist:.3g} m away from the geometry",
    "V001": "no primitives",
    "V002": "missing prim attribute '{attr}'",
    "V003": "prim {prim}: not a triangle",
    "V004": "prim {prim}: zero area",
    "V005": "prim {prim}: invalid name '{name}'",
    "V006": "prim {prim}: material attributes differ within name '{name}'",
    "V007": "{name}: unknown material '{material}'",
    "V008": "{name}: thickness < 0",
    "V009": "{name}: scattering_coefficient outside [0, 1]",
    "V010": "prim {prim}: empty name",
    "V011": "{name}: material '{material}' resolves to invalid permittivity or conductivity",
    "V012": "{name}: moisture {value:g} % outside 0 to 100",
    "V101": "missing point attribute '{attr}'",
    "V102": "no {role} point",
    "V103": "device with empty name",
    "V104": "duplicate device name '{name}'",
    "V105": "tx '{tx}' and rx '{rx}' at same position",
    "V106": "point {pt}: loose point with missing or invalid role '{role}'",
    "V107": "nothing to compute: no rx point and no measurement surface (material 'measure')",
    "E001": "cannot create output directory '{path}'",
    "E002": "cannot write file '{path}'",
    "E003": "hip file is not saved",
    "S001": "python executable not found '{path}'",
    "S002": "solver script not found '{path}'",
    "S003": "solver exited with code {code}: {err} (full output in solver.log)",
    "S004": "solver timed out after {seconds}s",
    "S005": "solver produced no result file",
    "S006": "no exported run found, export first",
    "S008": "frequency changed since export ({exported:g} Hz exported, {current:g} Hz now): export again",
    "S009": "program not found: '{path}'",
    "S011": "python on target '{target}' failed: {err}",
    "S010": "radio map needs {rays:.3g} rays ({samples:.3g} samples x {tx} tx), more than sionna's limit of "
            "4.29e9 per radio map: set radiomap_samples to {max} or lower",
    "T001": "target '{target}' unreachable (vpn, ssh alias or key): {err}",
    "T002": "no python at '{path}' on target '{target}'",
    "T003": "no gpu on target '{target}': {err} (switch use_gpu off to run on the cpu)",
    "T004": "file transfer with '{target}' failed: {err}",
    "T005": "no cpu backend on target '{target}': {err} (is the LLVM library installed?)",
    "I001": "result file not found '{path}'",
    "I002": "result file unreadable or wrong format",
    "I003": "result does not match current scene (device names differ)",
    "P001": "unknown {kind} preset '{name}', choose one of: {names}",
    "B001": "TOP node not found: '{path}'",
    "B002": "no work items with index {start} to {end} on '{path}'",
    "B003": "no batch found{name}, run batch export first",
    "B004": "batch '{name}' is already running on '{target}' (pid {pid})",
    "B007": "nothing to solve in batch '{name}'",
    "B008": "input did not cook: {err}",
    "B009": "batch_name '{name}' may only contain letters, digits, _ and -",
    "C001": "clear on '{target}' failed: {err}",
}


# --- messages ---

def fmt(rec):
    code, ctx = rec
    return f"{code} {CODES[code].format(**ctx)}"


def has_errors(recs):
    return any(r[0][0] not in "WN" for r in recs)


def say(phase, text):
    for line in str(text).splitlines() or [""]:
        print(f"[sionna {phase}] {line}", flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as fh:
        fh.write(f"{stamp} {phase} {text}\n")


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def report(phase, recs):
    for r in recs:
        say(phase, fmt(r))
    errors = sum(1 for r in recs if r[0][0] not in "WN")
    warnings = sum(1 for r in recs if r[0][0] == "W")
    status = "FAILED" if errors else "passed"
    say(phase, f"{phase} {status} ({plural(errors, 'error')}, {plural(warnings, 'warning')}) "
               f"after {time.time() - STARTED:.1f} s")


def short(names, n=3):
    names = list(names)
    return ", ".join(names[:n]) + (f", ... {names[-1]}" if len(names) > n else "")


def size(n):
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


# --- materials ---

def library():
    path = hou.expandString(OUT + "/materials.json")
    if not os.path.isfile(path):
        return {}
    with open(path) as fh:
        return json.load(fh)


MOISTURE_KINDS = ("vegetation", "soil")


def water_eps(f, temp_c, sigma_ion):
    theta = 1 - 300.0 / (temp_c + 273.15)
    es = 77.66 - 103.3 * theta
    einf = 0.0671 * es
    fr = (20.20 + 146.4 * theta + 316.0 * theta ** 2) * 1e9
    return einf + (es - einf) / (1 + 1j * f / fr) - 1j * sigma_ion / (2 * math.pi * f * EPS0)


def vegetation_eps(f, mg, sigma=1.27):
    fg = f / 1e9
    er = 1.7 - 0.74 * mg + 6.16 * mg ** 2
    vfw = mg * (0.55 * mg - 0.076)
    vb = 4.64 * mg ** 2 / (1 + 7.36 * mg ** 2)
    free = 4.9 + 75.0 / (1 + 1j * fg / 18.0) - 1j * 18.0 * sigma / fg
    bound = 2.9 + 55.0 / (1 + (1j * fg / 0.18) ** 0.5)
    return er + vfw * free + vb * bound


def pure_water(fg, temp_c):
    th = 300.0 / (temp_c + 273.15) - 1
    es = 77.66 + 103.3 * th
    e1 = 0.0671 * es
    einf = 3.52 - 7.52 * th
    f1 = 20.20 - 146.4 * th + 316.0 * th ** 2
    f2 = 39.8 * f1
    re = (es - e1) / (1 + (fg / f1) ** 2) + (e1 - einf) / (1 + (fg / f2) ** 2) + einf
    im = (fg / f1) * (es - e1) / (1 + (fg / f1) ** 2) + (fg / f2) * (e1 - einf) / (1 + (fg / f2) ** 2)
    return re, im


def soil_eps(f, entry, moisture):
    fg, ps, pc = f / 1e9, entry["sand"], entry["clay"]
    rs, rb, mv, a = entry["specific_gravity"], entry["bulk_density"], moisture / 100.0, 0.65
    esm = (1.01 + 0.44 * rs) ** 2 - 0.062
    b1 = 1.2748 - 0.00519 * ps - 0.00152 * pc
    b2 = 1.33797 - 0.00603 * ps - 0.00166 * pc
    s1 = 0.0467 + 0.2204 * rb - 0.004111 * ps - 0.006614 * pc
    s2 = -1.645 + 1.939 * rb - 0.0225622 * ps + 0.01594 * pc
    se1 = (fg / 1.35) * (s1 - s2) / (1 + (fg / 1.35) ** 2)
    se2 = s2 + (s1 - s2) / (1 + (fg / 1.35) ** 2)
    wr, wi = pure_water(fg, entry.get("temperature_c", 20.0))
    k = 18.0 / fg * (rs - rb) / (rs * mv)
    re = (1 + rb / rs * (esm ** a - 1) + mv ** b1 * (wr + se1 * k) ** a - mv) ** (1 / a)
    im = (mv ** b2 * (wi + se2 * k) ** a) ** (1 / a)
    return re, im


def itu_row(entry, fg):
    rows = entry["ranges_ghz"]
    for row in rows:
        if row[0] <= fg <= row[1]:
            return row
    return min(rows, key=lambda r: min(abs(math.log(fg / r[0])), abs(math.log(fg / r[1]))))


def uses_moisture(entry):
    return entry.get("kind") in MOISTURE_KINDS


def measured_ranges(entry):
    if entry.get("kind") == "itu":
        return [(r[0], r[1]) for r in entry["ranges_ghz"]]
    return [tuple(entry["range_ghz"])] if "range_ghz" in entry else []


def outside_range(entry, f):
    ranges = measured_ranges(entry)
    return bool(ranges) and not any(lo <= f / 1e9 <= hi for lo, hi in ranges)


def resolve(entry, f, moisture=0.0):
    w = 2 * math.pi * f * EPS0
    kind = entry.get("kind", "fixed")
    wet = moisture if moisture > 0 else entry.get("moisture", 0.0)
    if kind == "water":
        eps = water_eps(f, entry.get("temperature_c", 25.0), entry.get("ionic_conductivity", 0.0))
        return eps.real, -eps.imag * w
    if kind == "vegetation":
        eps = vegetation_eps(f, wet / 100.0)
        return eps.real, -eps.imag * w
    if kind == "soil":
        re, im = soil_eps(f, entry, wet)
        return re, im * w
    if kind == "itu":
        _, _, a, b, c, d = itu_row(entry, f / 1e9)
        return a * (f / 1e9) ** b, c * (f / 1e9) ** d
    if kind == "conductor":
        return 1.0, entry["conductivity"]
    if kind == "cole_cole":
        ei, es = entry["eps_inf"], entry["eps_s"]
        eps = ei + (es - ei) / (1 + (1j * 2 * math.pi * f * entry["tau"]) ** (1 - entry["alpha"]))
        eps += entry["sigma_s"] / (1j * w)
        return eps.real, -eps.imag * w
    er = entry["relative_permittivity"]
    if "conductivity" in entry:
        return er, entry["conductivity"]
    if "loss_factor" in entry:
        return er, entry["loss_factor"] * w
    return er, er * entry.get("loss_tangent", 0.0) * w


def object_names(geo, names=None, lib=None):
    import numpy as np
    names = np.array(geo.primStringAttribValues("name")) if names is None else names
    if not geo.findPrimAttrib("moisture"):
        return names
    lib = library() if lib is None else lib
    wet = [m for m, e in lib.items() if uses_moisture(e)]
    mats = np.array(geo.primStringAttribValues("material"))
    m = np.round(np.array(prim_values(geo, "moisture"), dtype=float)).astype(int)
    use = np.isin(mats, wet) & (m > 0)
    return np.where(use, np.char.add(np.char.add(names, "_m"), m.astype(str)), names)


def ray_limit(scene, s):
    measure = scene.replace("_scene.xml", "_measure.json")
    txrx = scene.replace("_scene.xml", "_txrx.json")
    if not (os.path.isfile(measure) and os.path.isfile(txrx)):
        return []
    with open(measure) as fh:
        names = json.load(fh)
    with open(txrx) as fh:
        ntx = len(json.load(fh)["tx"])
    rays = s["radiomap_samples"] * ntx
    if names and rays > MAX_RAYS:
        return [("S010", {"rays": rays, "samples": s["radiomap_samples"], "tx": ntx, "max": MAX_RAYS // ntx})]
    return []


def stale(scene, s):
    path = scene.replace("_scene.xml", "_materials.json")
    if not os.path.isfile(path):
        return []
    with open(path) as fh:
        f = json.load(fh)["frequency"]
    if abs(f - s["frequency"]) < 1:
        return []
    return [("S008", {"exported": f, "current": s["frequency"]})]


# --- validate ---

SCAN = """
int pts[] = primpoints(0, @primnum);
i@sionna_nv = len(pts);
i@sionna_closed = primintrinsic(0, "closed", @primnum);
s@sionna_type = primintrinsic(0, "typename", @primnum);
i@sionna_p0 = len(pts) > 0 ? pts[0] : -1;
i@sionna_p1 = len(pts) > 1 ? pts[1] : -1;
i@sionna_p2 = len(pts) > 2 ? pts[2] : -1;
addpointattrib(0, "sionna_used", 0);
foreach (int pt; pts)
    setpointattrib(0, "sionna_used", pt, 1);
"""


def scan(geo):
    import numpy as np
    src = geo.sopNode()
    with hou.undos.disabler():
        wrangle = src.parent().createNode("attribwrangle", "sionna_scan")
        try:
            wrangle.setInput(0, src)
            wrangle.parm("class").set(1)
            wrangle.parm("snippet").set(SCAN)
            out = wrangle.geometry()
            res = {
                "tri": np.array([out.primIntAttribValues(f"sionna_p{i}") for i in range(3)]).T.reshape(-1, 3),
                "ok": (np.array(out.primStringAttribValues("sionna_type")) == "Poly")
                      & (np.array(out.primIntAttribValues("sionna_nv")) == 3)
                      & (np.array(out.primIntAttribValues("sionna_closed")) == 1),
                "used": np.array(out.pointIntAttribValues("sionna_used")) == 1,
            }
        finally:
            wrangle.destroy()
    res["P"] = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), dtype=np.float32).reshape(-1, 3).astype(float)
    return res


def prim_values(geo, name):
    kind = geo.findPrimAttrib(name).dataType()
    if kind == hou.attribData.String:
        return geo.primStringAttribValues(name)
    if kind == hou.attribData.Int:
        return geo.primIntAttribValues(name)
    return geo.primFloatAttribValues(name)


def sionna_axes(v):
    return v[:, [0, 2, 1]] * (1.0, -1.0, 1.0)


def validate(geo, frequency=FREQUENCY):
    import numpy as np
    if not geo.intrinsicValue("primitivecount"):
        return [("V001", {})]
    recs = [("V002", {"attr": a}) for a in ("name", "material") if geo.findPrimAttrib(a) is None]
    if recs:
        return recs

    s = scan(geo)
    P, tri, ok, used = s["P"], s["tri"], s["ok"], s["used"]
    names = np.array(geo.primStringAttribValues("name"))
    corner = P[np.where(ok[:, None], tri, 0)]
    area = 0.5 * np.linalg.norm(np.cross(corner[:, 1] - corner[:, 0], corner[:, 2] - corner[:, 0]), axis=1)
    uniq, inv = np.unique(names, return_inverse=True)
    valid = np.array([bool(re.fullmatch(r"[A-Za-z0-9_-]+", u)) for u in uniq.tolist()])[inv.ravel()]
    recs += [("V003", {"prim": i}) for i in np.nonzero(~ok)[0].tolist()]
    recs += [("V004", {"prim": i}) for i in np.nonzero(ok & (area < 1e-12))[0].tolist()]
    recs += [("V010", {"prim": i}) for i in np.nonzero(ok & (names == ""))[0].tolist()]
    recs += [("V005", {"prim": i, "name": names[i]}) for i in np.nonzero(ok & (names != "") & ~valid)[0].tolist()]
    lib = library()
    names = object_names(geo, names, lib)

    present = [a for a in MAT_ATTRS if geo.findPrimAttrib(a)]
    cols = [prim_values(geo, a) for a in present]
    good = np.nonzero(ok & valid)[0]
    _, first, ginv = np.unique(names[good], return_index=True, return_inverse=True)
    ginv = ginv.ravel()
    diff = np.zeros(len(good), bool)
    for c in cols:
        c = np.array(c)[good]
        diff |= c != c[first][ginv]
    recs += [("V006", {"prim": int(good[k]), "name": str(names[good[k]])}) for k in np.nonzero(diff)[0]]
    order = sorted(first.tolist())
    seen = {str(names[good[f]]): tuple(c[good[f]] for c in cols) for f in order}
    moist = np.array(prim_values(geo, "moisture"), dtype=float) if geo.findPrimAttrib("moisture") else None
    wet = {str(names[good[f]]): float(round(moist[good[f]])) if moist is not None else 0.0 for f in order}
    if moist is not None:
        bad = (moist < 0) | (moist > 100)
        for n in dict.fromkeys(names[bad].tolist()):
            recs.append(("V012", {"name": n, "value": float(moist[names == n][0])}))
        mats = np.array(prim_values(geo, "material"))
        for mat in sorted(set(mats[moist > 0].tolist()) - {MEASURE}):
            if not uses_moisture(lib.get(mat, {})):
                recs.append(("W011", {"material": mat, "count": int(((mats == mat) & (moist > 0)).sum())}))

    warned = set()
    for name, vals in seen.items():
        v = dict(zip(present, vals))
        mat = v["material"]
        if mat == MEASURE:
            continue
        if mat in lib:
            try:
                er, sigma = resolve(lib[mat], frequency, wet[name] if uses_moisture(lib[mat]) else 0.0)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                er, sigma = 0.0, -1.0
            status = lib[mat].get("status", "no status")
            if er < 1 or sigma < 0:
                recs.append(("V011", {"name": name, "material": mat}))
            elif mat not in warned:
                warned.add(mat)
                if status != "confirmed":
                    recs.append(("W005", {"material": mat, "status": status}))
                if outside_range(lib[mat], frequency):
                    ranges = ", ".join(f"{lo:g} to {hi:g}" for lo, hi in measured_ranges(lib[mat]))
                    recs.append(("W010", {"material": mat, "f": frequency / 1e9, "ranges": ranges}))
        elif mat not in ITU:
            recs.append(("V007", {"name": name, "material": mat}))
        if v.get("thickness", 0.1) < 0:
            recs.append(("V008", {"name": name}))
        if not 0 <= v.get("scattering_coefficient", 0) <= 1:
            recs.append(("V009", {"name": name}))

    lo, hi = P[used].min(axis=0), P[used].max(axis=0)
    size = (hi - lo).tolist()
    diag = float(np.linalg.norm(hi - lo))
    recs.insert(0, ("N001", {"x": size[0], "y": size[2], "z": size[1]}))
    if not 1 <= diag <= 50000:
        recs.append(("W001", {"diag": diag}))
    lam = 299792458 / frequency
    if len(good):
        blo = np.full((len(first), 3), np.inf)
        bhi = -blo
        np.minimum.at(blo, ginv, corner[good].min(axis=1))
        np.maximum.at(bhi, ginv, corner[good].max(axis=1))
        small = (bhi - blo).max(axis=1) < lam
        recs += [("W002", {"name": str(names[good[first[k]]]), "lam": lam})
                 for k in sorted(range(len(first)), key=lambda k: first[k]) if small[k]]

    missing = [a for a in ("role", "name") if geo.findPointAttrib(a) is None]
    if missing:
        return recs + [("V101", {"attr": a}) for a in missing]

    roles = np.array(geo.pointStringAttribValues("role"))
    pnames = np.array(geo.pointStringAttribValues("name"))
    tx, rx = roles == "tx", roles == "rx"
    dev = tx | rx
    recs += [("V106", {"pt": i, "role": str(roles[i])}) for i in np.nonzero(~dev & ~used)[0].tolist()]
    if not tx.any():
        recs.append(("V102", {"role": "tx"}))
    if not rx.any():
        measure = any(dict(zip(present, v))["material"] == MEASURE for v in seen.values())
        recs.append(("W004", {}) if measure else ("V107", {}))
    if (pnames[dev] == "").any():
        recs.append(("V103", {}))
    dup, counts = np.unique(pnames[dev & (pnames != "")], return_counts=True)
    recs += [("V104", {"name": n}) for n in dup[counts > 1].tolist()]
    close = np.linalg.norm(P[tx][:, None] - P[rx][None], axis=2) < 1e-4
    recs += [("V105", {"tx": str(pnames[tx][i]), "rx": str(pnames[rx][j])}) for i, j in zip(*np.nonzero(close))]
    dist = np.linalg.norm(P[dev] - np.clip(P[dev], lo, hi), axis=1)
    recs += [("W003", {"name": str(n), "dist": float(d)}) for n, d in zip(pnames[dev], dist) if d > diag]
    return recs


def frequency(node):
    parm = node.parm("frequency")
    return parm.eval() if parm else FREQUENCY


def inventory(phase, geo, f, node):
    if geo.findPrimAttrib("name") and geo.findPrimAttrib("material"):
        mats = geo.primStringAttribValues("material")
        names = geo.primStringAttribValues("name")
        tris, objs = {}, {}
        for m, n in zip(mats, names):
            tris[m] = tris.get(m, 0) + 1
            objs.setdefault(m, set()).add(n)
        lib = library()
        scene = sorted(m for m in tris if m != MEASURE)
        say(phase, f"scene: {plural(sum(len(objs[m]) for m in scene), 'object')}, "
                   f"{plural(sum(tris[m] for m in scene), 'triangle')}, {plural(len(scene), 'material')}")
        for m in scene:
            kind = lib[m].get("kind", "fixed") if m in lib else "ITU" if m in ITU else "unknown"
            say(phase, f"  {m:<22} {kind:<8} {plural(len(objs[m]), 'object'):>12} {plural(tris[m], 'triangle'):>16}")
        if MEASURE in tris:
            say(phase, f"radio map surfaces: {short(sorted(objs[MEASURE]))} ({plural(tris[MEASURE], 'cell')})")
        else:
            say(phase, "radio map surfaces: none, solve computes paths only")
    if geo.findPointAttrib("role") and geo.findPointAttrib("name"):
        roles = geo.pointStringAttribValues("role")
        names = geo.pointStringAttribValues("name")
        tx = [n for r, n in zip(roles, names) if r == "tx"]
        rx = [n for r, n in zip(roles, names) if r == "rx"]
        say(phase, f"devices: {len(tx)} tx ({short(tx)}), {len(rx)} rx ({short(rx)})")
    say(phase, f"frequency {f / 1e9:g} GHz (wavelength {299792458 / f * 100:.1f} cm), target {target(node)}")


def on_validate():
    node = hou.pwd()
    geo, f = node.inputs()[0].geometry(), frequency(node)
    recs = validate(geo, f)
    inventory("validate", geo, f, node)
    report("validate", recs)
    return recs


# --- export ---

def materials(geo):
    import numpy as np
    lib = library()
    names = object_names(geo, lib=lib).tolist()
    cols = {a: prim_values(geo, a) for a in MAT_ATTRS + ("moisture",) if geo.findPrimAttrib(a)}
    out = {}
    for i in sorted(np.unique(names, return_index=True)[1].tolist()):
        v = {a: c[i] for a, c in cols.items()}
        wet = float(round(v.get("moisture", 0.0))) if uses_moisture(lib.get(v["material"], {})) else 0.0
        out[names[i]] = (v["material"], v.get("thickness", 0.0), v.get("scattering_coefficient", 0.0), max(wet, 0.0))
    return out


def resolved(geo, f):
    lib = library()
    out = {}
    for name, (mat, thick, scat, wet) in materials(geo).items():
        if mat == MEASURE:
            continue
        entry = lib.get(mat, {})
        d = {
            "material": mat,
            "thickness": thick if thick > 0 else entry.get("thickness", 0.1),
            "scattering_coefficient": scat if scat > 0 else entry.get("scattering_coefficient", 0.0),
        }
        if mat in lib:
            d["relative_permittivity"], d["conductivity"] = resolve(entry, f, wet)
            if uses_moisture(entry):
                d["moisture"] = wet if wet > 0 else entry.get("moisture", 0.0)
            d["xpd_coefficient"] = entry.get("xpd_coefficient", 0.0)
            d["source"] = entry.get("source", "")
            d["status"] = entry.get("status", "no status")
        out[name] = d
    return out


def bsdf_id(d):
    keys = (("t", "thickness"), ("s", "scattering_coefficient"), ("m", "moisture"))
    parts = [f"{k}{d[a]:g}".replace(".", "p") for k, a in keys if a in d]
    return "_".join([d["material"]] + parts)


def build_xml(objs):
    lines, done = ['<scene version="2.1.0">'], set()
    for d in objs.values():
        i = bsdf_id(d)
        if i in done:
            continue
        done.add(i)
        if "relative_permittivity" in d:
            lines += [
                f'    <bsdf type="radio-material" id="{i}">',
                f'        <float name="relative_permittivity" value="{d["relative_permittivity"]:.6g}"/>',
                f'        <float name="conductivity" value="{d["conductivity"]:.6g}"/>',
                f'        <float name="xpd_coefficient" value="{d["xpd_coefficient"]:g}"/>',
            ]
        else:
            lines += [
                f'    <bsdf type="itu-radio-material" id="{i}">',
                f'        <string name="type" value="{d["material"]}"/>',
            ]
        lines += [
            f'        <float name="thickness" value="{d["thickness"]:g}"/>',
            f'        <float name="scattering_coefficient" value="{d["scattering_coefficient"]:g}"/>',
            '    </bsdf>',
        ]
    for name, d in objs.items():
        lines += [
            f'    <shape type="ply" id="mesh-{name}">',
            f'        <string name="filename" value="meshes/{name}.ply"/>',
            '        <boolean name="face_normals" value="true"/>',
            f'        <ref id="{bsdf_id(d)}" name="bsdf"/>',
            '    </shape>',
        ]
    lines.append('</scene>')
    return "\n".join(lines)


def build_devices(geo):
    import numpy as np

    def vec(attr):
        if geo.findPointAttrib(attr):
            return np.array(geo.pointFloatAttribValues(attr)).reshape(-1, 3)
        return np.zeros((len(roles), 3))

    def rnd(v):
        return [round(float(c), 6) for c in v]

    roles = geo.pointStringAttribValues("role")
    names = geo.pointStringAttribValues("name")
    pos = sionna_axes(vec("P"))
    ori, vel = vec("orientation"), sionna_axes(vec("velocity"))
    power = geo.pointFloatAttribValues("power_dbm") if geo.findPointAttrib("power_dbm") else None
    out = {"tx": [], "rx": []}
    for i, role in enumerate(roles):
        if role not in out:
            continue
        d = {"name": names[i], "position": rnd(pos[i]), "orientation": rnd(ori[i]), "velocity": rnd(vel[i])}
        if role == "tx" and power is not None:
            d["power_dbm"] = round(power[i], 6)
        out[role].append(d)
    return out


def write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def write_meshes(geo, folder):
    import numpy as np
    s = scan(geo)
    names, _, group = np.unique(object_names(geo), return_index=True, return_inverse=True)
    group = group.ravel()
    prims = np.split(np.argsort(group, kind="stable"), np.cumsum(np.bincount(group))[:-1])
    for name, idx in zip(names.tolist(), prims):
        u, inv = np.unique(s["tri"][idx].ravel(), return_inverse=True)
        write_ply(f"{folder}/{name}.ply", sionna_axes(s["P"][u]), inv.reshape(-1, 3)[:, ::-1])


def write_ply(path, pts, faces):
    import numpy as np
    tri = np.zeros(len(faces), dtype=[("n", "u1"), ("i", "<i4", 3)])
    tri["n"], tri["i"] = 3, faces
    header = (
        f"ply\nformat binary_little_endian 1.0\nelement vertex {len(pts)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        f"element face {len(faces)}\n"
        "property list uchar int vertex_indices\nend_header\n"
    )
    with open(path, "wb") as fh:
        fh.write(header.encode("ascii"))
        fh.write(np.asarray(pts, dtype="<f4").tobytes())
        fh.write(tri.tobytes())


def export_run(geo, f, folder, recs, extra):
    hip = hou.expandString("$HIPNAME")
    try:
        os.makedirs(folder + "/meshes")
    except OSError:
        recs.append(("E001", {"path": folder}))
        return None
    try:
        geo.saveToFile(folder + "/scene.bgeo.sc")
        write_meshes(geo, folder + "/meshes")
        objs = resolved(geo, f)
        write(f"{folder}/{hip}_scene.xml", build_xml(objs))
        write(f"{folder}/{hip}_materials.json", json.dumps({"frequency": f, "objects": objs}, indent=2))
        write(f"{folder}/{hip}_txrx.json", json.dumps(build_devices(geo), indent=2))
        measure = [n for n, m in materials(geo).items() if m[0] == MEASURE]
        write(f"{folder}/{hip}_measure.json", json.dumps(measure))
        meta = {"exported_utc": time.strftime("%Y%m%d_%H%M%SZ", time.gmtime()),
                "hip": hou.hipFile.path(), "houdini": hou.applicationVersionString()}
        meta.update(extra)
        write(f"{folder}/{hip}_meta.json", json.dumps(meta, indent=2))
        recs.append(("N002", {"path": folder}))
        write(f"{folder}/{hip}_log.txt", "\n".join(fmt(r) for r in recs) + "\n")
        return objs, measure, meta
    except (OSError, hou.Error) as e:
        recs.append(("E002", {"path": getattr(e, "filename", None) or folder}))
        return None


def on_export(checked=None):
    node = hou.pwd()
    if hou.hipFile.isNewFile():
        report("export", [("E003", {})])
        return False
    geo, f = node.inputs()[0].geometry(), frequency(node)
    recs = validate(geo, f) if checked is None else list(checked)
    shown = 0 if checked is None else len(recs)
    if not has_errors(recs):
        folder = hou.expandString(f"{OUT}/data/{time.strftime('%Y%m%d_%H%M%SZ', time.gmtime())}")
        out = export_run(geo, f, folder, recs, git_info())
        if out:
            export_summary("export", folder, f, *out)
    report("export", recs[shown:])
    return not has_errors(recs)


def export_summary(phase, folder, f, objs, measure, meta):
    say(phase, f"run folder {folder}")
    meshes = [os.path.join(folder, "meshes", m) for m in sorted(os.listdir(folder + "/meshes"))]
    say(phase, f"  meshes/  {plural(len(meshes), 'file')}, {size(sum(os.path.getsize(m) for m in meshes))}"
               f" ({plural(len(objs), 'scene object')}, {plural(len(measure), 'radio map surface')})")
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            say(phase, f"  {name}  {size(os.path.getsize(path))}")
    say(phase, f"materials at {f / 1e9:g} GHz:")
    seen = set()
    for d in objs.values():
        key = (d["material"], d.get("moisture"))
        if key in seen:
            continue
        seen.add(key)
        if "relative_permittivity" in d:
            wet = f"  moisture {d['moisture']:g} %" if "moisture" in d else ""
            say(phase, f"  {d['material']:<22} er {d['relative_permittivity']:7.2f}  sigma {d['conductivity']:8.4g} S/m"
                       f"  thickness {d['thickness']:g} m{wet}  [{d['status']}]")
        else:
            say(phase, f"  {d['material']:<22} ITU model, evaluated by sionna  thickness {d['thickness']:g} m")
    commit = meta.get("commit")
    if commit:
        say(phase, f"code version: git {commit[:8]}" + (", with uncommitted changes" if meta.get("dirty") else ""))
    else:
        say(phase, "code version: not in a git repository")


# --- run ---

def latest_run():
    root = hou.expandString(OUT + "/data")
    if not os.path.isdir(root):
        return None
    runs = sorted(d for d in os.listdir(root) if os.path.isdir(f"{root}/{d}"))
    return f"{root}/{runs[-1]}" if runs else None


def clean_env():
    hfs = hou.expandString("$HFS").replace(os.sep, "/").lower()
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    for k in ("PATH", "LD_LIBRARY_PATH"):
        if k in env:
            env[k] = os.pathsep.join(
                p for p in env[k].split(os.pathsep) if hfs not in p.replace(os.sep, "/").lower()
            )
    return env


def call(args, timeout=60):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        args, env=clean_env(), capture_output=True, text=True, timeout=timeout, creationflags=flags,
    )


def tail(text, n=800):
    return text.strip()[-n:]


def git_info():
    try:
        c = call(["git", "-C", hou.expandString("$HIP"), "rev-parse", "HEAD"], 10)
        if c.returncode:
            return {"commit": None, "dirty": None}
        d = call(["git", "-C", hou.expandString("$HIP"), "status", "--porcelain"], 10)
        return {"commit": c.stdout.strip(), "dirty": bool(d.stdout.strip())}
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": None, "dirty": None}


def parm_str(node, name, default):
    parm = node.parm(name)
    return (parm.eval().strip() if parm else "") or default


def target(node):
    return parm_str(node, "target", "local")


def remote_root(node):
    root = parm_str(node, "remote_root", REMOTE_ROOT)
    return root[2:] if root.startswith("~/") else root


def local_python(node):
    return hou.expandString(parm_str(node, "python_exe", PYTHON_EXE))


def use_gpu(node):
    parm = node.parm("use_gpu")
    return bool(parm.eval()) if parm else True


def device(node):
    return "gpu" if use_gpu(node) else "cpu"


def timeout(node):
    parm = node.parm("timeout")
    return int(parm.eval()) if parm else TIMEOUT


def stream(args, seconds, on_line):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    p = subprocess.Popen(
        args, env=clean_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, creationflags=flags,
    )
    killed = []
    timer = threading.Timer(seconds, lambda: (killed.append(1), p.kill()))
    timer.start()
    lines = []
    try:
        for line in p.stdout:
            line = line.rstrip()
            lines.append(line)
            on_line(line)
        p.wait()
    finally:
        timer.cancel()
    if killed:
        raise subprocess.TimeoutExpired(args, seconds)
    return p.returncode, lines


def transfer(phase, src, dst, seconds, *extra):
    files, total, t0 = 0, 0, time.time()

    def line(text):
        nonlocal files, total
        name, _, n = text.rpartition(" ")
        if name and n.isdigit():
            if not name.endswith("/"):
                files += 1
                total += int(n)
                say(phase, f"    {name}  {size(int(n))}")
        elif text:
            say(phase, f"    {text}")

    args = ["rsync", "-a", *extra, "--out-format=%n %l", "-e", "ssh " + " ".join(SSH_OPTS),
            "--exclude", "*.bgeo.sc", "--exclude", "solver.log", src, dst]
    code, lines = stream(args, seconds, line)
    say(phase, f"  {files} files, {size(total)} in {time.time() - t0:.1f} s")
    return code, lines


def ssh(host, cmd, seconds=60):
    return call(["ssh", *SSH_OPTS, host, cmd], seconds)


def gpu_text(info):
    name, _, load = info.rpartition(",")
    return f"{name.strip()}, load {load.strip()}%" if name else "none"


def preflight(node, need_gpu=True):
    host, py = target(node), remote_root(node) + "/venv/bin/python3"
    cmd = (
        f"test -x {shlex.quote(py)} || exit 3; "
        "nvidia-smi --query-gpu=name,utilization.gpu --format=csv,noheader,nounits "
        + ("|| exit 4; " if need_gpu else "2>/dev/null || true; ") +
        "echo ---; nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader || true"
    )
    try:
        r = ssh(host, cmd, 30)
    except subprocess.TimeoutExpired:
        return [("T001", {"target": host, "err": "timeout"})], ""
    if r.returncode == 3:
        return [("T002", {"path": py, "target": host})], ""
    if r.returncode == 4:
        return [("T003", {"target": host, "err": "nvidia-smi failed"})], ""
    if r.returncode:
        return [("T001", {"target": host, "err": tail(r.stderr, 300)})], ""
    gpu, _, apps = r.stdout.partition("---")
    apps = [a.strip() for a in apps.strip().splitlines() if a.strip()]
    recs = [("W006", {"target": host, "apps": "; ".join(apps)})] if apps else []
    return recs, gpu.strip().splitlines()[0] if gpu.strip() else ""


def run_sionna(node, mode, folder, phase):
    script = hou.expandString(OUT + "/sionna_run.py")
    if not os.path.isfile(script):
        return [("S002", {"path": script})]
    shutil.copy2(script, folder + "/sionna_run.py")
    host, seconds = target(node), timeout(node)
    t0 = time.time()

    def echo(text):
        say(phase, f"  {host} | {text}")

    try:
        if host == "local":
            exe = local_python(node)
            if not os.path.isfile(exe):
                return [("S001", {"path": exe})]
            say(phase, f"run {mode} locally on the {device(node)} with {exe}")
            code, lines = stream([exe, "-u", folder + "/sionna_run.py", mode, folder, device(node)], seconds, echo)
        else:
            say(phase, f"target {host}: checking")
            pre, info = preflight(node, use_gpu(node))
            if has_errors(pre):
                return pre
            busy = [r[1]["apps"] for r in pre if r[0] == "W006"]
            say(phase, f"target {host}: gpu {gpu_text(info)}, other compute processes: {busy[0] if busy else 'none'}, "
                       f"runs on the {device(node)}")
            recs = pre
            root = remote_root(node)
            rdir = f"{root}/runs/{hou.expandString('$HIPNAME')}/{os.path.basename(folder)}"
            mk = ssh(host, f"mkdir -p {shlex.quote(rdir)}")
            if mk.returncode:
                return recs + [("T004", {"target": host, "err": tail(mk.stderr, 300)})]
            say(phase, f"send to {host}:{rdir}")
            c, out = transfer(phase, folder + "/", f"{host}:{rdir}/", seconds, "--delete")
            if c:
                return recs + [("T004", {"target": host, "err": tail("\n".join(out), 300)})]
            say(phase, f"run {mode} on {host}")
            py, run = shlex.quote(root + "/venv/bin/python3"), shlex.quote(rdir + "/sionna_run.py")
            code, lines = stream(["ssh", *SSH_OPTS, host, f"{py} -u {run} {mode} {shlex.quote(rdir)} {device(node)}"],
                                 seconds, echo)
            if code == 255:
                return recs + [("T001", {"target": host, "err": tail("\n".join(lines), 300)})]
        if code == 0 and host != "local":
            say(phase, f"receive from {host}:{rdir}")
            c, out = transfer(phase, f"{host}:{rdir}/", folder + "/", seconds)
            if c:
                return recs + [("T004", {"target": host, "err": tail("\n".join(out), 300)})]
    except subprocess.TimeoutExpired:
        return [("S004", {"seconds": seconds})]
    except FileNotFoundError as e:
        return [("S009", {"path": e.filename})]
    write(folder + "/solver.log", "\n".join(lines) + "\n")
    say(phase, f"{mode} {'done' if code == 0 else 'failed'} after {time.time() - t0:.1f} s")
    recs = [] if host == "local" else recs
    if code == 3:
        return recs + [("T003", {"target": host, "err": lines[-1] if lines else ""})]
    if code == 4:
        return recs + [("T005", {"target": host, "err": lines[-1] if lines else ""})]
    if code:
        return recs + [("S003", {"code": code, "err": lines[-1] if lines else ""})]
    return recs


# --- check ---

PROBE = """
import json, os, platform
out = {"threads": os.cpu_count(), "cpu": platform.machine()}
try:
    with open("/proc/cpuinfo") as fh:
        out["cpu"] = next(l.split(":", 1)[1].strip() for l in fh if l.lower().startswith("model name")) or out["cpu"]
except (OSError, StopIteration):
    pass
import mitsuba as mi, drjit as dr
for key, variant in (("gpu", "cuda_ad_mono_polarized"), ("cpu", "llvm_ad_mono_polarized")):
    try:
        mi.set_variant(variant)
        dr.eval(mi.Float(1.0) + 1.0)
        out[key + "_error"] = ""
        if key == "cpu" and hasattr(dr.detail, "llvm_version"):
            out["llvm"] = list(dr.detail.llvm_version())
    except Exception as e:
        out[key + "_error"] = (str(e).strip().splitlines() or [type(e).__name__])[-1].split(". ")[0][:200]
import sionna.rt
out["sionna"] = sionna.rt.__version__
print(json.dumps(out))
"""


def on_check():
    node = hou.pwd()
    host, gpu = target(node), use_gpu(node)
    try:
        if host == "local":
            exe = local_python(node)
            if not os.path.isfile(exe):
                report("check", [("S001", {"path": exe})])
                return
            recs, info = [], ""
            try:
                g = call(["nvidia-smi", "--query-gpu=name,utilization.gpu", "--format=csv,noheader,nounits"], 30)
                info = g.stdout.strip().splitlines()[0] if g.returncode == 0 and g.stdout.strip() else ""
            except FileNotFoundError:
                pass
            r = call([exe, "-c", PROBE], 300)
        else:
            recs, info = preflight(node, False)
            if has_errors(recs):
                report("check", recs)
                return
            py = shlex.quote(remote_root(node) + "/venv/bin/python3")
            r = ssh(host, f"{py} -c {shlex.quote(PROBE)}", 300)
    except subprocess.TimeoutExpired:
        report("check", [("S004", {"seconds": 300})])
        return
    except FileNotFoundError as e:
        report("check", [("S009", {"path": e.filename})])
        return
    lines = r.stdout.strip().splitlines()
    try:
        p = json.loads(lines[-1])
    except (IndexError, ValueError):
        err = r.stderr.strip().splitlines() or [f"exit code {r.returncode}"]
        for line in err[-6:-1]:
            say("check", f"  {host} | {line}")
        report("check", recs + [("S011", {"target": host, "err": err[-1]})])
        return
    say("check", f"target {host}: sionna {p['sionna']}")
    gpu_err, cpu_err = p["gpu_error"], p["cpu_error"]
    say("check", "  gpu: " + (f"not available ({gpu_err})" if gpu_err else gpu_text(info) if info else "available"))
    llvm = p.get("llvm")
    say("check", f"  cpu: {p['cpu']}, {p['threads']} threads, " + (f"not available ({cpu_err})" if cpu_err
                                                                   else "available") +
        (f", LLVM {'.'.join(map(str, llvm))}" if llvm else ""))
    say("check", f"  selected: {device(node)} (use_gpu {'on' if gpu else 'off'})")
    if gpu and gpu_err:
        recs.append(("T003", {"target": host, "err": gpu_err}))
    elif not gpu and cpu_err:
        recs.append(("T005", {"target": host, "err": cpu_err}))
    else:
        if not gpu and llvm and llvm[0] < LLVM_MIN:
            recs.append(("W013", {"target": host, "version": ".".join(map(str, llvm)), "minimum": LLVM_MIN}))
        recs.append(("N008", {"target": host, "version": p["sionna"], "device": device(node)}))
    report("check", recs)


# --- previz ---

def from_sionna(v):
    return (v[0], v[2], -v[1])


def file_sop(node, name, path, offset, **parms):
    target = node.parent().node(name)
    if target is None:
        target = node.parent().createNode("file", name)
        target.parm("file").set(path)
        for k, v in parms.items():
            target.parm(k).set(v)
        target.setPosition(node.position() + hou.Vector2(*offset))
    elif target.type().name() != "file":
        return None
    target.parm("reload").pressButton()
    return target


def load_result(node, name, path, offset, recs, **parms):
    target = file_sop(node, name, path, offset, **parms)
    if target is None:
        recs.append(("W008", {"name": name, "path": hou.expandString(path)}))
    return target


def on_previz():
    node = hou.pwd()
    folder = latest_run()
    if not folder:
        report("previz", [("S006", {})])
        return
    recs = run_sionna(node, "dump", folder, "previz")
    if not has_errors(recs):
        found = glob.glob(folder + "/*_dump.json")
        if found:
            geo = build_previz(found[0])
            roles = geo.pointStringAttribValues("role")
            say("previz", f"loaded by sionna: {plural(len(set(geo.primStringAttribValues('name'))), 'object')}, "
                          f"{plural(len(geo.prims()), 'triangle')}, {roles.count('tx')} tx, {roles.count('rx')} rx")
            geo.saveToFile(found[0].replace("_dump.json", "_previz.bgeo.sc"))
            geo.saveToFile(hou.expandString(OUT + "/previz.bgeo.sc"))
            recs.append(("N003", {"path": found[0]}))
        else:
            recs.append(("S005", {}))
    if not has_errors(recs):
        target = load_result(node, "sionna_previz", OUT + "/previz.bgeo.sc", (3, 0), recs)
        if target:
            target.setDisplayFlag(True)
    report("previz", recs)


def build_previz(path):
    with open(path) as fh:
        data = json.load(fh)
    geo = hou.Geometry()

    floats = ("thickness", "scattering_coefficient", "relative_permittivity", "conductivity")
    for a in ("name", "material"):
        geo.addAttrib(hou.attribType.Prim, a, "")
    for a in floats:
        geo.addAttrib(hou.attribType.Prim, a, 0.0)
    for a in ("name", "role"):
        geo.addAttrib(hou.attribType.Point, a, "")
    for a in ("sionna_rt", "variant"):
        geo.addAttrib(hou.attribType.Global, a, "")
        geo.setGlobalAttribValue(a, data[a])

    for o in data["objects"]:
        pts = geo.createPoints([from_sionna(v) for v in o["vertices"]])
        for f in o["faces"]:
            poly = geo.createPolygon()
            for i in reversed(f):
                poly.addVertex(pts[i])
            poly.setAttribValue("name", o["name"])
            poly.setAttribValue("material", o["itu_type"] or o["material"])
            for a in floats:
                poly.setAttribValue(a, o[a])
    for role in ("tx", "rx"):
        for d in data[role]:
            pt = geo.createPoint()
            pt.setPosition(from_sionna(d["position"]))
            pt.setAttribValue("name", d["name"])
            pt.setAttribValue("role", role)
    return geo


# --- solve ---

def settings(node):
    out = {}
    for k, v in SETTINGS.items():
        parm = node.parm(k)
        out[k] = type(v)(parm.eval()) if parm else v
    return out


def on_solve():
    node = hou.pwd()
    folder = latest_run()
    if not folder:
        report("solve", [("S006", {})])
        return False
    scene = glob.glob(folder + "/*_scene.xml")[0]
    for suffix in ("_result.npz", "_radiomap.npz"):
        old = scene.replace("_scene.xml", suffix)
        if os.path.isfile(old):
            os.remove(old)
    s = settings(node)
    write(scene.replace("_scene.xml", "_settings.json"), json.dumps(s, indent=2))
    say("solve", f"run folder {folder}")
    recs = stale(scene, s) or ray_limit(scene, s) or run_sionna(node, "solve", folder, "solve")
    if not has_errors(recs):
        result = scene.replace("_scene.xml", "_result.npz")
        rmap = scene.replace("_scene.xml", "_radiomap.npz")
        if os.path.isfile(result):
            d = npz(result, "path_tx")
            recs.append(("N004", {"count": len(d["path_tx"]), "path": result}))
        if os.path.isfile(rmap):
            d = npz(rmap, "cell_map", "map_names", "tx")
            recs.append(("N006", {"cells": len(d["cell_map"]), "maps": len(d["map_names"]), "tx": len(d["tx"])}))
        if not os.path.isfile(result) and not os.path.isfile(rmap):
            recs.append(("S005", {}))
    report("solve", recs)
    return not has_errors(recs)


# --- import ---

PATH_FLOATS = ("gain_db", "tau", "a_re", "a_im", "theta_t", "phi_t", "theta_r", "phi_r", "doppler")
LINK_FLOATS = ("gain_db_coherent", "gain_db_incoherent", "delay_spread")


def npz(path, *keys):
    import numpy as np
    with np.load(path) as d:
        return {k: d[k] for k in (keys or d.files)}


def houdini_axes(v):
    return v[:, [0, 2, 1]] * (1.0, 1.0, -1.0)


def polylines(geo, positions, counts):
    import numpy as np
    geo.createPoints(houdini_axes(positions).tolist())
    start = np.cumsum(counts) - counts
    return geo.createPolygons([list(range(s, s + c)) for s, c in zip(start.tolist(), counts.tolist())], False)


def build_paths(d):
    import numpy as np
    geo = hou.Geometry()
    for a in ("tx", "rx"):
        geo.addAttrib(hou.attribType.Prim, a, "")
    for a in PATH_FLOATS:
        geo.addAttrib(hou.attribType.Prim, a, 0.0)
    geo.addAttrib(hou.attribType.Prim, "bounces", 0)
    geo.addAttrib(hou.attribType.Point, "interaction", 0)
    geo.addAttrib(hou.attribType.Point, "primitive", -1)
    geo.addAttrib(hou.attribType.Point, "object", "")
    tx, rx = d["path_tx"], d["path_rx"]
    if not len(tx):
        return geo
    hop = d["path_interactions"] != 0
    bounces = hop.sum(axis=1)
    counts = bounces + 2
    start = np.cumsum(counts) - counts
    row, k = np.nonzero(hop)
    slot = start[row] + np.cumsum(hop, axis=1)[row, k]
    pos = np.zeros((counts.sum(), 3))
    pos[start] = d["tx_position"][tx]
    pos[start + counts - 1] = d["rx_position"][rx]
    pos[slot] = d["path_vertices"][row, k]
    inter = np.zeros(len(pos), dtype=int)
    inter[slot] = d["path_interactions"][row, k]
    prim = np.full(len(pos), -1)
    prim[slot] = d["path_primitives"][row, k]
    obj = np.full(len(pos), -1)
    obj[slot] = d["path_objects"][row, k]
    names = d["object_names"].tolist() + [""]
    polylines(geo, pos, counts)
    geo.setPointIntAttribValues("interaction", inter.tolist())
    geo.setPointIntAttribValues("primitive", prim.tolist())
    geo.setPointStringAttribValues("object", [names[i] for i in obj.tolist()])
    geo.setPrimStringAttribValues("tx", d["tx"][tx].tolist())
    geo.setPrimStringAttribValues("rx", d["rx"][rx].tolist())
    for a in PATH_FLOATS:
        geo.setPrimFloatAttribValues(a, d["path_" + a].astype(float).tolist())
    geo.setPrimIntAttribValues("bounces", bounces.tolist())
    return geo


def build_links(d):
    import numpy as np
    geo = hou.Geometry()
    for a in ("tx", "rx"):
        geo.addAttrib(hou.attribType.Prim, a, "")
    for a in LINK_FLOATS:
        geo.addAttrib(hou.attribType.Prim, a, 0.0)
    geo.addAttrib(hou.attribType.Prim, "num_paths", 0)
    geo.addArrayAttrib(hou.attribType.Prim, "cfr_db", hou.attribData.Float)
    geo.addArrayAttrib(hou.attribType.Global, "cfr_frequencies", hou.attribData.Float)
    geo.setGlobalAttribValue("cfr_frequencies", d["cfr_frequencies"].tolist())
    num = d["link_num_paths"]
    if not num.size:
        return geo
    r, t = np.divmod(np.arange(num.size), num.shape[1])
    pos = np.empty((2 * num.size, 3))
    pos[0::2] = d["tx_position"][t]
    pos[1::2] = d["rx_position"][r]
    polys = polylines(geo, pos, np.full(num.size, 2))
    geo.setPrimStringAttribValues("tx", d["tx"][t].tolist())
    geo.setPrimStringAttribValues("rx", d["rx"][r].tolist())
    for a in LINK_FLOATS:
        geo.setPrimFloatAttribValues(a, d["link_" + a].ravel().astype(float).tolist())
    geo.setPrimIntAttribValues("num_paths", num.ravel().tolist())
    cfr = d["link_cfr_db"].reshape(num.size, -1)
    if cfr.shape[1]:
        for poly, n, row in zip(polys, num.ravel().tolist(), cfr.tolist()):
            if n:
                poly.setAttribValue("cfr_db", row)
    return geo


KINDS = ("paths", "links", "radiomap")


def to_bgeo(folder):
    out = {}
    for path in glob.glob(folder + "/*_result.npz"):
        out["result"] = d = npz(path)
        out["paths"], out["links"] = build_paths(d), build_links(d)
    for path in glob.glob(folder + "/*_radiomap.npz"):
        out["rmap"] = d = npz(path)
        out["radiomap"] = build_radiomap(d)
    for kind in KINDS:
        if kind in out:
            out[kind].saveToFile(f"{folder}/{kind}.bgeo.sc")
    return out


def on_import():
    node = hou.pwd()
    folder = latest_run()
    if not folder:
        report("import", [("S006", {})])
        return False
    say("import", f"run folder {folder}")
    if not glob.glob(folder + "/*_result.npz") and not glob.glob(folder + "/*_radiomap.npz"):
        report("import", [("I001", {"path": folder})])
        return False
    recs, t0 = [], time.time()
    try:
        out = to_bgeo(folder)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile):
        report("import", [("I002", {})])
        return False
    for i, kind in enumerate(KINDS):
        if kind in out:
            out[kind].saveToFile(hou.expandString(f"{OUT}/{kind}.bgeo.sc"))
            load_result(node, f"sionna_{kind}", f"{OUT}/{kind}.bgeo.sc", (3, -1 - i), recs)
    if "result" in out:
        d = out["result"]
        recs.append(("N005", {"paths": len(out["paths"].prims()), "links": len(out["links"].prims())}))
        gains = d["path_gain_db"][d["path_gain_db"] > -999]
        if len(gains):
            los = int(((d["path_interactions"] != 0).sum(axis=1) == 0).sum())
            say("import", f"paths: gain {gains.min():.1f} to {gains.max():.1f} dB, {los} line of sight")
    if "rmap" in out:
        d = out["rmap"]
        recs.append(("N006", {"cells": len(d["cell_map"]), "maps": len(d["map_names"]), "tx": len(d["tx"])}))
        peak = d["path_gain_db"].max(axis=1)
        if (peak > -999).any():
            say("import", f"radio map: strongest tx per cell {peak[peak > -999].min():.1f} to "
                          f"{peak.max():.1f} dB, {plural(int((peak <= -999).sum()), 'cell')} without signal")
    say("import", f"results written for {', '.join('sionna_' + k for k in KINDS if k in out)} "
                  f"({time.time() - t0:.1f} s)")
    report("import", recs)
    return not has_errors(recs)


# --- run ---

def on_run():
    t0 = time.time()
    recs = on_validate()
    ok = not has_errors(recs) and on_export(recs) and on_solve() and on_import()
    say("run", f"run {'done' if ok else 'stopped'} after {time.time() - t0:.1f} s")


# --- radiomap ---

def build_radiomap(d):
    import numpy as np
    geo = hou.Geometry()
    geo.addAttrib(hou.attribType.Prim, "name", "")
    geo.addAttrib(hou.attribType.Prim, "best_tx_name", "")
    geo.addAttrib(hou.attribType.Prim, "best_tx", -1)
    geo.addAttrib(hou.attribType.Prim, "path_gain_db_max", 0.0)
    geo.addArrayAttrib(hou.attribType.Prim, "path_gain_db", hou.attribData.Float)
    geo.addArrayAttrib(hou.attribType.Global, "tx", hou.attribData.String)
    tx = d["tx"].tolist()
    geo.setGlobalAttribValue("tx", tx)
    g = d["path_gain_db"]
    if not len(g):
        return geo
    geo.createPoints(houdini_axes(d["vertices"]).tolist())
    polys = geo.createPolygons(d["faces"][:, ::-1].tolist())
    peak = g.max(axis=1)
    best = np.where(peak > -999, g.argmax(axis=1), -1)
    for poly, row in zip(polys, g.tolist()):
        poly.setAttribValue("path_gain_db", row)
    geo.setPrimStringAttribValues("name", d["map_names"][d["cell_map"]].tolist())
    geo.setPrimStringAttribValues("best_tx_name", [tx[i] if i >= 0 else "" for i in best.tolist()])
    geo.setPrimIntAttribValues("best_tx", best.tolist())
    geo.setPrimFloatAttribValues("path_gain_db_max", peak.astype(float).tolist())
    return geo


# --- batch ---

def parm_int(node, name, default):
    parm = node.parm(name)
    return int(parm.eval()) if parm else default


def top_node(node):
    path = parm_str(node, "top_node", "") or TOPNET
    top = node.node(path)
    if top is not None and top.children():
        top = next((c for c in top.children() if c.isDisplayFlagSet()), None)
    return (top if hasattr(top, "getPDGNode") else None), path


def work_items(top):
    top.generateStaticWorkItems(block=True)
    pdg_node = top.getPDGNode()
    return sorted(pdg_node.workItems, key=lambda w: w.index) if pdg_node else []


def wedge(wi):
    out = {}
    for k, vals in wi.attribValues().items():
        vals = vals if isinstance(vals, (list, tuple)) else [vals]
        vals = [v if isinstance(v, (int, float, str)) else str(getattr(v, "path", v)) for v in vals]
        out[k] = vals[0] if len(vals) == 1 else vals
    return out


def item_name(index):
    return f"wi{index:03d}"


def batch_folder(node):
    name = parm_str(node, "batch", "")
    root = hou.expandString(OUT + "/batches")
    if not name and os.path.isdir(root):
        found = sorted((d for d in os.listdir(root) if os.path.isfile(f"{root}/{d}/batch.json")), key=lambda d: d[-16:])
        name = found[-1] if found else ""
    if name and os.path.isfile(f"{root}/{name}/batch.json"):
        return f"{root}/{name}", []
    return None, [("B003", {"name": f" named '{name}'" if parm_str(node, "batch", "") else ""})]


def batch_prefix(node):
    name = parm_str(node, "batch_name", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]*", name):
        return None, [("B009", {"name": name})]
    return name, []


def remote_batch(node, folder):
    return f"{remote_root(node)}/batches/{hou.expandString('$HIPNAME')}/{os.path.basename(folder)}"


def on_batch_export():
    node = hou.pwd()
    if hou.hipFile.isNewFile():
        report("batch", [("E003", {})])
        return
    top, path = top_node(node)
    if top is None:
        report("batch", [("B001", {"path": path})])
        return
    lo, hi = parm_int(node, "batch_start", 0), parm_int(node, "batch_end", 1 << 30)
    items = [w for w in work_items(top) if lo <= w.index <= hi]
    if not items:
        report("batch", [("B002", {"start": lo, "end": hi, "path": top.path()})])
        return
    prefix, recs = batch_prefix(node)
    if recs:
        report("batch", recs)
        return
    stamp = time.strftime("%Y%m%d_%H%M%SZ", time.gmtime())
    stamp = f"{prefix}_{stamp}" if prefix else stamp
    folder = hou.expandString(f"{OUT}/batches/{stamp}")
    f, git = frequency(node), git_info()
    batch = {"created_utc": stamp, "hip": hou.hipFile.path(), "top_node": top.path(), "range": [lo, hi],
             "frequency": f, "items": {}}
    batch.update(git)
    say("batch", f"batch {stamp}: {plural(len(items), 'work item')} ({items[0].index} to {items[-1].index}) "
                 f"from {top.path()}")
    before = top.getSelectedWorkItem()
    try:
        for n, wi in enumerate(items, 1):
            t1, name = time.time(), item_name(wi.index)
            top.setSelectedWorkItem(wi.id)
            try:
                geo = node.inputs()[0].geometry()
                recs = validate(geo, f) if geo else [("B008", {"err": "no geometry"})]
            except hou.Error as e:
                geo, recs = None, [("B008", {"err": e.instanceMessage()})]
            entry = {"index": wi.index, "id": wi.id, "name": wi.name}
            if not has_errors(recs):
                export_run(geo, f, f"{folder}/{name}", recs, dict(git, work_item=entry, wedge=wedge(wi)))
            entry["status"] = "failed" if has_errors(recs) else "exported"
            entry["codes"] = [r[0] for r in recs if r[0][0] != "N"]
            batch["items"][name] = entry
            codes = f", {' '.join(entry['codes'])}" if entry["codes"] else ""
            say("batch", f"  [{n}/{len(items)}] {name}: {entry['status']}, "
                         f"{plural(geo.intrinsicValue('primitivecount') if geo else 0, 'prim')}{codes} ({time.time() - t1:.1f} s)")
            for r in recs:
                if r[0][0] not in "WN":
                    say("batch", f"    {fmt(r)}")
    finally:
        top.setSelectedWorkItem(before)
        os.makedirs(folder, exist_ok=True)
        write(folder + "/batch.json", json.dumps(batch, indent=2))
    failed = sum(1 for e in batch["items"].values() if e["status"] == "failed")
    recs = [("N009", {"name": stamp, "ok": len(items) - failed, "failed": failed, "path": folder})]
    if node.parm("batch"):
        node.parm("batch").set(stamp)
        say("batch", f"parm 'batch' set to {stamp}")
    else:
        recs.append(("W009", {}))
    report("batch", recs)


def on_batch_solve():
    node = hou.pwd()
    folder, recs = batch_folder(node)
    if not folder:
        report("batch", recs)
        return
    name, s = os.path.basename(folder), settings(node)
    with open(folder + "/batch.json") as fh:
        items = json.load(fh)["items"]
    queue = []
    for item, entry in sorted(items.items(), key=lambda kv: kv[1]["index"]):
        if entry["status"] != "exported":
            continue
        scene = glob.glob(f"{folder}/{item}/*_scene.xml")[0]
        bad = stale(scene, s) or ray_limit(scene, s)
        for r in bad:
            say("batch", f"  {item}: {fmt(r)}")
        if not bad:
            write(scene.replace("_scene.xml", "_settings.json"), json.dumps(s, indent=2))
            queue.append(item)
    if not queue:
        report("batch", [("B007", {"name": name})])
        return
    write(folder + "/queue.json", json.dumps(queue))
    script = hou.expandString(OUT + "/sionna_run.py")
    if not os.path.isfile(script):
        report("batch", [("S002", {"path": script})])
        return
    shutil.copy2(script, folder + "/sionna_run.py")
    exported = sum(1 for e in items.values() if e["status"] == "exported")
    say("batch", f"batch {name}: {plural(len(queue), 'work item')} queued, {exported} of {len(items)} exported")
    host, seconds = target(node), timeout(node)
    try:
        if host == "local":
            recs = start_local(node, folder, name, len(queue))
        else:
            recs = start_remote(node, folder, name, len(queue), seconds)
    except subprocess.TimeoutExpired:
        recs = [("S004", {"seconds": seconds})]
    except FileNotFoundError as e:
        recs = [("S009", {"path": e.filename})]
    started = any(r[0] == "N010" for r in recs)
    if started or any(r[0] == "B004" for r in recs):
        watch(folder, name, host, remote_batch(node, folder) if host != "local" else None, started)
    report("batch", recs)


def watchers():
    if not hasattr(hou.session, "sionna_watchers"):
        hou.session.sionna_watchers = {}
    return hou.session.sionna_watchers


def watch(folder, name, host, rdir, restart):
    key = f"{host}:{name}"
    old = watchers().get(key)
    if old and old[0].is_alive():
        if not restart:
            say("batch", f"already watching batch {name} on {host}")
            return
        old[1].set()
    stop = threading.Event()
    if rdir:
        env = clean_env()
        cmd = ["ssh", *SSH_OPTS, host, f"cd {shlex.quote(rdir)} 2>/dev/null || exit 0; cat status.json 2>/dev/null; "
               "echo; echo ---; [ -f batch.pid ] && kill -0 \"$(cat batch.pid)\" 2>/dev/null && echo running; true"]

        def poll():
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
            if r.returncode:
                raise OSError(tail(r.stderr, 200) or f"ssh exit code {r.returncode}")
            status, _, running = r.stdout.partition("---\n")
            return (json.loads(status) if status.strip() else None), running.strip() == "running"
    else:
        def poll():
            pid = read_pid(folder + "/batch.pid")
            return read_status(folder), bool(pid) and alive(pid)

    def loop():
        t0, seen, misses = time.time(), None, 0
        while True:
            try:
                status, running = poll()
                misses = 0
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                misses += 1
                if misses == 4:
                    say("watch", f"batch {name} on {host}: stopped watching after 4 failed checks: {e}")
                    return
                if stop.wait(WATCH_SECONDS):
                    return
                continue
            status = status or {}
            done, failed = status.get("done", []), status.get("failed", {})
            total = status.get("total", 0)
            finished = len(done) + len(status.get("skipped", [])) + len(failed)
            if seen is None:
                seen = set(done) | set(failed)
                if finished:
                    say("watch", f"batch {name} on {host}: {finished} of {total} finished so far")
            for item, err in sorted(failed.items()):
                if item not in seen:
                    seen.add(item)
                    say("watch", f"batch {name} on {host}: {item} failed: {err}")
            new = [item for item in done if item not in seen]
            seen.update(new)
            if new:
                say("watch", f"batch {name} on {host}: {', '.join(new)} solved, {finished} of {total} finished")
            if status.get("finished"):
                say("watch", f"batch {name} on {host}: finished, {len(done)} solved, {len(status.get('skipped', []))} "
                             f"skipped, {len(failed)} failed ({(time.time() - t0) / 60:.1f} min), press batch fetch")
                return
            if not running:
                say("watch", f"batch {name} on {host}: stopped, process not running, see batch status")
                return
            if stop.wait(WATCH_SECONDS):
                return

    t = threading.Thread(target=loop, name=f"sionna watch {key}", daemon=True)
    watchers()[key] = (t, stop)
    t.start()
    say("batch", f"watching batch {name} on {host} every {WATCH_SECONDS} s, a line follows each finished work item")


def alive(pid):
    if os.name == "nt":
        return False
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid(path):
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return 0


def read_status(folder):
    if not os.path.isfile(folder + "/status.json"):
        return None
    with open(folder + "/status.json") as fh:
        return json.load(fh)


def start_local(node, folder, name, count):
    pid = read_pid(folder + "/batch.pid")
    if pid and alive(pid) and not (read_status(folder) or {}).get("finished"):
        return [("B004", {"name": name, "target": "local", "pid": pid})]
    exe = local_python(node)
    if not os.path.isfile(exe):
        return [("S001", {"path": exe})]
    if os.path.isfile(folder + "/status.json"):
        os.remove(folder + "/status.json")
    with open(folder + "/batch.log", "a") as log:
        p = subprocess.Popen(
            [exe, "-u", folder + "/sionna_run.py", "batch", folder, device(node)], env=clean_env(), cwd=folder,
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
        )
    write(folder + "/batch.pid", str(p.pid))
    return [("N010", {"name": name, "target": "local", "pid": p.pid, "count": count})]


def start_remote(node, folder, name, count, seconds):
    host = target(node)
    say("batch", f"target {host}: checking")
    recs, info = preflight(node, use_gpu(node))
    if has_errors(recs):
        return recs
    say("batch", f"target {host}: gpu {gpu_text(info)}, runs on the {device(node)}")
    rdir, py = remote_batch(node, folder), shlex.quote(remote_root(node) + "/venv/bin/python3")
    q = shlex.quote(rdir)
    r = ssh(host, f"mkdir -p {q} && cd {q} && "
                  "if [ -f batch.pid ] && kill -0 \"$(cat batch.pid)\" 2>/dev/null "
                  "&& ! grep -q '\"finished\": true' status.json 2>/dev/null; then cat batch.pid; exit 5; fi")
    if r.returncode == 5:
        return recs + [("B004", {"name": name, "target": host, "pid": r.stdout.strip()})]
    if r.returncode:
        return recs + [("T004", {"target": host, "err": tail(r.stderr, 300)})]
    say("batch", f"send to {host}:{rdir}")
    c, out = transfer("batch", folder + "/", f"{host}:{rdir}/", seconds,
                      "--exclude", "batch.pid", "--exclude", "batch.log", "--exclude", "status.json")
    if c:
        return recs + [("T004", {"target": host, "err": tail("\n".join(out), 300)})]
    r = ssh(host, f"rm -f {q}/status.json; nohup {py} -u {q}/sionna_run.py batch {q} {device(node)} >> {q}/batch.log 2>&1 < /dev/null & "
                  f"echo $! > {q}/batch.pid; cat {q}/batch.pid")
    if r.returncode:
        return recs + [("T001", {"target": host, "err": tail(r.stderr, 300)})]
    return recs + [("N010", {"name": name, "target": host, "pid": r.stdout.strip(), "count": count})]


def batch_counts(folder):
    with open(folder + "/batch.json") as fh:
        items = sorted(k for k, e in json.load(fh)["items"].items() if e["status"] == "exported")
    solved = [i for i in items if os.path.isfile(f"{folder}/{i}/done.json")]
    failed = [i for i in items if os.path.isfile(f"{folder}/{i}/failed.json")]
    return items, solved, failed


def show_status(name, host, status, running, log):
    running = running and not (status or {}).get("finished")
    if not status:
        say("batch", f"batch {name} on {host}: " + ("starting" if running else "not started"))
    else:
        total, done, failed = status["total"], len(status["done"]) + len(status["skipped"]), status["failed"]
        state = "running" if running else "finished" if status["finished"] else "stopped, process not running"
        current = f", now {status['current']}" if running and status.get("current") else ""
        say("batch", f"batch {name} on {host}: {state}, {done} of {total} done "
                     f"({len(status['skipped'])} skipped as already solved), {len(failed)} failed{current}")
        solved = len(status["done"])
        if solved:
            avg = status["solve_seconds"] / solved
            left = (total - done - len(failed)) * avg
            eta = f", about {left / 60:.0f} min left" if running else ""
            say("batch", f"  {avg:.2f} s per work item{eta}")
        for item, err in sorted(failed.items()):
            say("batch", f"  failed {item}: {err}")
    for line in log:
        say("batch", f"  log | {line}")


def on_batch_status():
    node = hou.pwd()
    folder, recs = batch_folder(node)
    if not folder:
        report("batch", recs)
        return
    name, host = os.path.basename(folder), target(node)
    try:
        if host == "local":
            status = read_status(folder)
            pid = read_pid(folder + "/batch.pid")
            log = []
            if os.path.isfile(folder + "/batch.log"):
                with open(folder + "/batch.log") as fh:
                    log = fh.read().splitlines()[-5:]
            show_status(name, host, status, bool(pid) and alive(pid), log)
        else:
            q = shlex.quote(remote_batch(node, folder))
            r = ssh(host, f"cd {q} 2>/dev/null || exit 0; cat status.json 2>/dev/null; echo; echo ---; "
                          "[ -f batch.pid ] && kill -0 \"$(cat batch.pid)\" 2>/dev/null && echo running; echo ---; "
                          "tail -n 5 batch.log 2>/dev/null")
            if r.returncode:
                recs.append(("T001", {"target": host, "err": tail(r.stderr, 300)}))
            else:
                status, running, log = (r.stdout.split("---\n") + ["", ""])[:3]
                status = json.loads(status) if status.strip() else None
                show_status(name, host, status, running.strip() == "running", log.splitlines())
    except subprocess.TimeoutExpired:
        recs.append(("T001", {"target": host, "err": "timeout"}))
    report("batch", recs)


def stale_bgeo(item):
    src = glob.glob(item + "/*.npz")
    dst = [f"{item}/{k}.bgeo.sc" for k in KINDS if os.path.isfile(f"{item}/{k}.bgeo.sc")]
    if not src:
        for path in dst:
            os.remove(path)
        return False
    return not dst or max(map(os.path.getmtime, src)) > min(map(os.path.getmtime, dst))


def on_batch_fetch():
    node = hou.pwd()
    folder, recs = batch_folder(node)
    if not folder:
        report("batch", recs)
        return
    name, host = os.path.basename(folder), target(node)
    try:
        if host != "local":
            rdir = remote_batch(node, folder)
            say("batch", f"receive from {host}:{rdir}")
            c, out = transfer("batch", f"{host}:{rdir}/", folder + "/", timeout(node),
                              "--delete", "--exclude", "batch.pid")
            if c:
                recs.append(("T004", {"target": host, "err": tail("\n".join(out), 300)}))
    except subprocess.TimeoutExpired:
        recs.append(("S004", {"seconds": timeout(node)}))
    items, solved, failed = batch_counts(folder)
    todo = [i for i in items if stale_bgeo(f"{folder}/{i}")]
    say("batch", f"convert {plural(len(todo), 'work item')} to bgeo, the others are up to date or have no result")
    t0, bad = time.time(), 0
    for n, item in enumerate(todo, 1):
        t1 = time.time()
        try:
            to_bgeo(f"{folder}/{item}")
            say("batch", f"  [{n}/{len(todo)}] {item} ({time.time() - t1:.1f} s)")
        except (ValueError, KeyError, OSError, zipfile.BadZipFile):
            bad += 1
            say("batch", f"  [{n}/{len(todo)}] {item}: {fmt(('I002', {}))}")
    if todo:
        say("batch", f"converted in {time.time() - t0:.1f} s")
    if bad:
        recs.append(("I002", {}))
    for i, kind in enumerate(("scene",) + KINDS):
        path = f'{OUT}/batches/`chs("../{node.name()}/batch")`/wi`padzero(3, @pdg_index)`/{kind}.bgeo.sc'
        load_result(node, f"sionna_batch_{kind}", path, (6, -i), recs, missingframe="empty")
    if not node.parm("batch"):
        recs.append(("W009", {}))
    recs.append(("N011", {"name": name, "done": len(solved), "failed": len(failed),
                          "missing": len(items) - len(solved) - len(failed)}))
    report("batch", recs)


# --- presets ---

def preset_menu(kind):
    return [x for name in PRESETS[kind] for x in (name, name.replace("_", " "))]


def on_preset(kind):
    node = hou.pwd()
    presets = PRESETS[kind]
    name = parm_str(node, kind, "")
    if name not in presets:
        report("preset", [("P001", {"kind": kind, "name": name, "names": ", ".join(presets)})])
        return
    missing, same = [], 0
    for key, value in presets[name].items():
        parm = node.parm(key)
        if parm is None:
            missing.append(key)
            continue
        old = parm.eval()
        if old == value:
            same += 1
            continue
        parm.set(value)
        say("preset", f"  {key:<20} {old} -> {value}")
    say("preset", f"{kind} preset {name} applied, {same} parms already had the preset value")
    report("preset", [("W012", {"kind": kind, "name": name, "parms": ", ".join(missing)})] if missing else [])


# --- clear ---

CLEAN = r"""
import json, os, re, shutil


def alive(pid):
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def running(path):
    try:
        with open(path + "/batch.pid") as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return False
    try:
        with open(path + "/status.json") as fh:
            if json.load(fh).get("finished"):
                return False
    except (OSError, ValueError):
        pass
    return alive(pid)


def owner(path):
    try:
        with open(path + "/batch.json") as fh:
            return os.path.splitext(os.path.basename(json.load(fh)["hip"]))[0]
    except (OSError, ValueError, KeyError):
        return next((f[:-10] for f in os.listdir(path) if f.endswith("_meta.json")), "")


def clean(spec, delete=None):
    out = []
    for root, pattern in spec["roots"]:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if not re.fullmatch(pattern, name) or os.path.islink(path) or not os.path.isdir(path):
                continue
            if owner(path) != spec["hip"]:
                continue
            d = {"path": path, "bytes": sum(os.lstat(os.path.join(a, f)).st_size for a, _, fs in os.walk(path) for f in fs),
                 "running": running(path)}
            if delete and path in delete and not d["running"]:
                shutil.rmtree(path)
                d["deleted"] = True
            out.append(d)
    return out
"""


def run_clean(host, spec, delete=None):
    if host == "local":
        g = {}
        exec(CLEAN, g)
        return g["clean"](spec, delete), []
    payload = json.dumps({"spec": spec, "delete": delete})
    script = CLEAN + f"\nargs = json.loads({payload!r})\nprint(json.dumps(clean(args['spec'], args['delete'])))\n"
    try:
        r = ssh(host, f"python3 -c {shlex.quote(script)}", 300)
    except subprocess.TimeoutExpired:
        return None, [("T001", {"target": host, "err": "timeout"})]
    if r.returncode == 255:
        return None, [("T001", {"target": host, "err": tail(r.stderr, 300)})]
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]), []
    except (IndexError, ValueError):
        return None, [("C001", {"target": host, "err": tail(r.stderr, 300) or f"exit code {r.returncode}"})]


def on_clear(scope):
    node = hou.pwd()
    host, hip = target(node), hou.expandString("$HIPNAME")
    prefix, recs = batch_prefix(node)
    if recs:
        report("clear", recs)
        return
    session = (re.escape(prefix) + "_" if prefix else "") + STAMP
    if host == "local":
        runs, batches = hou.expandString(OUT + "/data"), hou.expandString(OUT + "/batches")
    else:
        root = remote_root(node)
        runs, batches = f"{root}/runs/{hip}", f"{root}/batches/{hip}"
    if scope == "all":
        roots, what = [[runs, STAMP], [batches, r"(?:[A-Za-z0-9_-]+_)?" + STAMP]], f"runs or batches of {hip}"
    else:
        roots, what = [[batches, session]], f"batches of {hip} in session '{prefix}'" if prefix else \
            f"batches of {hip} without a session name"
    spec = {"hip": hip, "roots": roots}
    say("clear", f"looking for {what} on {host}")
    found, recs = run_clean(host, spec)
    if recs:
        report("clear", recs)
        return
    if not found:
        report("clear", [("N013", {"target": host, "what": what})])
        return
    free = [d for d in found if not d["running"]]
    busy = [os.path.basename(d["path"]) for d in found if d["running"]]
    for d in found:
        say("clear", f"  {d['path']}  {size(d['bytes'])}" + ("  running, kept" if d["running"] else ""))
    if busy:
        recs.append(("W014", {"target": host, "names": ", ".join(busy)}))
    if not free:
        report("clear", recs)
        return
    total = size(sum(d["bytes"] for d in free))
    names = [os.path.basename(d["path"]) for d in free]
    shown = "\n".join(names[:15]) + (f"\n... and {len(names) - 15} more" if len(names) > 15 else "")
    choice = hou.ui.displayMessage(
        f"Delete {plural(len(free), 'folder')} ({total}) on '{host}'?\n\n{shown}\n\nThis cannot be undone.",
        buttons=("Delete", "Cancel"), default_choice=1, close_choice=1, severity=hou.severityType.Warning,
        title="sionna clear")
    if choice != 0:
        say("clear", "cancelled, nothing deleted")
        report("clear", recs)
        return
    done, more = run_clean(host, spec, [d["path"] for d in free])
    if more:
        report("clear", recs + more)
        return
    gone = [d for d in done if d.get("deleted")]
    report("clear", recs + [("N012", {"folders": plural(len(gone), "folder"), "size": size(sum(d["bytes"] for d in gone)), "target": host})])
