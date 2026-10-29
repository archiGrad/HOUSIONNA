"""Small, local-only job manager for on-demand vertical-farm Sionna runs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import platform
import re
import subprocess
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from demos.cea_demo import _run_scenario
from server.digital_twin_data import SCENARIO_LABELS, _entry, _rx_metrics
from demos.poc import _load_rt
from demos.vertical_farm_geometry import (
    generate_vertical_farm_geometry,
    load_vertical_farm_config,
    vertical_farm_scenario_config,
)


MAP_QUALITY = {
    "low": {"cell_size_m": [0.30, 0.30], "samples_per_transmitter": 4500},
    "medium": {"cell_size_m": [0.15, 0.15], "samples_per_transmitter": 18000},
    "high": {"cell_size_m": [0.10, 0.10], "samples_per_transmitter": 40000},
}
SCENARIO_DENSITY = {
    "empty": "farm_empty", "none": "farm_empty",
    "low": "farm_proxy", "sparse": "farm_proxy", "medium": "farm_proxy", "standard": "farm_proxy", "proxy": "farm_proxy",
    "high": "farm_dense", "dense": "farm_dense",
}
MAX_HISTORY = 50


class LiveApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveApiError(400, f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise LiveApiError(400, f"{field} must be a finite number")
    return number


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


class LiveSimulationManager:
    """Serializes Sionna runs, persists results, and reuses exact successful runs."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.output_root = self.project_root / "outputs" / "live"
        self.history_file = self.output_root / "history.json"
        self.lock = threading.RLock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active_run_id: str | None = None
        self.history = self._read_history()
        self.rt = None
        self.mi = None
        self.backend = self._detect_backend()

    def _read_history(self) -> list[dict[str, Any]]:
        try:
            rows = json.loads(self.history_file.read_text(encoding="utf-8"))
            return [row for row in rows if isinstance(row, dict) and self._valid_id(row.get("run_id"))]
        except (OSError, json.JSONDecodeError):
            return []

    @staticmethod
    def _valid_id(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 32 and all(char in "0123456789abcdef" for char in value)

    def _detect_backend(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "available": False,
            "sionna_version": _package_version("sionna-rt"),
            "mitsuba_variant": "unknown",
            "backend": "Unavailable",
            "gpu_name": None,
            "host": platform.platform(),
            "error": None,
        }
        try:
            self.rt, self.mi = _load_rt()
            variant = str(self.mi.variant() or "unknown")
            is_cuda = "cuda" in variant.lower()
            info.update({
                "available": True,
                "sionna_version": _package_version("sionna-rt"),
                "mitsuba_variant": variant,
                "backend": f"CUDA ({variant})" if is_cuda else ("LLVM CPU" if "llvm" in variant.lower() else variant),
            })
            if is_cuda:
                try:
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                        capture_output=True, text=True, timeout=2, check=False,
                    )
                    if result.returncode == 0:
                        info["gpu_name"] = result.stdout.splitlines()[0].strip() or None
                except (OSError, subprocess.TimeoutExpired):
                    pass
        except Exception as error:  # Keep the 2D viewer available if RT cannot initialize.
            info["error"] = f"{type(error).__name__}: Sionna backend initialization failed; see the viewer terminal for details."
            print(f"On-demand Sionna API unavailable: {type(error).__name__}: {error}")
        return info

    def _normalize(self, payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(payload, dict):
            raise LiveApiError(400, "Request body must be a JSON object")
        allowed = {"scenario", "frequency_hz", "tx", "receiver_set", "plant_proxy", "solver", "map_quality"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise LiveApiError(400, f"Unsupported request field(s): {', '.join(unknown)}")

        scenario_value = payload.get("scenario", "farm_proxy")
        plant_proxy = payload.get("plant_proxy", {})
        if not isinstance(plant_proxy, dict):
            raise LiveApiError(400, "plant_proxy must be an object")
        if set(plant_proxy) - {"density"}:
            raise LiveApiError(400, "plant_proxy accepts density only")
        if scenario_value == "vertical_farm":
            density = plant_proxy.get("density", "proxy")
            if not isinstance(density, str):
                raise LiveApiError(400, "plant_proxy.density must be a string preset")
            density = density.lower()
            if density not in SCENARIO_DENSITY:
                raise LiveApiError(400, "plant_proxy.density must map to an existing empty, proxy, or dense farm preset")
            scenario = SCENARIO_DENSITY[density]
        else:
            scenario = scenario_value
        if scenario not in SCENARIO_DENSITY.values():
            raise LiveApiError(400, "scenario must be farm_empty, farm_proxy, farm_dense, or vertical_farm")

        base = load_vertical_farm_config()
        cfg = vertical_farm_scenario_config(base, scenario)
        frequency = _finite_number(payload.get("frequency_hz", cfg["frequency_hz"]), "frequency_hz")
        if frequency < 100_000_000 or frequency > 6_000_000_000:
            raise LiveApiError(400, "frequency_hz must be between 100 MHz and 6 GHz")

        tx_payload = payload.get("tx", {})
        if not isinstance(tx_payload, dict):
            raise LiveApiError(400, "tx must be an object")
        if set(tx_payload) - {"position", "position_m", "orientation", "orientation_rad"}:
            raise LiveApiError(400, "tx accepts position/position_m and orientation/orientation_rad only")
        raw_position = tx_payload.get("position_m", tx_payload.get("position", cfg["transmitter"]["position_m"]))
        raw_orientation = tx_payload.get("orientation_rad", tx_payload.get("orientation", cfg["transmitter"]["orientation_rad"]))
        if not isinstance(raw_position, list) or len(raw_position) != 3:
            raise LiveApiError(400, "tx.position must contain exactly [x, y, z] in metres")
        if not isinstance(raw_orientation, list) or len(raw_orientation) != 3:
            raise LiveApiError(400, "tx.orientation must contain exactly [yaw about Z, pitch about Y, roll about X] in radians")
        position = [_finite_number(value, f"tx.position[{index}]") for index, value in enumerate(raw_position)]
        orientation = [_finite_number(value, f"tx.orientation[{index}]") for index, value in enumerate(raw_orientation)]
        width = float(cfg["environment"]["width_m"])
        depth = float(cfg["environment"]["depth_m"])
        height = float(cfg["environment"]["height_m"])
        limits = ((-0.20, width + 0.20), (-0.55, depth + 0.10), (0.05, height))
        for index, (value, (minimum, maximum)) in enumerate(zip(position, limits)):
            if not minimum <= value <= maximum:
                axis = "xyz"[index]
                raise LiveApiError(400, f"TX {axis} is outside allowed bounds [{minimum:.2f}, {maximum:.2f}] m")
        if any(abs(value) > 2 * math.pi for value in orientation):
            raise LiveApiError(400, "TX orientation values must be within -2π to 2π radians")

        receiver_set = payload.get("receiver_set", "default")
        if receiver_set != "default":
            raise LiveApiError(400, "Only the configured default receiver set is supported")

        solver = payload.get("solver", {})
        if not isinstance(solver, dict) or set(solver) - {"max_depth", "specular_reflection", "refraction"}:
            raise LiveApiError(400, "solver accepts max_depth, specular_reflection, and refraction only")
        depth_value = solver.get("max_depth", cfg["path_solver"]["max_depth"])
        if isinstance(depth_value, bool) or not isinstance(depth_value, int) or not 1 <= depth_value <= 5:
            raise LiveApiError(400, "solver.max_depth must be an integer from 1 to 5")
        specular = solver.get("specular_reflection", cfg["path_solver"]["specular_reflection"])
        refraction = solver.get("refraction", cfg["path_solver"]["refraction"])
        if not isinstance(specular, bool) or not isinstance(refraction, bool):
            raise LiveApiError(400, "solver.specular_reflection and solver.refraction must be booleans")

        quality = payload.get("map_quality", "medium")
        if not isinstance(quality, str) or quality.lower() not in MAP_QUALITY:
            raise LiveApiError(400, "map_quality must be low, medium, or high")
        quality = quality.lower()
        normalized = {
            "scenario": scenario,
            "frequency_hz": int(round(frequency)),
            "tx": {"position_m": [round(value, 6) for value in position],
                   "orientation_rad": [round(value, 8) for value in orientation]},
            "receiver_set": receiver_set,
            "solver": {"max_depth": depth_value,
                       "specular_reflection": specular, "refraction": refraction},
            "map_quality": quality,
        }
        cfg["frequency_hz"] = float(normalized["frequency_hz"])
        cfg["transmitter"]["position_m"] = normalized["tx"]["position_m"]
        cfg["transmitter"]["orientation_rad"] = normalized["tx"]["orientation_rad"]
        cfg["path_solver"].update(normalized["solver"])
        cfg["radio_map"].update(normalized["solver"])
        cfg["radio_map"].update(MAP_QUALITY[quality])
        cfg["radio_map"]["planes"] = []  # live runs only need the plane shown in the viewer
        geometry_file = self.project_root / "config" / "vertical_farm.yaml"
        geometry_hash = hashlib.sha256(geometry_file.read_bytes()).hexdigest()
        digest_input = {"api_schema": 1, "scene_config_sha256": geometry_hash, **normalized}
        config_hash = hashlib.sha256(json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        normalized["config_hash"] = config_hash
        return normalized, cfg

    def _find_cached(self, config_hash: str) -> dict[str, Any] | None:
        for row in self.history:
            if row.get("status") != "complete" or row.get("config_hash") != config_hash:
                continue
            run_dir = self.output_root / row["run_id"]
            result_file = run_dir / "result.json"
            try:
                result = json.loads(result_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            return {"run_id": row["run_id"], "result": result, "history": row}
        return None

    def start(self, payload: Any) -> tuple[int, dict[str, Any]]:
        normalized, cfg = self._normalize(payload)
        config_hash = normalized["config_hash"]
        with self.lock:
            cached = self._find_cached(config_hash)
            if cached:
                return 200, {
                    "run_id": cached["run_id"], "status": "complete", "cached": True,
                    "duration_seconds": cached["history"].get("duration_seconds"),
                    "result": cached["result"],
                }
            if self.active_run_id is not None:
                raise LiveApiError(409, "A Sionna simulation is already running")
            if not self.backend["available"]:
                raise LiveApiError(503, f"Sionna backend is unavailable: {self.backend['error'] or 'not initialized'}")
            run_id = uuid.uuid4().hex
            job = {
                "run_id": run_id, "status": "running", "started_monotonic": time.monotonic(),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "config": normalized, "config_hash": config_hash,
            }
            self.jobs[run_id] = job
            self.active_run_id = run_id
            thread = threading.Thread(target=self._run_job, args=(run_id, copy.deepcopy(cfg), normalized), daemon=True)
            thread.start()
            return 202, {"run_id": run_id, "status": "running", "cached": False}

    def _tx_inside_rf_geometry(self, geometry: dict[str, Any], position: list[float]) -> list[str]:
        x, y, z = position
        hits = []
        for item in geometry["objects"]:
            if item["category"] == "floor":
                continue
            bounds = item["bounds_m"]
            if (bounds["x_min"] <= x <= bounds["x_max"] and
                    bounds["y_min"] <= y <= bounds["y_max"] and
                    bounds["z_min"] <= z <= bounds["z_max"]):
                hits.append(item["id"])
        return hits

    def _run_job(self, run_id: str, cfg: dict[str, Any], normalized: dict[str, Any]) -> None:
        run_dir = self.output_root / run_id
        started_at = datetime.now(timezone.utc).isoformat()
        config_to_save = {"request": normalized, "expanded_sionna_config": cfg}
        base_metadata = {
            "run_id": run_id,
            "config_hash": normalized["config_hash"],
            "timestamp_utc": started_at,
            "software": {"sionna_rt": self.backend["sionna_version"], "api_schema": 1},
            "backend": self.backend,
            "scene_version": "config/vertical_farm.yaml",
            "frequency_hz": normalized["frequency_hz"],
            "transmitter": cfg["transmitter"],
            "receivers": cfg["receivers"],
            "materials": cfg["materials"],
            "solver": {"path_solver": cfg["path_solver"], "radio_map_solver": cfg["radio_map"]},
            "status": "running",
        }
        metadata_file = run_dir / "metadata.json"
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            (run_dir / "config.json").write_text(json.dumps(config_to_save, indent=2, allow_nan=False), encoding="utf-8")
            metadata_file.write_text(json.dumps(base_metadata, indent=2, allow_nan=False), encoding="utf-8")
            geometry = generate_vertical_farm_geometry(cfg)
            result = _run_scenario(
                self.rt, self.mi, cfg, run_id, output_root=self.output_root,
                geometry_override=geometry,
            )
            viewer_data = result["viewer_data"]
            (run_dir / "radio_map.json").write_text(json.dumps({
                **viewer_data["radio_map"],
                "quantity": "path_gain",
                "display_values_are_db": True,
                "display_transform": "10*log10(max(path_gain, 1e-15)) dB; not RSS",
            }, allow_nan=False), encoding="utf-8")
            path_summary = json.loads((run_dir / "paths.json").read_text(encoding="utf-8"))
            metrics = _rx_metrics(path_summary["paths"], [rx["name"] for rx in cfg["receivers"]])
            entry = _entry(
                normalized["scenario"], cfg, geometry, viewer_data["radio_map"],
                path_summary["paths"], cfg["receivers"], metrics, None,
                cfg["material_status"],
                solver={"path_solver": cfg["path_solver"], "radio_map_solver": cfg["radio_map"]},
            )
            entry["label"] = f"On-demand · {SCENARIO_LABELS[normalized['scenario']]}"
            entry["run_metadata"] = {
                "run_id": run_id, "config_hash": normalized["config_hash"],
                "timestamp_utc": started_at, "cached": False,
            }
            entry["live_configuration"] = {key: normalized[key] for key in (
                "scenario", "frequency_hz", "tx", "solver", "map_quality", "receiver_set")}
            tx_collisions = self._tx_inside_rf_geometry(geometry, normalized["tx"]["position_m"])
            entry["tx_geometry_warning"] = tx_collisions
            duration = time.monotonic() - self.jobs[run_id]["started_monotonic"]
            public_metadata = {
                **base_metadata,
                "status": "complete",
                "duration_seconds": round(duration, 3),
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "valid_path_counts_by_receiver": path_summary["receivers"],
                "radio_map": result["map_metadata"],
                "tx_geometry_warning": tx_collisions,
            }
            metadata_file.write_text(json.dumps(public_metadata, indent=2, allow_nan=False), encoding="utf-8")
            (run_dir / "receiver_metrics.json").write_text(json.dumps(metrics, indent=2, allow_nan=False), encoding="utf-8")
            (run_dir / "result.json").write_text(json.dumps(entry, allow_nan=False), encoding="utf-8")
            history_row = {
                "run_id": run_id, "config_hash": normalized["config_hash"],
                "timestamp_utc": started_at, "duration_seconds": round(duration, 3),
                "status": "complete", "scenario": normalized["scenario"],
                "frequency_hz": normalized["frequency_hz"], "tx_position_m": normalized["tx"]["position_m"],
                "map_quality": normalized["map_quality"], "cached": False,
            }
            with self.lock:
                self._record_history(history_row)
                self.jobs[run_id].update({
                    "status": "complete", "duration_seconds": round(duration, 3),
                    "result": entry, "cached": False,
                })
        except Exception as error:
            traceback.print_exc()
            duration = time.monotonic() - self.jobs[run_id]["started_monotonic"]
            error_text = str(error).replace(str(self.project_root), "<project>")
            error_text = error_text.replace(str(self.project_root).replace("\\", "/"), "<project>")
            error_text = re.sub(r"(?i)\b[a-z]:\\[^\r\n\"']+", "<local-path>", error_text)
            public_error = f"{type(error).__name__}: {error_text}"
            try:
                failed_metadata = {**base_metadata, "status": "failed", "duration_seconds": round(duration, 3),
                                   "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                                   "error": public_error}
                metadata_file.write_text(json.dumps(failed_metadata, indent=2, allow_nan=False), encoding="utf-8")
            except Exception:
                traceback.print_exc()
            row = {
                "run_id": run_id, "config_hash": normalized["config_hash"],
                "timestamp_utc": started_at, "duration_seconds": round(duration, 3),
                "status": "failed", "scenario": normalized["scenario"],
                "frequency_hz": normalized["frequency_hz"], "tx_position_m": normalized["tx"]["position_m"],
                "error": public_error,
            }
            with self.lock:
                self._record_history(row)
                self.jobs[run_id].update({"status": "failed", "duration_seconds": round(duration, 3), "error": public_error})
        finally:
            with self.lock:
                if self.active_run_id == run_id:
                    self.active_run_id = None

    def _record_history(self, row: dict[str, Any]) -> None:
        self.history = [item for item in self.history if item.get("run_id") != row["run_id"]]
        self.history.insert(0, row)
        self.history = self.history[:MAX_HISTORY]
        self.output_root.mkdir(parents=True, exist_ok=True)
        temp = self.history_file.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.history, indent=2, allow_nan=False), encoding="utf-8")
        temp.replace(self.history_file)

    def _public_job(self, job: dict[str, Any], include_result: bool = True) -> dict[str, Any]:
        elapsed = time.monotonic() - job["started_monotonic"] if job["status"] == "running" else job.get("duration_seconds")
        public = {"run_id": job["run_id"], "status": job["status"], "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
                  "duration_seconds": job.get("duration_seconds"), "cached": bool(job.get("cached", False))}
        if job.get("error"):
            public["error"] = job["error"]
        if include_result and job.get("result") is not None:
            public["result"] = job["result"]
        return public

    def get_job(self, run_id: str) -> dict[str, Any] | None:
        if not self._valid_id(run_id):
            return None
        with self.lock:
            job = self.jobs.get(run_id)
            if job:
                return self._public_job(job)
        run_dir = self.output_root / run_id
        try:
            metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
            result = json.loads((run_dir / "result.json").read_text(encoding="utf-8")) if metadata.get("status") == "complete" else None
        except (OSError, json.JSONDecodeError):
            return None
        return {"run_id": run_id, "status": metadata.get("status", "unknown"),
                "duration_seconds": metadata.get("duration_seconds"), "elapsed_seconds": None,
                "cached": False, "result": result, "error": metadata.get("error")}

    def status(self) -> dict[str, Any]:
        with self.lock:
            active = self.jobs.get(self.active_run_id) if self.active_run_id else None
            return {
                "backend": self.backend,
                "active_run": self._public_job(active, include_result=False) if active else None,
                "recent_runs": copy.deepcopy(self.history[:10]),
            }

    def history_payload(self) -> dict[str, Any]:
        with self.lock:
            return {"runs": copy.deepcopy(self.history[:10])}
