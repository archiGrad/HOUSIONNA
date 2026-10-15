"""Local HTTP orchestration for the HOUSIONNA file adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from pathlib import Path
import threading
import time
import uuid
from typing import Any

from digital_twin_data import build_viewer_scene
from integrations.housionna import (
    compare_imports,
    configured_runs_directory,
    discover_runs,
    import_run,
    list_imports,
    read_import,
)


class HousionnaApiError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class HousionnaImportManager:
    """Runs imports off the HTTP request thread and exposes real stage updates."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active_job_id: str | None = None

    @staticmethod
    def _valid_job_id(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None

    @staticmethod
    def _safe_error(error: Exception, roots: list[Path]) -> str:
        message = str(error)
        for root in roots:
            message = message.replace(str(root), "<configured directory>")
            message = message.replace(str(root).replace("\\", "/"), "<configured directory>")
        message = re.sub(r"(?i)\b[a-z]:\\[^\r\n\"']+", "<local path>", message)
        return f"{type(error).__name__}: {message[:360]}"

    def start(self, run_id: Any = None) -> dict[str, Any]:
        if run_id is not None and (not isinstance(run_id, str) or not run_id or
                                   re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id) is None or
                                   ".." in run_id):
            raise HousionnaApiError(400, "run_id must be a discovered HOUSIONNA folder name")
        with self.lock:
            if self.active_job_id:
                active = self.jobs.get(self.active_job_id)
                if active and active["status"] == "running":
                    if active.get("requested_run_id") == run_id:
                        return self._public(active, reused_active=True)
                    raise HousionnaApiError(409, "A different HOUSIONNA import is already running")
            job_id = uuid.uuid4().hex
            job = {
                "job_id": job_id,
                "status": "running",
                "stage": "discovering_runs",
                "message": "Discovering completed HOUSIONNA exports",
                "requested_run_id": run_id,
                "run_id": None,
                "started_monotonic": time.monotonic(),
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "import_id": None,
                "error": None,
            }
            self.jobs[job_id] = job
            self.active_job_id = job_id
            threading.Thread(target=self._run, args=(job_id,), daemon=True,
                             name=f"housionna-import-{job_id[:8]}").start()
            return self._public(job)

    def _set_stage(self, job_id: str, stage: str, message: str | None = None) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job and job["status"] == "running":
                job["stage"] = stage
                job["message"] = message or stage.replace("_", " ").capitalize()

    def _run(self, job_id: str) -> None:
        runs_root = self.project_root
        try:
            runs_root = configured_runs_directory(self.project_root)
            candidates = discover_runs(self.project_root)
            requested = self.jobs[job_id]["requested_run_id"]
            if requested is None:
                selected = next((row for row in candidates if row["status"] == "valid"), None)
                if selected is None:
                    raise HousionnaApiError(404, "No valid completed HOUSIONNA run was found in the configured directory")
                requested = selected["run_id"]
            else:
                selected = next((row for row in candidates
                                 if row["run_id"] == requested and row["status"] == "valid"), None)
                if selected is None:
                    raise HousionnaApiError(404, "The selected HOUSIONNA run is incomplete or invalid")
            run_folder = (runs_root / requested).resolve()
            try:
                run_folder.relative_to(runs_root.resolve())
            except ValueError as error:
                raise HousionnaApiError(400, "The selected run is outside the configured directory") from error
            if run_folder.is_symlink() or not run_folder.is_dir():
                raise HousionnaApiError(404, "The selected HOUSIONNA run is unavailable")
            with self.lock:
                self.jobs[job_id]["run_id"] = requested
            self._set_stage(job_id, "validating_export", "Validating the selected export")

            def progress(stage: str) -> None:
                messages = {
                    "validating_export": "Validating export and checking its content hash",
                    "importing_geometry": "Importing exported scene meshes",
                    "processing_radio_map": "Processing measurement triangles and radio-map values",
                    "normalizing_results": "Normalizing transmitter, receiver, path, and link results",
                    "saving_viewer_data": "Saving the normalized viewer scene",
                    "ready_cached": "Source content matches a validated cached import",
                }
                self._set_stage(job_id, stage, messages.get(stage))

            output_file = import_run(run_folder, self.project_root, progress_callback=progress)
            if not isinstance(output_file, Path):
                raise RuntimeError("Adapter did not produce a normalized import file")
            import_id = output_file.parent.name
            self._set_stage(job_id, "updating_viewer", "Updating the existing digital-twin scene data")
            build_viewer_scene(self.project_root)
            document = read_import(self.project_root, import_id)
            run_metadata = document.get("run_metadata", {})
            with self.lock:
                job = self.jobs[job_id]
                job.update({
                    "status": "complete", "stage": "ready", "message": "HOUSIONNA run is ready in the viewer",
                    "import_id": import_id, "run_metadata": run_metadata,
                    "duration_seconds": round(time.monotonic() - job["started_monotonic"], 3),
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as error:
            safe = self._safe_error(error, [runs_root, self.project_root])
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    job.update({
                        "status": "failed", "stage": "import_failed", "message": "HOUSIONNA import failed",
                        "error": safe,
                        "duration_seconds": round(time.monotonic() - job["started_monotonic"], 3),
                        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                    })
        finally:
            with self.lock:
                if self.active_job_id == job_id:
                    self.active_job_id = None

    def _public(self, job: dict[str, Any], reused_active: bool = False) -> dict[str, Any]:
        result = {key: value for key, value in job.items()
                  if key not in {"started_monotonic", "requested_run_id"}}
        if job["status"] == "running":
            result["elapsed_seconds"] = round(time.monotonic() - job["started_monotonic"], 1)
        if reused_active:
            result["reused_active"] = True
        return result

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not self._valid_job_id(job_id):
            return None
        with self.lock:
            job = self.jobs.get(job_id)
            return self._public(job) if job else None


def api_runs(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    runs_root = configured_runs_directory(root)
    return {
        "configured": runs_root.is_dir(),
        "runs": discover_runs(root),
    }


def api_imports(project_root: str | Path) -> dict[str, Any]:
    return {"imports": list_imports(project_root)}


def api_import(project_root: str | Path, import_id: str) -> dict[str, Any]:
    document = read_import(project_root, import_id)
    return _public_import(import_id, document)


def _public_import(import_id: str, document: dict[str, Any]) -> dict[str, Any]:
    from integrations.housionna import _summary_from_document
    row = _summary_from_document(import_id, document)
    row["source"] = document.get("provenance", {}).get("pipeline")
    row["adapter_version"] = document.get("provenance", {}).get("adapter_version")
    row["source_files"] = document.get("provenance", {}).get("source_files", [])
    row["scenario_order"] = document.get("scenario_order", [])
    row["settings"] = document.get("settings", {})
    return row


def api_compare(project_root: str | Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "reference_id", "comparison_id", "transmitter"
    }:
        raise HousionnaApiError(400, "Comparison requires reference_id, comparison_id, and transmitter")
    try:
        return compare_imports(project_root, payload["reference_id"],
                               payload["comparison_id"], payload["transmitter"])
    except FileNotFoundError as error:
        raise HousionnaApiError(404, str(error)) from error
    except (ValueError, KeyError, TypeError) as error:
        raise HousionnaApiError(400, str(error)) from error
