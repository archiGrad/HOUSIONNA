import hou
import numpy as np
from xml.sax.saxutils import escape

SCALE = 1000


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
        cd = (np.clip(cd[:, :3], 0, 1) * 255).astype(int)
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

    for prim, sw in zip(prims, widths):
        pts = P[[p.number() for p in prim.points()]]
        data = " ".join(map(str, pts.ravel().tolist()))
        stroke = "rgb(%d,%d,%d)" % tuple(cd[_index(cd_level, prim)]) if cd_level else "black"
        opacity = " stroke-opacity='%s'" % a[_index(a_level, prim)] if a_level else ""
        tag = "polygon" if isinstance(prim, hou.Face) and prim.isClosed() else "polyline"
        lines.append("\t<%s points='%s' fill='none' stroke='%s' stroke-width='%s'%s/>" % (tag, data, stroke, sw, opacity))

        if labels and labels[prim.number()]:
            x, y = pts[0]
            lines.append("\t<text x='%s' y='%s' font-size='12' fill='black'>%s</text>" % (x, y, escape(labels[prim.number()])))

    lines.append("</svg>")
    print("Generated %d SVG lines" % len(lines))

    output_path = hou.expandString(node.evalParm("svg_out"))
    print("Output path: %s" % output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("SVG file written successfully")
