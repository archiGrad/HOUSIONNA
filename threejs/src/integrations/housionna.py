"""Import HOUSIONNA run folders into the local digital-twin scene format.

This module is the only code that reads HOUSIONNA's files. The viewer consumes
the normalized payload written under ``outputs/integrations/housionna``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Callable
from collections import OrderedDict
import threading

import numpy as np
import yaml


LIGHT_SPEED_M_S = 299_792_458.0
MISSING_VALUE = -999.0
ADAPTER_VERSION = "2.2.0"
DEFAULT_PATH_ENDPOINT_TOLERANCE_M = 1e-3
INTERACTION_BITS = (
    (1, "specular_reflection"),
    (2, "diffuse_reflection"),
    (4, "refraction"),
    (8, "diffraction"),
)
_RUN_VALIDATION_CACHE: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
# Discovery of a new 280-item batch validates every work item once (about 0.15 s each). The results and the file
# fingerprints are kept in outputs/integrations/housionna/discovery_cache.json, so a server restart or a page load
# only stats the files. A fingerprint is reused only while every source file keeps its size and mtime; imports
# always hash the files again.
_DISCOVERY_CACHE_LOCK = threading.Lock()
_DISCOVERY_CACHE: dict[str, Any] = {"file": None, "runs": {}}
DISCOVERY_CACHE_SCHEMA = 1
_IMPORT_SUMMARY_CACHE = OrderedDict()
_IMPORT_SUMMARY_LOCK = threading.Lock()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read {path.name} as UTF-8 JSON: {error}") from error


def _one_file(folder: Path, suffix: str, *, required: bool = True) -> Path | None:
    matches = sorted(path for path in folder.iterdir() if path.is_file() and path.name.endswith(suffix))
    if len(matches) > 1:
        raise ValueError(f"Expected one *{suffix} file in {folder}, found {len(matches)}")
    if not matches:
        if required:
            raise ValueError(f"Required run artifact *{suffix} is missing from {folder}")
        return None
    return matches[0]


def _artifact(folder: Path, stem: str, *, required: bool = True) -> Path | None:
    """Find *<stem>.json (original exporter) or *<stem>.npz (multi-sim exporter, Oct 2026)."""
    found = [path for suffix in (".json", ".npz")
             if (path := _one_file(folder, stem + suffix, required=False)) is not None]
    if len(found) > 1:
        raise ValueError(f"{folder.name} has both *{stem}.json and *{stem}.npz; expected one result format")
    if not found and required:
        raise ValueError(f"Required run artifact *{stem}.json or *{stem}.npz is missing from {folder}")
    return found[0] if found else None


def _npz_info(data: dict[str, Any]) -> dict[str, Any]:
    info = json.loads(str(data["info"])) if "info" in data else {}
    return info if isinstance(info, dict) else {}


def _result_from_npz(path: Path) -> dict[str, Any]:
    """Rebuild the JSON result layout (paths as TX, interaction points, RX) from the NumPy export."""
    with path.open("rb") as handle, np.load(handle, allow_pickle=False) as archive:
        # NpzFile decompresses an array on every lookup, so read each array exactly once.
        data = {key: archive[key] for key in archive.files}
        info = _npz_info(data)
        tx_names = [str(name) for name in data["tx"]]
        rx_names = [str(name) for name in data["rx"]]
        tx_positions = data["tx_position"].astype(float)
        rx_positions = data["rx_position"].astype(float)
        object_names = [str(name) for name in data["object_names"]]
        interactions, objects = data["path_interactions"], data["path_objects"]
        primitives, vertices = data["path_primitives"], data["path_vertices"].astype(float)
        paths = []
        for k, (t, r) in enumerate(zip(data["path_tx"].tolist(), data["path_rx"].tolist())):
            used = interactions[k] != 0  # unused depth slots are 0 / object -1
            object_ids = objects[k][used].tolist()
            if any(index < 0 or index >= len(object_names) for index in object_ids):
                raise ValueError(f"{path.name} path {k} refers to an object outside object_names")
            paths.append({
                "tx": tx_names[t], "rx": rx_names[r],
                "vertices": [tx_positions[t].tolist(), *vertices[k][used].tolist(), rx_positions[r].tolist()],
                "interactions": interactions[k][used].tolist(),
                "objects": [object_names[index] for index in object_ids],
                "primitives": primitives[k][used].tolist(),
                **{key: float(data[f"path_{key}"][k]) for key in (
                    "a_re", "a_im", "gain_db", "tau", "theta_t", "phi_t", "theta_r", "phi_r", "doppler")},
            })
        links = []  # link arrays are indexed [rx, tx]
        for r, rx_name in enumerate(rx_names):
            for t, tx_name in enumerate(tx_names):
                links.append({
                    "tx": tx_name, "rx": rx_name,
                    "vertices": [tx_positions[t].tolist(), rx_positions[r].tolist()],
                    "num_paths": int(data["link_num_paths"][r, t]),
                    "gain_db_coherent": float(data["link_gain_db_coherent"][r, t]),
                    "gain_db_incoherent": float(data["link_gain_db_incoherent"][r, t]),
                    "delay_spread": float(data["link_delay_spread"][r, t]),
                    "cfr_db": data["link_cfr_db"][r, t].astype(float).tolist(),
                })
        return {"sionna_rt": info.get("sionna_rt"), "variant": info.get("variant"),
                "settings": info.get("settings"), "cfr_frequencies": data["cfr_frequencies"].tolist(),
                "paths": paths, "links": links}


def _radiomap_from_npz(path: Path) -> dict[str, Any]:
    """Split the concatenated NumPy radio maps back into one entry per measurement mesh."""
    with path.open("rb") as handle, np.load(handle, allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
        info = _npz_info(data)
        vertices, faces = data["vertices"].astype(float), data["faces"]
        cell_map, gains = data["cell_map"], data["path_gain_db"].astype(float)
        maps, start = [], 0
        for index, name in enumerate(str(item) for item in data["map_names"]):
            selected = cell_map == index
            map_faces = faces[selected]
            # The exporter appends each mesh's vertices as one contiguous block, in map order.
            if not len(map_faces) or int(map_faces.min()) < start:
                raise ValueError(f"{path.name} map {name!r} has no faces or faces outside its vertex block")
            end = int(map_faces.max())+1
            maps.append({"name": name, "vertices": vertices[start:end].tolist(),
                         "faces": (map_faces-start).tolist(), "path_gain_db": gains[selected].tolist()})
            start = end
        return {"sionna_rt": info.get("sionna_rt"), "settings": info.get("settings"),
                "tx": [str(name) for name in data["tx"]], "maps": maps}


def _read_npz(path: Path, convert: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    # A damaged archive must make this one run invalid, not break discovery of every run.
    try:
        return convert(path)
    except (OSError, EOFError, KeyError, IndexError, ValueError, zipfile.BadZipFile) as error:
        raise ValueError(f"{path.name} is not a readable HOUSIONNA NumPy export ({error})") from error


def _read_result(path: Path) -> Any:
    return _read_npz(path, _result_from_npz) if path.suffix == ".npz" else _read_json(path)


def _read_radiomap(path: Path) -> Any:
    return _read_npz(path, _radiomap_from_npz) if path.suffix == ".npz" else _read_json(path)


def _required_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _nullable_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or math.isclose(result, MISSING_VALUE, abs_tol=1e-9):
        return None
    return result


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must contain three coordinates")
    return [_required_number(component, label) for component in value]


def _safe_run_file(folder: Path, relative_name: str, label: str) -> Path:
    candidate = (folder / relative_name.replace("\\", "/")).resolve()
    try:
        candidate.relative_to(folder.resolve())
    except ValueError as error:
        raise ValueError(f"{label} points outside the run folder: {relative_name}") from error
    if not candidate.is_file():
        raise ValueError(f"{label} is missing: {relative_name}")
    return candidate


def _source_fingerprint(folder: Path) -> tuple[str, dict[str, str]]:
    """Hash the inputs used by the adapter, including every exported PLY mesh."""
    selected: dict[str, Path] = {}
    artifacts = [_one_file(folder, suffix, required=suffix in {"_scene.xml", "_txrx.json", "_settings.json"})
                 for suffix in ("_scene.xml", "_txrx.json", "_settings.json", "_dump.json", "_measure.json")]
    artifacts += [_artifact(folder, "_result"), _artifact(folder, "_radiomap", required=False)]
    for artifact in artifacts:
        if artifact is not None:
            relative = artifact.relative_to(folder).as_posix()
            selected[relative] = _safe_run_file(folder, relative, "Source artifact")
    mesh_root = folder / "meshes"
    if mesh_root.is_dir():
        for mesh in sorted(mesh_root.glob("*.ply")):
            if mesh.is_file():
                relative = mesh.relative_to(folder).as_posix()
                selected[relative] = _safe_run_file(folder, relative, "Source mesh")
    per_file: dict[str, str] = {}
    digest = hashlib.sha256()
    for relative_name, path in sorted(selected.items()):
        file_hash = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                file_hash.update(block)
        value = file_hash.hexdigest()
        per_file[relative_name] = value
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), per_file


PLY_TYPES = {
    "char": "b", "int8": "b", "uchar": "B", "uint8": "B",
    "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
    "int": "i", "int32": "i", "uint": "I", "uint32": "I",
    "float": "f", "float32": "f", "double": "d", "float64": "d",
}
PLY_FORMATS = {"ascii 1.0": None, "binary_little_endian 1.0": "<", "binary_big_endian 1.0": ">"}


def _ply_type(path: Path, name: str) -> str:
    if name not in PLY_TYPES:
        raise ValueError(f"{path.name} uses an unsupported PLY property type {name!r}")
    return PLY_TYPES[name]


def _load_ply(path: Path) -> tuple[list[list[float]], list[list[int]]]:
    """Read the triangular PLY meshes written by the Houdini exporter (ASCII or binary)."""
    with path.open("rb") as handle:
        header: list[str] = []
        while True:
            raw = handle.readline()
            if not raw:
                raise ValueError(f"{path.name} has an incomplete PLY header")
            try:
                line = raw.decode("ascii").strip()
            except UnicodeDecodeError as error:
                raise ValueError(f"{path.name} has a non-ASCII PLY header") from error
            header.append(line)
            if line == "end_header":
                break

        if not header or header[0] != "ply":
            raise ValueError(f"{path.name} is not a PLY file")
        formats = [line.removeprefix("format ") for line in header if line.startswith("format ")]
        if len(formats) != 1 or formats[0] not in PLY_FORMATS:
            raise ValueError(f"{path.name} uses an unsupported PLY format; expected ASCII or binary 1.0")
        endian = PLY_FORMATS[formats[0]]

        vertex_count = face_count = None
        vertex_properties: list[tuple[str, str]] = []  # (type, name)
        face_list: tuple[str, str] | None = None        # (count type, index type)
        face_extra = False
        current_element = None
        for line in header:
            parts = line.split()
            if len(parts) == 3 and parts[0] == "element":
                current_element = parts[1]
                if current_element == "vertex":
                    vertex_count = int(parts[2])
                elif current_element == "face":
                    face_count = int(parts[2])
            elif parts and parts[0] == "property" and current_element == "vertex" and len(parts) == 3:
                vertex_properties.append((parts[1], parts[2]))
            elif parts and parts[0] == "property" and current_element == "face":
                if len(parts) == 5 and parts[1] == "list" and face_list is None:
                    face_list = (parts[2], parts[3])
                else:
                    face_extra = True

        if vertex_count is None or face_count is None:
            raise ValueError(f"{path.name} must declare vertex and face elements")
        names = [name for _, name in vertex_properties]
        if not all(axis in names for axis in ("x", "y", "z")):
            raise ValueError(f"{path.name} must have x, y, and z vertex properties")
        axis_indices = [names.index(axis) for axis in ("x", "y", "z")]

        vertices: list[list[float]] = []
        faces: list[list[int]] = []
        if endian is None:
            def next_tokens() -> list[str]:
                while True:
                    raw_line = handle.readline()
                    if not raw_line:
                        raise ValueError(f"{path.name} ended before all declared geometry was read")
                    text = raw_line.decode("ascii").strip()
                    if text:
                        return text.split()

            for _ in range(vertex_count):
                tokens = next_tokens()
                try:
                    vertices.append([_required_number(tokens[index], f"{path.name} vertex") for index in axis_indices])
                except IndexError as error:
                    raise ValueError(f"{path.name} has a malformed vertex row") from error
            for _ in range(face_count):
                tokens = next_tokens()
                try:
                    count = int(tokens[0])
                    face = [int(index) for index in tokens[1:1 + count]]
                except (IndexError, ValueError) as error:
                    raise ValueError(f"{path.name} has a malformed face row") from error
                faces.append([count, *face])
        else:
            # Binary rows have a fixed layout, so any face property besides the index list cannot be skipped safely.
            if face_list is None or face_extra:
                raise ValueError(f"{path.name} must have exactly one face index list in binary PLY")
            vertex_format = endian + "".join(_ply_type(path, kind) for kind, _ in vertex_properties)
            vertex_size = struct.calcsize(vertex_format)
            data = handle.read(vertex_size * vertex_count)
            if len(data) != vertex_size * vertex_count:
                raise ValueError(f"{path.name} ended before all declared geometry was read")
            for row in struct.iter_unpack(vertex_format, data):
                vertices.append([_required_number(row[index], f"{path.name} vertex") for index in axis_indices])
            count_format = endian + _ply_type(path, face_list[0])
            index_type = _ply_type(path, face_list[1])
            count_size = struct.calcsize(count_format)
            for _ in range(face_count):
                raw_count = handle.read(count_size)
                if len(raw_count) != count_size:
                    raise ValueError(f"{path.name} ended before all declared geometry was read")
                count = struct.unpack(count_format, raw_count)[0]
                index_format = endian + index_type * count
                raw_face = handle.read(struct.calcsize(index_format))
                if len(raw_face) != struct.calcsize(index_format):
                    raise ValueError(f"{path.name} ended before all declared geometry was read")
                faces.append([count, *struct.unpack(index_format, raw_face)])

        checked: list[list[int]] = []
        for count, *face in faces:
            if count != 3 or len(face) != 3:
                raise ValueError(f"{path.name} contains a non-triangle face; HOUSIONNA exports triangles")
            if any(index < 0 or index >= vertex_count for index in face):
                raise ValueError(f"{path.name} contains an out-of-range face index")
            checked.append(face)
    if not vertices or not checked:
        raise ValueError(f"{path.name} contains no renderable triangles")
    return vertices, checked


def _bounds(vertices: list[list[float]]) -> dict[str, float]:
    if not vertices:
        raise ValueError("Cannot compute bounds for an empty mesh")
    return {
        f"{axis}_{side}": (min(point[index] for point in vertices)
                            if side == "min" else max(point[index] for point in vertices))
        for index, axis in enumerate(("x", "y", "z"))
        for side in ("min", "max")
    }


def _union_bounds(bounds: list[dict[str, float]]) -> dict[str, float]:
    return {
        f"{axis}_{side}": (min(item[f"{axis}_{side}"] for item in bounds)
                            if side == "min" else max(item[f"{axis}_{side}"] for item in bounds))
        for axis in ("x", "y", "z")
        for side in ("min", "max")
    }


def _xml_value(element: ET.Element, name: str, default: Any = None) -> Any:
    child = element.find(f"*[@name='{name}']")
    return default if child is None else child.get("value", default)


def _category(object_name: str, itu_type: str) -> str:
    text = f"{object_name} {itu_type}".lower()
    if any(word in text for word in ("ground", "floor")):
        return "floor"
    if "glass" in text or "glazing" in text or "window" in text:
        return "greenhouse_shell"
    if "metal" in text or "steel" in text:
        return "metal_structure"
    return "equipment"


def _scene_from_xml(folder: Path, scene_file: Path, dump_data: dict[str, Any] | None
                    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        root = ET.parse(scene_file).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"Could not parse {scene_file.name}: {error}") from error
    if root.tag != "scene":
        raise ValueError(f"{scene_file.name} must have a <scene> root element")

    materials: dict[str, dict[str, Any]] = {}
    for element in root.findall("bsdf"):
        material_id = element.get("id")
        if not material_id:
            raise ValueError(f"{scene_file.name} contains a material without an id")
        itu_type = str(_xml_value(element, "type", "unknown"))
        record: dict[str, Any] = {
            "name": material_id,
            "itu_type": itu_type,
            "thickness_m": _nullable_number(_xml_value(element, "thickness")),
            "scattering_coefficient": _nullable_number(_xml_value(element, "scattering_coefficient")),
        }
        materials[material_id] = record

    dump_materials: dict[str, dict[str, Any]] = {}
    if isinstance(dump_data, dict):
        for object_row in dump_data.get("objects", []):
            if isinstance(object_row, dict) and object_row.get("material"):
                dump_materials[str(object_row["material"])] = object_row

    objects: list[dict[str, Any]] = []
    for shape in root.findall("shape"):
        if shape.get("type") != "ply":
            continue
        filename = _xml_value(shape, "filename")
        if not filename:
            raise ValueError(f"{scene_file.name} contains a PLY shape without a filename")
        mesh_path = _safe_run_file(folder, str(filename), "Scene mesh")
        object_name = Path(str(filename).replace("\\", "/")).stem
        if not object_name:
            raise ValueError(f"{scene_file.name} contains a shape with an empty mesh name")
        material_ref = shape.find("ref[@name='bsdf']")
        material_id = material_ref.get("id") if material_ref is not None else None
        if material_id not in materials:
            raise ValueError(f"Scene object {object_name!r} refers to missing material {material_id!r}")
        vertices, faces = _load_ply(mesh_path)
        bounds = _bounds(vertices)
        material = materials[material_id]
        dump_row = dump_materials.get(material_id)
        if dump_row:
            eps = _nullable_number(dump_row.get("relative_permittivity"))
            conductivity = _nullable_number(dump_row.get("conductivity"))
            if eps is not None:
                material["relative_permittivity"] = eps
            if conductivity is not None:
                material["conductivity_s_per_m"] = conductivity
        objects.append({
            "id": object_name,
            "name": object_name,
            "category": _category(object_name, str(material["itu_type"])),
            "material_key": material_id,
            "bounds_m": bounds,
            "mesh_format": "indexed_triangles",
            "vertices": vertices,
            "faces": faces,
            "metadata": {
                "source_pipeline": "HOUSIONNA",
                "scene_shape_id": shape.get("id"),
                "mesh_file": str(Path(str(filename).replace("\\", "/"))),
                "material_name": material_id,
                "itu_type": material["itu_type"],
                "thickness_m": material["thickness_m"],
                "scattering_coefficient": material["scattering_coefficient"],
            },
        })
    geometry = {
        "units": "m",
        "up_axis": "z",
        # Free-space runs have no scene objects; import_run then frames the measurement surfaces and devices.
        "bounds_m": _union_bounds([item["bounds_m"] for item in objects]) if objects else None,
        "objects": objects,
    }
    return geometry, materials


def _devices(data: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        raise ValueError("TX/RX JSON must be an object with 'tx' and 'rx' arrays")
    converted: dict[str, list[dict[str, Any]]] = {"tx": [], "rx": []}
    names: set[str] = set()
    for role in ("tx", "rx"):
        rows = data.get(role)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"TX/RX JSON must contain a non-empty '{role}' array")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]:
                raise ValueError(f"Every {role.upper()} must have a non-empty name")
            name = row["name"]
            if name in names:
                raise ValueError(f"TX/RX names must be unique; found {name!r} more than once")
            names.add(name)
            device = {
                "name": name,
                "position_m": _vector(row.get("position"), f"{name}.position"),
                "orientation_rad": _vector(row.get("orientation", [0, 0, 0]), f"{name}.orientation"),
                "velocity_m_s": _vector(row.get("velocity", [0, 0, 0]), f"{name}.velocity"),
            }
            if role == "tx":
                device["power_dbm"] = (
                    _required_number(row["power_dbm"], f"{name}.power_dbm")
                    if row.get("power_dbm") is not None else None
                )
            converted[role].append(device)
    return converted["tx"], converted["rx"]


def _interaction_types(values: list[Any]) -> tuple[list[int], list[str]]:
    ids: list[int] = []
    types: list[str] = []
    for raw in values:
        mask = int(raw)
        ids.append(mask)
        matched = False
        for bit, name in INTERACTION_BITS:
            if mask & bit:
                types.append(name)
                matched = True
        if mask and not matched:
            types.append(f"unknown_interaction_{mask}")
    return ids, types


def _paths_for_tx(result: dict[str, Any], tx_name: str, tx_names: set[str],
                  rx_names: set[str], scene_object_names: set[str]) -> list[dict[str, Any]]:
    rows = result.get("paths")
    if not isinstance(rows, list):
        raise ValueError("Result JSON must contain a 'paths' array")
    output: list[dict[str, Any]] = []
    indices: dict[str, int] = {}
    for source in rows:
        if not isinstance(source, dict):
            raise ValueError("Each result path must be a JSON object")
        source_tx, receiver = source.get("tx"), source.get("rx")
        if source_tx not in tx_names or receiver not in rx_names:
            raise ValueError(f"Path references an unknown TX/RX pair: {source_tx!r}/{receiver!r}")
        if source_tx != tx_name:
            continue
        vertices = source.get("vertices")
        interactions = source.get("interactions", [])
        objects = source.get("objects", [])
        primitives = source.get("primitives", [])
        if not isinstance(vertices, list) or len(vertices) != len(interactions) + 2:
            raise ValueError(f"Path {source_tx}/{receiver} has inconsistent vertices and interactions")
        if len(objects) != len(interactions) or len(primitives) != len(interactions):
            raise ValueError(f"Path {source_tx}/{receiver} has inconsistent object/primitive metadata")
        unknown_objects = sorted({str(name) for name in objects} - scene_object_names)
        if unknown_objects:
            raise ValueError(
                f"Path {source_tx}/{receiver} references unknown scene object(s): {', '.join(unknown_objects)}"
            )
        converted_vertices = [_vector(point, f"path {source_tx}/{receiver} vertex") for point in vertices]
        interaction_ids, interaction_names = _interaction_types(interactions)
        real = _required_number(source.get("a_re"), "path.a_re")
        imag = _required_number(source.get("a_im"), "path.a_im")
        magnitude = math.hypot(real, imag)
        gain_db = _nullable_number(source.get("gain_db"))
        if gain_db is None and magnitude > 0:
            gain_db = 20.0 * math.log10(magnitude)
        tau = _required_number(source.get("tau"), "path.tau")
        if tau < 0:
            raise ValueError("Path delays must be non-negative")
        path_index = indices.get(str(receiver), 0)
        indices[str(receiver)] = path_index + 1
        output.append({
            "receiver": receiver,
            "path_index": path_index,
            "delay_s": tau,
            "delay_ns": tau * 1e9,
            "path_length_m_from_delay": tau * LIGHT_SPEED_M_S,
            "a_real": real,
            "a_imag": imag,
            "magnitude": magnitude,
            "magnitude_db": gain_db,
            "interaction_type_ids": interaction_ids,
            "interaction_types": interaction_names,
            "interacted_objects": [str(name) for name in objects],
            "interacted_primitives": [int(value) for value in primitives],
            "interaction_vertices_m": converted_vertices[1:-1],
            "is_los": not bool(interactions),
            "source_angles_rad": {
                name: _nullable_number(source.get(name))
                for name in ("theta_t", "phi_t", "theta_r", "phi_r")
            },
            "doppler_hz": _nullable_number(source.get("doppler")),
        })
    return output


def _validate_path_endpoints(result: dict[str, Any], tx_devices: list[dict[str, Any]],
                             rx_devices: list[dict[str, Any]], tolerance_m: float) -> float:
    """Verify raw path endpoints match exported device coordinates within metres."""
    tx_positions = {row["name"]: row["position_m"] for row in tx_devices}
    rx_positions = {row["name"]: row["position_m"] for row in rx_devices}
    paths = result.get("paths")
    if not isinstance(paths, list):
        raise ValueError("Result JSON must contain a 'paths' array")
    maximum_error_m = 0.0
    for path in paths:
        if not isinstance(path, dict):
            raise ValueError("Each result path must be a JSON object")
        tx_name, rx_name = path.get("tx"), path.get("rx")
        if tx_name not in tx_positions or rx_name not in rx_positions:
            raise ValueError(f"Path references an unknown TX/RX pair: {tx_name!r}/{rx_name!r}")
        vertices = path.get("vertices")
        if not isinstance(vertices, list) or len(vertices) < 2:
            raise ValueError(f"Path {tx_name}/{rx_name} must have at least TX and RX vertices")
        first = _vector(vertices[0], f"path {tx_name}/{rx_name} TX endpoint")
        last = _vector(vertices[-1], f"path {tx_name}/{rx_name} RX endpoint")
        tx_error = math.dist(first, tx_positions[tx_name])
        rx_error = math.dist(last, rx_positions[rx_name])
        maximum_error_m = max(maximum_error_m, tx_error, rx_error)
        if tx_error > tolerance_m:
            raise ValueError(
                f"Path {tx_name}/{rx_name} TX endpoint differs from its device by "
                f"{tx_error:.6g} m (configured tolerance {tolerance_m:.6g} m)"
            )
        if rx_error > tolerance_m:
            raise ValueError(
                f"Path {tx_name}/{rx_name} RX endpoint differs from its device by "
                f"{rx_error:.6g} m (configured tolerance {tolerance_m:.6g} m)"
            )
    return maximum_error_m


def _links_for_tx(result: dict[str, Any], tx_name: str, tx_names: set[str],
                  rx_names: set[str]) -> list[dict[str, Any]]:
    rows = result.get("links")
    if not isinstance(rows, list):
        raise ValueError("Result JSON must contain a 'links' array")
    frequencies = [_nullable_number(value) for value in result.get("cfr_frequencies", [])]
    output: list[dict[str, Any]] = []
    for source in rows:
        if not isinstance(source, dict):
            raise ValueError("Each result link must be a JSON object")
        source_tx, receiver = source.get("tx"), source.get("rx")
        if source_tx not in tx_names or receiver not in rx_names:
            raise ValueError(f"Link references an unknown TX/RX pair: {source_tx!r}/{receiver!r}")
        if source_tx != tx_name:
            continue
        delay_spread_s = _nullable_number(source.get("delay_spread"))
        output.append({
            "tx": source_tx,
            "rx": receiver,
            "num_paths": int(source.get("num_paths", 0)),
            "gain_db_coherent": _nullable_number(source.get("gain_db_coherent")),
            "gain_db_incoherent": _nullable_number(source.get("gain_db_incoherent")),
            "delay_spread_s": delay_spread_s,
            "delay_spread_ns": None if delay_spread_s is None else delay_spread_s * 1e9,
            "cfr_db": [_nullable_number(value) for value in source.get("cfr_db", [])],
            "cfr_frequencies_hz": frequencies,
            "vertices_m": [_vector(point, f"link {source_tx}/{receiver} vertex")
                           for point in source.get("vertices", [])],
        })
    return output


def _receiver_metrics(receiver_names: list[str], paths: list[dict[str, Any]],
                      links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for receiver in receiver_names:
        receiver_paths = [path for path in paths if path["receiver"] == receiver]
        receiver_link = next((link for link in links if link["rx"] == receiver), None)
        strongest = max(receiver_paths, key=lambda row: row["magnitude"], default=None)
        aggregate_power = sum(path["magnitude"] ** 2 for path in receiver_paths)
        interaction_counts = {
            kind: sum(kind in path["interaction_types"] for path in receiver_paths)
            for kind in ("specular_reflection", "refraction", "diffuse_reflection", "diffuse_scattering", "diffraction")
        }
        aggregate_db = (receiver_link.get("gain_db_incoherent") if receiver_link else None)
        if aggregate_db is None and aggregate_power > 0:
            aggregate_db = 10.0 * math.log10(aggregate_power)
        metrics.append({
            "receiver": receiver,
            "path_count": len(receiver_paths),
            "los_present": any(path["is_los"] for path in receiver_paths),
            "strongest_path_db": None if strongest is None else strongest["magnitude_db"],
            "strongest_path_delay_ns": None if strongest is None else strongest["delay_ns"],
            "aggregate_path_coefficient_power_db": aggregate_db,
            "aggregate_path_coefficient_power_linear": aggregate_power,
            "aggregate_power_definition": "sum of individual |a|^2; not RSS",
            "interaction_path_counts": interaction_counts,
            "link_metrics": None if receiver_link is None else {
                "gain_db_coherent": receiver_link["gain_db_coherent"],
                "gain_db_incoherent": receiver_link["gain_db_incoherent"],
                "delay_spread_ns": receiver_link["delay_spread_ns"],
                "cfr_db": receiver_link["cfr_db"],
                "cfr_frequencies_hz": receiver_link["cfr_frequencies_hz"],
            },
        })
    return metrics


def _radio_maps(folder: Path, radio_file: Path | None, measure_file: Path | None,
                tx_names: list[str], asset_prefix: str
                ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if radio_file is None:
        return [], {}
    if measure_file is None:
        raise ValueError("A radiomap JSON is present but its matching _measure.json file is missing")
    measure_names = _read_json(measure_file)
    if not isinstance(measure_names, list) or not all(isinstance(name, str) for name in measure_names):
        raise ValueError(f"{measure_file.name} must be a JSON array of measurement mesh names")
    data = _read_radiomap(radio_file)
    if not isinstance(data, dict) or not isinstance(data.get("maps"), list):
        raise ValueError(f"{radio_file.name} must contain a 'maps' array")
    result_tx_names = data.get("tx")
    if not isinstance(result_tx_names, list) or result_tx_names != tx_names:
        raise ValueError("Radiomap 'tx' order must match the TX order in the TX/RX JSON")
    map_names = [row.get("name") for row in data["maps"] if isinstance(row, dict)]
    if map_names != measure_names:
        raise ValueError("Radiomap map names/order must match the _measure.json array")

    surfaces: list[dict[str, Any]] = []
    mesh_assets: dict[str, Any] = {}
    all_bounds: list[dict[str, float]] = []
    for map_data in data["maps"]:
        name = map_data["name"]
        measurement_ply = _safe_run_file(folder, f"meshes/{name}.ply", "Measurement mesh")
        ply_vertices, ply_faces = _load_ply(measurement_ply)
        vertices = [_vector(point, f"radiomap {name} vertex") for point in map_data.get("vertices", [])]
        faces = map_data.get("faces")
        values_matrix = map_data.get("path_gain_db")
        if not isinstance(faces, list) or not isinstance(values_matrix, list):
            raise ValueError(f"Radiomap surface {name!r} is missing faces or path_gain_db")
        normalized_faces = [[int(index) for index in face] for face in faces]
        if len(normalized_faces) != len(ply_faces):
            raise ValueError(f"Radiomap surface {name!r} face count does not match its PLY measurement mesh")
        if any(len(face) != 3 or any(index < 0 or index >= len(vertices) for index in face)
               for face in normalized_faces):
            raise ValueError(f"Radiomap surface {name!r} contains invalid triangle indices")
        if len(vertices) != len(ply_vertices):
            raise ValueError(f"Radiomap surface {name!r} vertex count does not match its PLY measurement mesh")
        if len(values_matrix) != len(normalized_faces):
            raise ValueError(f"Radiomap surface {name!r} must have one path-gain row per triangle")
        if any(not isinstance(row, list) or len(row) != len(tx_names) for row in values_matrix):
            raise ValueError(f"Radiomap surface {name!r} rows must follow the 'tx' order and contain one value per TX")

        bounds = _bounds(vertices)
        all_bounds.append(bounds)
        mesh_ref = f"{asset_prefix}:measurement:{name}"
        mesh_assets[mesh_ref] = {"vertices_m": vertices, "faces": normalized_faces, "bounds_m": bounds}
        for tx_index, tx_name in enumerate(tx_names):
            surfaces.append({
                "name": name,
                "tx": tx_name,
                "mesh_ref": mesh_ref,
                "values_db": [_nullable_number(row[tx_index]) for row in values_matrix],
                "quantity": "path_gain",
                "units": "10 log10(path gain), dB; -999/non-finite values are missing",
            })
    return surfaces, mesh_assets


def _scenario_dimensions(bounds: dict[str, float]) -> list[float]:
    return [max(bounds[f"{axis}_max"] - bounds[f"{axis}_min"], 0.01) for axis in ("x", "y", "z")]


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value) or math.isclose(value, MISSING_VALUE, abs_tol=1e-9):
            return None
        return value
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_json(item) for key, item in value.items()}
    return value


def import_run(run_folder: str | Path, project_root: str | Path, *,
               progress_callback: Callable[[str], None] | None = None,
               dry_run: bool = False, run_id: str | None = None) -> Path | dict[str, Any]:
    """Validate and normalize a HOUSIONNA run; return its viewer-import file."""
    folder = Path(run_folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"HOUSIONNA run folder does not exist or is not a directory: {folder}")
    run_id = run_id or _run_id_for_folder(folder)
    def report(stage: str) -> None:
        if progress_callback:
            progress_callback(stage)

    report("validating_export")
    source_sha256, source_file_hashes = _source_fingerprint(folder)
    folder_tag = re.sub(r"[^A-Za-z0-9_]+", "_", run_id).strip("_") or "run"
    output_tag = f"{folder_tag}-{source_sha256[:12]}"
    root = Path(project_root).resolve()
    path_endpoint_tolerance_m = configured_path_endpoint_tolerance(root)
    output_file = root / "outputs" / "integrations" / "housionna" / output_tag / "viewer_import.json"
    if output_file.is_file():
        try:
            cached = _read_json(output_file)
            if (cached.get("provenance", {}).get("source_sha256") == source_sha256 and
                    cached.get("provenance", {}).get("adapter_version") == ADAPTER_VERSION and
                    cached.get("provenance", {}).get("path_endpoint_tolerance_m") == path_endpoint_tolerance_m):
                if dry_run:
                    return cached
                report("ready_cached")
                return output_file
        except (ValueError, AttributeError):
            pass
    scene_file = _one_file(folder, "_scene.xml")
    txrx_file = _one_file(folder, "_txrx.json")
    settings_file = _one_file(folder, "_settings.json")
    result_file = _artifact(folder, "_result")
    dump_file = _one_file(folder, "_dump.json", required=False)
    measure_file = _one_file(folder, "_measure.json", required=False)
    radio_file = _artifact(folder, "_radiomap", required=False)
    assert scene_file and txrx_file and settings_file and result_file

    devices_data = _read_json(txrx_file)
    tx_devices, rx_devices = _devices(devices_data)
    settings = _read_json(settings_file)
    result = _read_result(result_file)
    if not isinstance(settings, dict):
        raise ValueError(f"{settings_file.name} must contain a JSON object")
    if not isinstance(result, dict):
        raise ValueError(f"{result_file.name} must contain a JSON object")
    frequency_hz = _required_number(settings.get("frequency"), "settings.frequency")
    if frequency_hz <= 0:
        raise ValueError("settings.frequency must be greater than zero")
    if not isinstance(result.get("paths"), list) or not isinstance(result.get("links"), list):
        raise ValueError("Result JSON must contain 'paths' and 'links' arrays")
    if not isinstance(result.get("settings"), dict):
        raise ValueError("Result JSON must contain the settings used for this solve")
    max_path_endpoint_error_m = _validate_path_endpoints(
        result, tx_devices, rx_devices, path_endpoint_tolerance_m)

    dump_data = _read_json(dump_file) if dump_file else None
    report("importing_geometry")
    geometry, materials = _scene_from_xml(folder, scene_file, dump_data)
    scene_object_names = {item["id"] for item in geometry["objects"]}
    for item in geometry["objects"]:
        item["object_name"] = item["name"]
        item["mesh_file"] = item["metadata"]["mesh_file"]
        item["material_key"] = item["metadata"]["material_name"]
        item["triangle_count"] = len(item["faces"])
        item["rf_relevant"] = True
    tx_names = [item["name"] for item in tx_devices]
    rx_names = [item["name"] for item in rx_devices]
    tx_name_set, rx_name_set = set(tx_names), set(rx_names)
    asset_prefix = source_sha256[:12]
    assets = {"geometries": {f"housionna:{asset_prefix}:scene": geometry}, "meshes": {}}

    report("processing_radio_map")
    radio_surfaces, map_assets = _radio_maps(
        folder, radio_file, measure_file, tx_names, f"housionna:{asset_prefix}")
    assets["meshes"].update(map_assets)
    map_bounds = [_bounds(assets["meshes"][surface["mesh_ref"]]["vertices_m"])
                  for surface in radio_surfaces]
    scene_bounds = geometry["bounds_m"]
    all_bounds = [scene_bounds, *map_bounds] if scene_bounds else list(map_bounds)
    if not geometry["objects"]:
        all_bounds.append(_bounds([row["position_m"] for row in (*tx_devices, *rx_devices)]))
    overall_bounds = _union_bounds(all_bounds)
    if scene_bounds is None:
        geometry["bounds_m"] = overall_bounds
    dimensions = _scenario_dimensions(overall_bounds)
    radio_bounds = _union_bounds(map_bounds) if map_bounds else overall_bounds
    radio_center = [(radio_bounds[f"{axis}_min"] + radio_bounds[f"{axis}_max"]) / 2
                    for axis in ("x", "y", "z")]
    map_dimensions = [radio_bounds["x_max"] - radio_bounds["x_min"],
                      radio_bounds["y_max"] - radio_bounds["y_min"]]

    report("normalizing_results")
    path_rows_by_tx = {
        tx_name: _paths_for_tx(result, tx_name, tx_name_set, rx_name_set, scene_object_names)
        for tx_name in tx_names
    }
    links_by_tx = {
        tx_name: _links_for_tx(result, tx_name, tx_name_set, rx_name_set)
        for tx_name in tx_names
    }
    solver_settings = {
        "path_solver": {
            "max_depth": settings.get("max_depth"),
            "samples_per_source": settings.get("samples"),
            **{key: settings.get(key) for key in
               ("los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction")},
        },
        "radio_map_solver": {
            "samples_per_transmitter": settings.get("radiomap_samples"),
            "max_depth": settings.get("max_depth"),
        },
        "bandwidth_hz": _nullable_number(settings.get("bandwidth")),
        "cfr_points": settings.get("cfr_points"),
    }

    scenarios: dict[str, dict[str, Any]] = {}
    scenario_order: list[str] = []
    for tx in tx_devices:
        tx_name = tx["name"]
        tx_tag = re.sub(r"[^A-Za-z0-9_]+", "_", tx_name).strip("_") or "tx"
        scenario_key = f"housionna_{folder_tag}_{asset_prefix}_{tx_tag}"
        tx_paths = path_rows_by_tx[tx_name]
        tx_links = links_by_tx[tx_name]
        tx_maps = [surface for surface in radio_surfaces if surface["tx"] == tx_name]
        map_values = [value for surface in tx_maps for value in surface["values_db"] if value is not None]
        map_min = min(map_values) if map_values else None
        map_max = max(map_values) if map_values else None
        scene_entry = {
            "name": scenario_key,
            "label": f"HOUSIONNA {run_id} · {tx_name}",
            "description": f"Imported HOUSIONNA Houdini → Sionna RT result from run {run_id}; viewing {tx_name}.",
            "source_type": "housionna",
            "provenance": {
                "pipeline": "HOUSIONNA Houdini → Sionna RT → Houdini",
                "run_folder_name": run_id,
                "source_run_folder": str(folder),
                "source_scene_file": scene_file.name,
                "source_device_file": txrx_file.name,
                "source_settings_file": settings_file.name,
                "source_result_file": result_file.name,
                "source_sionna_rt": result.get("sionna_rt"),
                "source_variant": result.get("variant"),
                "imported_at_utc": datetime.now(timezone.utc).isoformat(),
                "import_id": output_tag,
                "source_sha256": source_sha256,
                "coordinate_system": "Sionna coordinates in metres; X/Y horizontal, Z up. HOUSIONNA already applies its Houdini-to-Sionna transform during export.",
                "path_endpoint_tolerance_m": path_endpoint_tolerance_m,
                "max_path_endpoint_error_m": max_path_endpoint_error_m,
            },
            "run_metadata": {
                "run_id": run_id,
                "import_id": output_tag,
                "imported_at_utc": None,
                "source_sha256": source_sha256,
            },
            "frequency_hz": frequency_hz,
            "greenhouse": {"length_m": dimensions[0], "width_m": dimensions[1], "height_m": dimensions[2]},
            "environment": {"label": f"HOUSIONNA run {run_id}"},
            "scene_dimensions_m": dimensions,
            "scene_bounds_m": overall_bounds,
            "structure_config": {},
            "canopy_config": {},
            "geometry_ref": f"housionna:{asset_prefix}:scene",
            "materials": materials,
            "antenna": {"rows": 1, "columns": 1, "pattern": "iso", "polarization": "V"},
            "transmitter": {
                "name": tx_name,
                "position_m": tx["position_m"],
                "orientation_rad": tx["orientation_rad"],
                "velocity_m_s": tx["velocity_m_s"],
                "power_dbm": tx["power_dbm"],
            },
            "receivers": [
                {**rx, "role": "HOUSIONNA receiver"}
                for rx in rx_devices
            ],
            "receiver_metrics": _receiver_metrics(rx_names, tx_paths, tx_links),
            "radio_map": {
                "values_db": [],
                "center_m": radio_center,
                "size_m": map_dimensions,
                "shape_yx": [sum(len(surface["values_db"]) for surface in tx_maps), 1],
                "units": "10 log10(path gain), dB; values below 1e-15 are missing",
                "quantity": "path_gain",
                "min_db": map_min,
                "max_db": map_max,
                "surfaces": [{key: value for key, value in surface.items() if key != "tx"}
                             for surface in tx_maps],
            },
            "difference_map_db": None,
            "paths": tx_paths,
            "links": tx_links,
            "path_count": len(tx_paths),
            "material_status": "IMPORTED · HOUSIONNA",
            "solver": solver_settings,
            "visual_plants": {"visualization_only": True, "visible_by_default": False, "label": "No decorative Three.js plants in imported scene"},
        }
        scenarios[scenario_key] = scene_entry
        scenario_order.append(scenario_key)

    artifact_names = sorted(source_file_hashes)
    imported_at = datetime.now(timezone.utc).isoformat()
    scene_name = scene_file.stem.removesuffix("_scene")
    total_path_count = sum(len(rows) for rows in path_rows_by_tx.values())
    total_map_triangles = sum(len(surface["values_db"]) for surface in radio_surfaces)
    run_metadata = {
        "run_id": run_id,
        "scene_name": scene_name,
        "import_id": output_tag,
        "imported_at_utc": imported_at,
        "frequency_hz": frequency_hz,
        "tx_count": len(tx_devices),
        "rx_count": len(rx_devices),
        "mesh_count": len(geometry["objects"]),
        "path_count": total_path_count,
        "radio_map_triangle_count": total_map_triangles,
        "source_sha256": source_sha256,
        **_houdini_metadata(folder),
    }
    for scenario in scenarios.values():
        scenario["run_metadata"]["imported_at_utc"] = imported_at
        scenario["run_metadata"].update({key: value for key, value in run_metadata.items()
                                         if key not in {"import_id", "imported_at_utc"}})
    document = {
        "schema_version": 1,
        "adapter_version": ADAPTER_VERSION,
        "source": "HOUSIONNA run normalized for the HyROPA Three.js digital twin.",
        "imported_at_utc": imported_at,
        "run_metadata": run_metadata,
        "settings": settings,
        "provenance": {
            "pipeline": "HOUSIONNA Houdini → Sionna RT → Houdini",
            "source_run_folder": str(folder),
            "source_run_name": run_id,
            "source_files": artifact_names,
            "source_file_sha256": source_file_hashes,
            "source_sha256": source_sha256,
            "source_format": "HOUSIONNA Sionna RT export",
            "adapter_version": ADAPTER_VERSION,
            "sionna_rt": result.get("sionna_rt"),
            "variant": result.get("variant"),
            "coordinate_system": "Sionna XYZ, metres, Z up; the exporter already maps Houdini (x,y,z) to (x,-z,y), so coordinates are passed through unchanged.",
            "path_endpoint_tolerance_m": path_endpoint_tolerance_m,
            "max_path_endpoint_error_m": max_path_endpoint_error_m,
        },
        "assets": assets,
        "scenario_order": scenario_order,
        "featured_scenario": scenario_order[0],
        "scenarios": scenarios,
    }
    document = _sanitize_json(document)
    if dry_run:
        report("validated")
        return document
    report("saving_viewer_data")
    output_dir = output_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = output_file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                         encoding="utf-8")
    temporary.replace(output_file)
    return output_file


def configured_runs_directory(project_root: str | Path) -> Path:
    """Resolve the configured export directory without accepting request paths."""
    root = Path(project_root).resolve()
    override = os.environ.get("HOUSIONNA_RUNS_DIRECTORY")
    if override:
        configured = Path(override).expanduser()
    else:
        config_file = root / "config" / "housionna.yaml"
        if config_file.is_file():
            try:
                raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as error:
                raise ValueError("config/housionna.yaml is not valid YAML") from error
            section = raw.get("housionna") if isinstance(raw, dict) else None
            value = section.get("runs_directory") if isinstance(section, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise ValueError("config/housionna.yaml must define housionna.runs_directory")
            configured = Path(value).expanduser()
        else:
            configured = Path("../houdini_files/sionna/data")
    if not configured.is_absolute():
        configured = root / configured
    return configured.resolve()


def configured_path_endpoint_tolerance(project_root: str | Path) -> float:
    """Read the raw-path/device endpoint tolerance in metres from local config."""
    root = Path(project_root).resolve()
    config_file = root / "config" / "housionna.yaml"
    if not config_file.is_file():
        return DEFAULT_PATH_ENDPOINT_TOLERANCE_M
    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise ValueError("config/housionna.yaml is not valid YAML") from error
    section = raw.get("housionna") if isinstance(raw, dict) else None
    value = section.get("path_endpoint_tolerance_m", DEFAULT_PATH_ENDPOINT_TOLERANCE_M) if isinstance(section, dict) else DEFAULT_PATH_ENDPOINT_TOLERANCE_M
    tolerance = _required_number(value, "housionna.path_endpoint_tolerance_m")
    if tolerance < 0:
        raise ValueError("housionna.path_endpoint_tolerance_m must be zero or greater")
    return tolerance


# Batch exports (Oct 2026): <batches>/<batch>/wiNNN/ holds one complete run per Houdini work item, next to
# batch.json and status.json. Such a run is addressed as "<batch>.wiNNN"; plain runs keep their folder name.
BATCH_RUN_ID = re.compile(r"([A-Za-z0-9][A-Za-z0-9_-]*)\.(wi\d+)")
WORK_ITEM = re.compile(r"wi\d+")


def configured_batches_directory(project_root: str | Path) -> Path:
    """housionna.batches_directory, or the "batches" folder next to the runs directory."""
    root = Path(project_root).resolve()
    value = os.environ.get("HOUSIONNA_BATCHES_DIRECTORY")
    config_file = root / "config" / "housionna.yaml"
    if not value and config_file.is_file():
        try:
            raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            raise ValueError("config/housionna.yaml is not valid YAML") from error
        section = raw.get("housionna") if isinstance(raw, dict) else None
        value = section.get("batches_directory") if isinstance(section, dict) else None
    if not value:
        return configured_runs_directory(root).parent / "batches"
    configured = Path(value).expanduser()
    return (configured if configured.is_absolute() else root / configured).resolve()


def _batch_of(run_id: str) -> str | None:
    match = BATCH_RUN_ID.fullmatch(run_id)
    return match.group(1) if match else None


def _run_id_for_folder(folder: Path) -> str:
    if WORK_ITEM.fullmatch(folder.name) and (folder.parent / "batch.json").is_file():
        return f"{folder.parent.name}.{folder.name}"
    return folder.name


def _run_folders(project_root: str | Path) -> list[tuple[str, Path]]:
    """Every candidate run: direct children of the runs directory, then each work item of each batch."""
    runs_root = configured_runs_directory(project_root)
    found = [(child.name, child) for child in runs_root.iterdir() if child.is_dir()] if runs_root.is_dir() else []
    batches_root = configured_batches_directory(project_root)
    if batches_root.is_dir():
        for batch in sorted(batches_root.iterdir()):
            if batch.is_dir() and not batch.is_symlink() and (batch / "batch.json").is_file():
                found += [(f"{batch.name}.{item.name}", item) for item in sorted(batch.iterdir())
                          if item.is_dir() and WORK_ITEM.fullmatch(item.name)]
    return found


def resolve_run_folder(project_root: str | Path, run_id: Any) -> Path:
    """Map a run id from the API to its folder, without accepting paths, traversal or symlinks."""
    if not _valid_run_id(run_id):
        raise ValueError("Invalid HOUSIONNA run identifier")
    batch = _batch_of(run_id)
    if batch:
        base = configured_batches_directory(project_root).resolve()
        unresolved = base / batch / run_id.split(".", 1)[1]
        links = (base / batch).is_symlink() or unresolved.is_symlink()
        folder = unresolved.resolve()
        inside = folder.parent.parent == base
    else:
        base = configured_runs_directory(project_root).resolve()
        unresolved = base / run_id
        links = unresolved.is_symlink()
        folder = unresolved.resolve()
        inside = folder.parent == base
    if links or not inside or not folder.is_dir():
        raise FileNotFoundError(f"HOUSIONNA run {run_id!r} is not available")
    return folder


def _houdini_metadata(folder: Path) -> dict[str, Any]:
    """Provenance and wedge parameters from <hip>_meta.json (and the batch's batch.json), without local paths.

    The meta file is not part of the source hash: it describes the run and never changes its RF content.
    """
    out: dict[str, Any] = {}
    meta_file = _one_file(folder, "_meta.json", required=False)
    meta = _read_json(meta_file) if meta_file else {}
    if isinstance(meta, dict) and meta:
        out["houdini"] = {key: meta[key] for key in ("houdini", "commit", "dirty", "exported_utc") if key in meta}
        if isinstance(meta.get("hip"), str):
            out["houdini"]["hip_file"] = re.split(r"[\\/]", meta["hip"])[-1]  # file name only, never the path
        wedge = meta.get("wedge") if isinstance(meta.get("wedge"), dict) else {}
        # Every wedged attribute starts with TOPS_ (agreed with Joris, Oct 2026).
        parameters = {key: value for key, value in wedge.items()
                      if key.startswith("TOPS_") and isinstance(value, (int, float)) and not isinstance(value, bool)}
        if parameters:
            out["parameters"] = parameters
        if wedge:
            out["wedge"] = {key: wedge[key] for key in ("wedgeindex", "wedgetotal", "wedgeattribs") if key in wedge}
    batch_file = folder.parent / "batch.json"
    if WORK_ITEM.fullmatch(folder.name) and batch_file.is_file():
        batch = _read_json(batch_file)
        if isinstance(batch, dict):
            out["batch"] = {"id": folder.parent.name, "work_item": folder.name,
                            "top_node": batch.get("top_node"), "created_utc": batch.get("created_utc"),
                            "items": len(batch.get("items") or {}) or None}
    return out


def _valid_run_id(run_id: Any) -> bool:
    return (isinstance(run_id, str) and len(run_id) <= 128 and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id) is not None and
            run_id not in {".", ".."} and ".." not in run_id)


def _summary_from_document(import_id: str, document: dict[str, Any]) -> dict[str, Any]:
    metadata = document.get("run_metadata") or {}
    return {
        "import_id": import_id,
        "adapter_version": document.get("adapter_version"),
        "path_endpoint_tolerance_m": document.get("provenance", {}).get("path_endpoint_tolerance_m"),
        "run_id": metadata.get("run_id") or document.get("provenance", {}).get("source_run_name"),
        "scene_name": metadata.get("scene_name"),
        "imported_at_utc": document.get("imported_at_utc"),
        "frequency_hz": metadata.get("frequency_hz"),
        "tx_count": metadata.get("tx_count", len(document.get("scenario_order", []))),
        "rx_count": metadata.get("rx_count"),
        "mesh_count": metadata.get("mesh_count"),
        "path_count": metadata.get("path_count"),
        "radio_map_triangle_count": metadata.get("radio_map_triangle_count"),
        "source_sha256": metadata.get("source_sha256") or document.get("provenance", {}).get("source_sha256"),
        "transmitters": [scenario.get("transmitter", {}).get("name")
                          for scenario in document.get("scenarios", {}).values()],
    }


def _folder_stat_key(folder: Path) -> list[list[Any]]:
    """Name, size and mtime of every file a fingerprint can read: the run folder and its meshes/."""
    key = []
    for directory in (folder, folder / "meshes"):
        if directory.is_dir():
            for entry in os.scandir(directory):
                if entry.is_file(follow_symlinks=False):
                    stat = entry.stat(follow_symlinks=False)
                    key.append([f"{directory.name}/{entry.name}" if directory != folder else entry.name,
                                stat.st_size, stat.st_mtime_ns])
    return sorted(key)


def _load_discovery_cache(root: Path) -> dict[str, Any]:
    cache_file = root / "outputs" / "integrations" / "housionna" / "discovery_cache.json"
    if _DISCOVERY_CACHE["file"] != str(cache_file):
        runs: dict[str, Any] = {}
        try:
            stored = _read_json(cache_file)
            if stored.get("schema") == DISCOVERY_CACHE_SCHEMA and stored.get("adapter_version") == ADAPTER_VERSION:
                runs = stored.get("runs") or {}
        except (OSError, ValueError, AttributeError):
            pass
        _DISCOVERY_CACHE.update(file=str(cache_file), runs=runs)
    return _DISCOVERY_CACHE["runs"]


def _save_discovery_cache(root: Path) -> None:
    from integrations.housionna_performance import atomic_json
    cache_file = Path(_DISCOVERY_CACHE["file"])
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(cache_file, {"schema": DISCOVERY_CACHE_SCHEMA, "adapter_version": ADAPTER_VERSION,
                             "runs": _DISCOVERY_CACHE["runs"]}, compact=True)


def discover_runs(project_root: str | Path, *, only: str | None = None) -> list[dict[str, Any]]:
    with _DISCOVERY_CACHE_LOCK:
        return _discover_runs(project_root, only=only)


def _discover_runs(project_root: str | Path, *, only: str | None = None) -> list[dict[str, Any]]:
    """List child folders and validate complete exports without importing them."""
    root = Path(project_root).resolve()
    runs_root = configured_runs_directory(root)
    rows: list[dict[str, Any]] = []
    stored = _load_discovery_cache(root)
    changed = False
    # A validated normalized import can certify unchanged source bytes. New or
    # changed exports still undergo the complete geometry/result validation.
    summaries = list_imports(root)
    tolerance = configured_path_endpoint_tolerance(root)
    required_suffixes = ("_scene.xml", "_txrx.json", "_settings.json", ("_result.json", "_result.npz"))
    # only=<run id> validates one run (an import job) instead of every run in every batch.
    for run_id, folder in (item for item in _run_folders(root) if only is None or item[0] == only):
        row: dict[str, Any] = {"run_id": run_id, "status": "invalid", "errors": []}
        batch = _batch_of(run_id)
        if batch:
            row["batch_id"] = batch
        if folder.is_symlink() or not _valid_run_id(run_id):
            row["errors"].append("Run folder name is not a supported identifier")
            rows.append(row)
            continue
        missing = []
        try:
            for suffix in required_suffixes:
                if not any(file.is_file() and file.name.endswith(suffix) for file in folder.iterdir()):
                    names = suffix if isinstance(suffix, tuple) else (suffix,)
                    missing.append(" or ".join(f"*{name}" for name in names))
            if missing:
                row.update({"status": "incomplete", "missing_artifacts": missing})
            else:
                stat_key = _folder_stat_key(folder)
                entry = stored.get(f"{folder.resolve()}") or {}
                if entry.get("stat_key") == stat_key and entry.get("source_sha256"):
                    source_hash = entry["source_sha256"]
                else:
                    source_hash, _ = _source_fingerprint(folder.resolve())
                    entry = {"stat_key": stat_key, "source_sha256": source_hash}
                    stored[f"{folder.resolve()}"] = entry
                    changed = True
                signature = f"{source_hash}:{tolerance:.12g}"
                if entry.get("signature") == signature and entry.get("row", {}).get("run_id") == run_id:
                    row.update(entry["row"])
                    rows.append(row)
                    continue
                cache_key = (str(runs_root.resolve()), run_id)
                cached_validation = _RUN_VALIDATION_CACHE.get(cache_key)
                if cached_validation and cached_validation[0] == signature:
                    row.update(cached_validation[1])
                    rows.append(row)
                    continue
                summary = next((item for item in summaries if item.get("run_id") == run_id and
                                item.get("source_sha256") == source_hash and item.get("adapter_version") == ADAPTER_VERSION and
                                item.get("path_endpoint_tolerance_m") == tolerance), None)
                if summary is None:
                    document = import_run(folder, root, dry_run=True, run_id=run_id)
                    assert isinstance(document, dict)
                    summary = _summary_from_document("", document)
                row.update({key: summary[key] for key in (
                    "scene_name", "frequency_hz", "tx_count", "rx_count", "mesh_count",
                    "path_count", "radio_map_triangle_count", "source_sha256", "transmitters")})
                row["status"] = "valid"
                row["timestamp"] = _run_timestamp(folder.parent if batch else folder)
                _RUN_VALIDATION_CACHE[cache_key] = (signature, dict(row))
                while len(_RUN_VALIDATION_CACHE) > 4096:
                    _RUN_VALIDATION_CACHE.pop(next(iter(_RUN_VALIDATION_CACHE)))
                entry.update(signature=signature, row=dict(row))
                changed = True
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as error:
            message = str(error).replace(str(folder), "run folder")
            message = re.sub(r"(?i)\b[a-z]:\\[^\r\n\"']+", "<local path>", message)
            row.update({"status": "invalid", "errors": [message[:360]]})
        rows.append(row)
    rows.sort(key=lambda row: (row.get("timestamp", ""), row["run_id"]), reverse=True)
    if only is None:
        # Forget folders that no longer exist, so the file stays the size of what is on disk.
        present = {f"{folder.resolve()}" for _, folder in _run_folders(root)}
        for key in [key for key in stored if key not in present]:
            del stored[key]
            changed = True
    if changed:
        try:
            _save_discovery_cache(root)
        except OSError:
            pass  # the cache only saves time
    # Never return source paths through the local API.
    return rows


def _run_timestamp(folder: Path) -> str:
    match = re.fullmatch(r"(\d{8})_(\d{6})Z", folder.name)
    if match:
        try:
            return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(folder.stat().st_mtime, tz=timezone.utc).isoformat()


def list_imports(project_root: str | Path) -> list[dict[str, Any]]:
    root = Path(project_root).resolve()
    integration_root = root / "outputs" / "integrations" / "housionna"
    if not integration_root.is_dir():
        return []
    rows = []
    for import_file in integration_root.glob("*/viewer_import.json"):
        try:
            stat=import_file.stat()
            signature=(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
            with _IMPORT_SUMMARY_LOCK:
                entry=_IMPORT_SUMMARY_CACHE.pop(str(import_file),None)
                if entry is None or entry[0] != signature:
                    document=_read_json(import_file)
                    if document.get("schema_version") != 1:continue
                    entry=(signature,_summary_from_document(import_file.parent.name,document))
                _IMPORT_SUMMARY_CACHE[str(import_file)]=entry
                while len(_IMPORT_SUMMARY_CACHE)>4096:_IMPORT_SUMMARY_CACHE.popitem(last=False)  # small summaries; batches hold hundreds of runs
                rows.append(dict(entry[1]))
        except (OSError, ValueError, AttributeError):
            continue
    rows.sort(key=lambda row: (row.get("imported_at_utc") or "", row["import_id"]), reverse=True)
    return rows


def read_import(project_root: str | Path, import_id: Any) -> dict[str, Any]:
    if not _valid_run_id(import_id):
        raise ValueError("Invalid imported run identifier")
    root = Path(project_root).resolve()
    integration_root = (root / "outputs" / "integrations" / "housionna").resolve()
    candidate = (integration_root / import_id / "viewer_import.json").resolve()
    try:
        candidate.relative_to(integration_root)
    except ValueError as error:
        raise ValueError("Imported run identifier is outside the integration output directory") from error
    if not candidate.is_file():
        raise FileNotFoundError("Imported HOUSIONNA run was not found")
    document = _read_json(candidate)
    if document.get("schema_version") != 1:
        raise ValueError("Unsupported normalized HOUSIONNA import schema")
    return document


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _scenario_for_tx(document: dict[str, Any], transmitter: str) -> dict[str, Any]:
    for scenario in document.get("scenarios", {}).values():
        if scenario.get("transmitter", {}).get("name") == transmitter:
            return scenario
    raise ValueError(f"Transmitter {transmitter!r} is not present in both selected imports")


def compare_imports(project_root: str | Path, reference_id: Any,
                    comparison_id: Any, transmitter: Any) -> dict[str, Any]:
    if not isinstance(transmitter, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", transmitter):
        raise ValueError("A valid transmitter name is required")
    reference = read_import(project_root, reference_id)
    comparison = read_import(project_root, comparison_id)
    left = _scenario_for_tx(reference, transmitter)
    right = _scenario_for_tx(comparison, transmitter)
    left_geometry = reference.get("assets", {}).get("geometries", {}).get(left.get("geometry_ref"))
    right_geometry = comparison.get("assets", {}).get("geometries", {}).get(right.get("geometry_ref"))
    if left_geometry is None or right_geometry is None:
        raise ValueError("A selected import is missing its normalized scene geometry")
    left_scene_hash = _canonical_sha256(left_geometry)
    right_scene_hash = _canonical_sha256(right_geometry)
    same_frequency = math.isclose(float(left["frequency_hz"]), float(right["frequency_hz"]), rel_tol=1e-9)
    device_fields = ("position_m", "orientation_rad", "velocity_m_s")
    left_devices = {item["name"]: tuple(item.get(field) for field in device_fields)
                    for item in left.get("receivers", [])}
    right_devices = {item["name"]: tuple(item.get(field) for field in device_fields)
                     for item in right.get("receivers", [])}
    same_receivers = left_devices == right_devices
    tx_fields = (*device_fields, "power_dbm")
    same_transmitter = all(left.get("transmitter", {}).get(field) ==
                           right.get("transmitter", {}).get(field) for field in tx_fields)
    same_materials = _canonical_sha256(left.get("materials", {})) == _canonical_sha256(right.get("materials", {}))
    same_solver = _canonical_sha256(left.get("solver", {})) == _canonical_sha256(right.get("solver", {}))
    same_geometry = left_scene_hash == right_scene_hash

    def map_surfaces(scenario: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]] | None:
        surfaces = scenario.get("radio_map", {}).get("surfaces", [])
        output = []
        for surface in surfaces:
            mesh = document.get("assets", {}).get("meshes", {}).get(surface.get("mesh_ref"))
            if mesh is None or len(surface.get("values_db", [])) != len(mesh.get("faces", [])):
                return None
            output.append({"surface": surface, "mesh": mesh})
        return output or None

    left_maps, right_maps = map_surfaces(left, reference), map_surfaces(right, comparison)
    same_surface = False
    map_delta = None
    map_reason = "A measurement surface is missing or its values do not match its faces."
    if left_maps and right_maps and len(left_maps) == len(right_maps):
        same_surface = all(
            first["surface"]["name"] == second["surface"]["name"] and
            first["mesh"].get("vertices_m") == second["mesh"].get("vertices_m") and
            first["mesh"].get("faces") == second["mesh"].get("faces") and
            len(first["surface"]["values_db"]) == len(second["surface"]["values_db"])
            for first, second in zip(left_maps, right_maps)
        )
        if same_surface:
            deltas = []
            for first, second in zip(left_maps, right_maps):
                deltas.extend(float(b) - float(a) for a, b in zip(
                    first["surface"]["values_db"], second["surface"]["values_db"])
                    if a is not None and b is not None and math.isfinite(float(a)) and math.isfinite(float(b)))
            map_delta = {
                "valid_cells": len(deltas),
                "mean_delta_db": (sum(deltas) / len(deltas)) if deltas else None,
                "mean_absolute_delta_db": (sum(abs(value) for value in deltas) / len(deltas)) if deltas else None,
                "minimum_delta_db": min(deltas) if deltas else None,
                "maximum_delta_db": max(deltas) if deltas else None,
                "rms_delta_db": (math.sqrt(sum(value * value for value in deltas) / len(deltas))) if deltas else None,
            }
            map_reason = "Every measurement surface has matching triangle coordinates, winding, and ordering; only jointly valid cells were compared."
        else:
            map_reason = "Measurement surface coordinates, triangle correspondence, or ordering differ."

    right_metrics = {row["receiver"]: row for row in right.get("receiver_metrics", [])}
    link_deltas = []
    for metric in left.get("receiver_metrics", []):
        other = right_metrics.get(metric.get("receiver"))
        if other is None:
            continue
        first_link, second_link = metric.get("link_metrics") or {}, other.get("link_metrics") or {}
        def delta(key: str) -> float | None:
            first, second = first_link.get(key), second_link.get(key)
            return float(second) - float(first) if first is not None and second is not None else None
        link_deltas.append({
            "receiver": metric["receiver"],
            "path_count_reference": metric.get("path_count"),
            "path_count_comparison": other.get("path_count"),
            "strongest_path_delay_delta_ns": (
                float(other["strongest_path_delay_ns"]) - float(metric["strongest_path_delay_ns"])
                if metric.get("strongest_path_delay_ns") is not None and
                other.get("strongest_path_delay_ns") is not None else None
            ),
            "coherent_gain_delta_db": delta("gain_db_coherent"),
            "incoherent_gain_delta_db": delta("gain_db_incoherent"),
            "delay_spread_delta_ns": delta("delay_spread_ns"),
        })

    compatible = same_frequency and same_geometry and same_transmitter and same_receivers
    return {
        "reference": _summary_from_document(str(reference_id), reference),
        "comparison": _summary_from_document(str(comparison_id), comparison),
        "transmitter": transmitter,
        "compatibility": {
            "status": "compatible" if compatible else "metadata_mismatch",
            "same_frequency": same_frequency,
            "same_scene_geometry": same_geometry,
            "same_transmitter_configuration": same_transmitter,
            "same_receiver_configuration": same_receivers,
            "same_material_definitions": same_materials,
            "same_solver_settings": same_solver,
            "reference_geometry_sha256": left_scene_hash,
            "comparison_geometry_sha256": right_scene_hash,
        },
        "radio_map": {
            "compatible": bool(same_surface and same_frequency and same_transmitter),
            "reason": map_reason,
            "delta_statistics": map_delta,
        },
        "link_deltas": link_deltas,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py import-housionna")
    parser.add_argument("run_folder", help="Path to one completed HOUSIONNA run folder")
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    try:
        output_file = import_run(args.run_folder, project_root)
        assert isinstance(output_file, Path)
        from digital_twin_data import build_viewer_scene

        viewer_file = build_viewer_scene(project_root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"HOUSIONNA import failed: {error}", file=sys.stderr)
        return 2
    print(f"Imported HOUSIONNA run into {output_file}")
    print(f"Updated Three.js viewer scene: {viewer_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
