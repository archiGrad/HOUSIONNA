import hou
import os
import subprocess
import threading
import time
import numpy as np
from xml.sax.saxutils import escape

SCALE = 1000
PRINT_DIR = os.path.expanduser("~/prints")
PAPER = {"A4": "A4", "A5": "A5", "A6": "Custom.105x148mm"}


def _attrib(geo, name, levels):
    for level in levels:
        attrib = getattr(geo, "find%sAttrib" % level.capitalize())(name)
        if attrib is not None:
            values = getattr(geo, "%sFloatAttribValues" % level)(name)
            return level, np.asarray(values).reshape(-1, attrib.size())
    return None, None


def _index(level, prim):
    if level == "prim":
        return prim.number()
    vtx = prim.vertex(0)
    return vtx.point().number() if level == "point" else vtx.linearNumber()


def _vals(level, data, prim):
    if level == "prim":
        return np.repeat(data[[prim.number()]], prim.numVertices(), 0)
    return data[[v.point().number() if level == "point" else v.linearNumber() for v in prim.vertices()]]


def _rgb(c):
    return "rgb(%d,%d,%d)" % tuple((np.asarray(c)[:3] * 255).astype(int))


def _tri_fill(pts, cols, al, defs):
    E = (pts[1:] - pts[0]).T
    if abs(np.linalg.det(E)) < 1e-9:
        return None
    C = cols if al is None else np.column_stack([cols, al])
    J = (C[1:] - C[0]).T @ np.linalg.inv(E)
    _, S, Vt = np.linalg.svd(J)
    s = pts @ Vt[0]
    lo, span = s.min(), np.ptp(s)
    if S[0] < 1e-9 or span < 1e-9:
        return "fill='%s'%s" % (_rgb(cols.mean(0)), " fill-opacity='%s'" % al.mean() if al is not None else "")
    gid = "g%d" % len(defs)
    stops = "".join("<stop offset='%s' stop-color='%s'%s/>" % ((s[i] - lo) / span, _rgb(cols[i]), " stop-opacity='%s'" % al[i] if al is not None else "") for i in np.argsort(s))
    (x1, y1), (x2, y2) = Vt[0] * lo, Vt[0] * (lo + span)
    defs.append("\t\t<linearGradient id='%s' gradientUnits='userSpaceOnUse' x1='%s' y1='%s' x2='%s' y2='%s'>%s</linearGradient>" % (gid, x1, y1, x2, y2, stops))
    return "fill='url(#%s)'" % gid


def export_svg():
    node = hou.pwd()
    print("Current node:", node.path())

    geo = node.geometry()
    prims = [p for p in geo.prims() if p.numVertices() > 1]
    print("Found %d primitives" % len(prims))
    if not prims:
        raise hou.Error("%s: no primitives to export" % node.path())

    P = np.asarray(geo.pointFloatAttribValues("P")).reshape(-1, 3)[:, :2] * (SCALE, -SCALE)
    cd_level, cd = _attrib(geo, "Cd", ("vertex", "point", "prim"))
    if cd_level:
        cd = np.clip(cd[:, :3], 0, 1)
    w_level, w = _attrib(geo, "width", ("point", "prim"))
    a_level, a = _attrib(geo, "Alpha", ("vertex", "point", "prim"))
    if a_level:
        a = np.clip(a[:, 0], 0, 1)
    label_attrib = geo.findPrimAttrib("label")
    labels = geo.primStringAttribValues("label") if label_attrib and label_attrib.dataType() == hou.attribData.String else None
    print("Attributes found - Color: %s, Width: %s, Alpha: %s, Label: %s" % (cd_level, w_level, a_level, labels is not None))

    widths = [w[_index(w_level, p), 0] * SCALE if w_level else 1.0 for p in prims]
    pad = max(widths) / 2 or 0.5
    lo = P.min(0) - pad
    size = P.max(0) + pad - lo
    P -= lo
    print("SVG dimensions: %gx%g" % tuple(size))

    lines = ["<svg xmlns='http://www.w3.org/2000/svg' width='%smm' height='%smm' viewBox='0 0 %s %s'>" % (size[0], size[1], size[0], size[1])]
    defs = []

    for prim, sw in zip(prims, widths):
        pts = P[[p.number() for p in prim.points()]]
        closed = isinstance(prim, hou.Face) and prim.isClosed()
        if closed and len(pts) > 2:
            cols = _vals(cd_level, cd, prim) if cd_level else np.zeros((len(pts), 3))
            al = _vals(a_level, a, prim) if a_level else None
            for i in range(1, len(pts) - 1):
                t = [0, i, i + 1]
                fill = _tri_fill(pts[t], cols[t], al[t] if al is not None else None, defs)
                if fill:
                    lines.append("\t<polygon points='%s' %s/>" % (" ".join(map(str, pts[t].ravel().tolist())), fill))
        else:
            data = " ".join(map(str, pts.ravel().tolist()))
            stroke = _rgb(cd[_index(cd_level, prim)]) if cd_level else "black"
            opacity = " stroke-opacity='%s'" % a[_index(a_level, prim)] if a_level else ""
            tag = "polygon" if closed else "polyline"
            lines.append("\t<%s points='%s' fill='none' stroke='%s' stroke-width='%s'%s/>" % (tag, data, stroke, sw, opacity))

        if labels and labels[prim.number()]:
            x, y = pts[0]
            lines.append("\t<text x='%s' y='%s' font-size='12' fill='black'>%s</text>" % (x, y, escape(labels[prim.number()])))

    if defs:
        lines[1:1] = ["\t<defs>"] + defs + ["\t</defs>"]
    lines.append("</svg>")
    print("Generated %d SVG lines" % len(lines))

    output_path = hou.expandString(node.evalParm("svg_out"))
    print("Output path: %s" % output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("SVG file written successfully")


def _run(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise hou.Error(r.stderr.strip() or "%s failed" % cmd[0])
    return r.stdout


def _watch(printer, job):
    last = None
    while True:
        lines = subprocess.run(["lpstat", "-l", "-o", printer], capture_output=True, text=True).stdout.splitlines()
        i = next((i for i, l in enumerate(lines) if l.split(" ", 1)[0] == job), None)
        if i is None:
            print("[%s] left queue" % job)
            return
        status = next((l.split(":", 1)[1].strip() for l in lines[i + 1:] if l.strip().startswith("Status:")), "")
        if status != last:
            print("[%s] %s" % (job, status))
            last = status
        time.sleep(2)


def print_svg():
    node = hou.pwd()
    svg = hou.expandString(node.evalParm("svg_out"))
    if not os.path.isfile(svg):
        raise hou.Error("%s not found, export first" % svg)
    printer = node.parm("printer").evalAsString()
    paper = node.parm("paper").evalAsString()

    os.makedirs(PRINT_DIR, exist_ok=True)
    pdf = os.path.join(PRINT_DIR, os.path.splitext(os.path.basename(svg))[0] + ".pdf")
    _run("rsvg-convert", "-f", "pdf", "-o", pdf, svg)
    print("PDF written: %s" % pdf)

    job = _run("lp", "-d", printer, "-o", "PageSize=" + PAPER[paper], "-o", "fit-to-page", pdf).split()[3]
    print("Sent to %s (%s), job %s" % (printer, paper, job))
    threading.Thread(target=_watch, args=(printer, job), daemon=True).start()
