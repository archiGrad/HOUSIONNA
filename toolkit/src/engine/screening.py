"""Sensor nodes whose paths to the gateway Sionna RT discards: a surface within 1 cm in the gateway's direction.

Sionna RT drops every path with a segment shorter than 1 cm. A sensor node mounted just below a leaf therefore loses
the direct path and every path through that leaf, and its gain drops by tens of dB although the leaf itself attenuates
by well under 1 dB. This casts the straight line from each sensor node to every gateway through the exported scene and
reports the shortest distance to the first surface it meets; nodes below the limit are excluded from the use case.
"""
from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

MIN_SEGMENT_M = 0.01
ROOT = Path(__file__).resolve().parents[2]
SEARCH = (ROOT.parent / "houdini_files" / "sionna" / "batches", ROOT / "outputs" / "reruns")


def run_folder(run_id: str) -> Path:
    """The exported work item of a run id <batch>.<item>, in the Houdini batches or the local reruns."""
    batch, item = run_id.split(".", 1)
    for base in SEARCH:
        folder = base / batch / item
        if folder.is_dir():
            return folder
    raise FileNotFoundError(f"No exported scene for {run_id} in {', '.join(str(base) for base in SEARCH)}")


def first_hit_m(folder: Path, gateway_prefix: str, sensor_prefix: str) -> dict[str, float]:
    """Per sensor node: the distance from it to the first surface on the straight line to a gateway (inf if none),
    the shortest over all gateways."""
    import mitsuba as mi
    if mi.variant() is None:
        mi.set_variant("scalar_rgb")
    scene_xml = next(folder.glob("*_scene.xml"))
    shapes = {"type": "scene"}
    for shape in ET.parse(scene_xml).getroot().iter("shape"):
        filename = next(child.get("value") for child in shape if child.get("name") == "filename")
        shapes[shape.get("id")] = {"type": "ply", "filename": str(folder / filename)}
    scene = mi.load_dict(shapes)
    devices = json.loads(next(folder.glob("*_txrx.json")).read_text(encoding="utf-8"))
    everyone = devices["tx"] + devices["rx"]
    gateways = [np.array(d["position"], dtype=float) for d in everyone if d["name"].startswith(gateway_prefix)]
    if not gateways:
        raise ValueError(f"no gateway named {gateway_prefix}* in {folder}")
    out = {}
    for device in everyone:
        if not device["name"].startswith(sensor_prefix):
            continue
        origin = np.array(device["position"], dtype=float)
        distances = []
        for gateway in gateways:
            direction = (gateway - origin) / np.linalg.norm(gateway - origin)
            hit = scene.ray_intersect(mi.Ray3f(mi.Point3f(*map(float, origin)), mi.Vector3f(*map(float, direction))))
            distances.append(float(np.ravel(hit.t)[0]) if bool(np.ravel(hit.is_valid())[0]) else float("inf"))
        out[device["name"]] = min(distances)
    return out


def too_close(run_id: str, gateway_prefix: str = "ap_", sensor_prefix: str = "plant_sensor_") -> dict[str, float]:
    """The sensor nodes of a run with a surface closer than MIN_SEGMENT_M towards the gateway, with that distance."""
    hits = first_hit_m(run_folder(run_id), gateway_prefix, sensor_prefix)
    return {name: distance for name, distance in hits.items() if distance < MIN_SEGMENT_M}
