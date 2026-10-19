"""Serve the local 3D digital twin viewer and its generated data."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Timer
from urllib.parse import parse_qs, urlsplit
import webbrowser
import mimetypes
from urllib.parse import unquote
import json
import re
import threading
import time
import gzip
from collections import OrderedDict
from contextlib import nullcontext
from typing import Any

from digital_twin_data import build_viewer_scene
from integrations.housionna_api import (
    HousionnaApiError,
    HousionnaImportManager,
    api_compare,
    api_import,
    api_imports,
    api_runs,
)
from live_simulation import LiveApiError, LiveSimulationManager
from integrations.housionna_simulation import (
    HousionnaLiveSimulationManager,
    HousionnaSimulationApiError,
)


class DashboardHandler(BaseHTTPRequestHandler):
    project_root = Path.cwd()
    routes: dict[str, Path] = {}
    digital_twin_root: Path | None = None
    live_simulations: LiveSimulationManager | None = None
    housionna_imports: HousionnaImportManager | None = None
    housionna_simulations: HousionnaLiveSimulationManager | None = None
    simulation_gate: Any = None
    compressed_assets = OrderedDict()
    compression_lock = threading.Lock()
    timing_lock = threading.Lock()

    def _dispatch_timed(self, method):
        self.request_started = time.perf_counter()
        try:
            method()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # A refresh or browser timeout closes its socket; it does not fail a worker.
            pass
        finally:
            if self.path.startswith('/api/housionna/'):
                path=self.project_root/'outputs/performance_refinement/http_timings.jsonl'
                path.parent.mkdir(parents=True,exist_ok=True)
                record={'route':urlsplit(self.path).path,'seconds':round(time.perf_counter()-self.request_started,6),'method':self.command}
                with self.timing_lock,path.open('a',encoding='utf-8') as handle:
                    handle.write(json.dumps(record)+'\n')

    def do_GET(self):
        self._dispatch_timed(self._get)

    def do_POST(self):
        self._dispatch_timed(self._post)

    def _send_json(self, status: int, value: dict):
        started = time.perf_counter()
        body = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        original_size = len(body)
        compressed = len(body) > 4096 and "gzip" in self.headers.get("Accept-Encoding", "")
        if compressed:
            body = gzip.compress(body, compresslevel=3)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("X-Uncompressed-Bytes", str(original_size))
        self.send_header("Server-Timing", f"serialize;dur={(time.perf_counter()-started)*1000:.3f},backend;dur={(time.perf_counter()-getattr(self,'request_started',started))*1000:.3f}")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def _get(self):
        parsed = urlsplit(self.path)
        route = parsed.path
        if route == "/api/housionna/simulations/active" and self.housionna_simulations:
            self._send_json(200, {"job": self.housionna_simulations.active()})
            return
        diagnostic = re.fullmatch(r"/api/housionna/simulations/([0-9a-f]{32})/diagnostics", route)
        if diagnostic and self.housionna_simulations:
            job_id = diagnostic.group(1)
            folder = self.project_root / "outputs/live/.housionna-jobs" / job_id
            document = {"job_id": job_id, "status": self.housionna_simulations.status(job_id)}
            for filename in ("worker.log", "traceback.txt"):
                try:
                    text = (folder / filename).read_text(encoding="utf-8", errors="replace")[-8000:]
                    document[filename] = re.sub(r"(?i)\b[a-z]:\\[^\r\n\"']+", "<local path>", text)
                except OSError:
                    pass
            self._send_json(200 if document["status"] else 404, document)
            return
        if route == "/api/status" and self.live_simulations:
            self._send_json(200, self.live_simulations.status())
            return
        if route == "/api/history" and self.live_simulations:
            self._send_json(200, self.live_simulations.history_payload())
            return
        if route == "/api/housionna/runs" and self.housionna_imports:
            try:
                self._send_json(200, api_runs(self.project_root))
            except (OSError, ValueError) as error:
                self._send_json(500, {"error": f"HOUSIONNA run discovery failed: {type(error).__name__}"})
            return
        if route == "/api/housionna/imports" and self.housionna_imports:
            self._send_json(200, api_imports(self.project_root))
            return
        if route == "/api/housionna/simulations/latest" and self.housionna_simulations:
            query = parse_qs(parsed.query, keep_blank_values=True)
            if set(query) != {"source_run_id", "import_id", "transmitter"} or any(len(values) != 1 for values in query.values()):
                self._send_json(400, {"error": "Latest-result lookup requires source_run_id, import_id, and transmitter"})
                return
            source_run_id, import_id, transmitter = (query[key][0] for key in ("source_run_id", "import_id", "transmitter"))
            if (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", source_run_id) is None or ".." in source_run_id or
                    re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", import_id) is None or ".." in import_id or
                    re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", transmitter) is None):
                self._send_json(400, {"error": "Latest-result lookup contains an invalid scene or device identifier"})
                return
            self._send_json(200, self.housionna_simulations.latest(source_run_id, import_id, transmitter))
            return
        match = re.fullmatch(r"/api/housionna/imports/([^/]+)", route)
        if match and self.housionna_imports:
            try:
                self._send_json(200, api_import(self.project_root, unquote(match.group(1))))
            except FileNotFoundError:
                self._send_json(404, {"error": "Imported HOUSIONNA run was not found"})
            except (ValueError, OSError) as error:
                self._send_json(400, {"error": str(error)[:360]})
            return
        match = re.fullmatch(r"/api/housionna/jobs/([0-9a-f]{32})", route)
        if match and self.housionna_imports:
            job = self.housionna_imports.get(match.group(1))
            self._send_json(200 if job else 404, job or {"error": "Import job was not found"})
            return
        match = re.fullmatch(r"/api/simulation/([0-9a-f]{32})", route)
        if match and self.live_simulations:
            job = self.live_simulations.get_job(match.group(1))
            if job is None:
                self._send_json(404, {"error": "Simulation run was not found"})
            else:
                self._send_json(200, job)
            return
        match = re.fullmatch(r"/api/housionna/simulations/([0-9a-f]{32})(/status)?", route)
        if match and self.housionna_simulations:
            job_id = match.group(1)
            job = (self.housionna_simulations.status(job_id) if match.group(2)
                   else self.housionna_simulations.result(job_id))
            self._send_json(200 if job else 404, job or {"error": "HOUSIONNA simulation was not found"})
            return
        if route == "/" and self.digital_twin_root and (self.digital_twin_root / "index.html").is_file():
            # The 3D twin is the only view.
            self.send_response(302)
            self.send_header("Location", "/digital-twin/")
            self.end_headers()
            return
        target = self.routes.get(route)
        if target is None and route.startswith("/digital-twin/") and self.digital_twin_root:
            relative = unquote(route.removeprefix("/digital-twin/")).strip("/")
            requested = (self.digital_twin_root / relative).resolve()
            try:
                requested.relative_to(self.digital_twin_root.resolve())
            except ValueError:
                self.send_error(404, "Not found")
                return
            target = requested
        if target is None or not target.is_file():
            self.send_error(404, "Not found")
            return
        body = target.read_bytes()
        guessed, _ = mimetypes.guess_type(target.name)
        content_type = f"{guessed or 'application/octet-stream'}; charset=utf-8" if target.suffix in {".html", ".js", ".css", ".json", ".svg", ".txt"} else (guessed or "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if len(body) > 4096 and target.suffix in {".json", ".js", ".css", ".html"} and "gzip" in self.headers.get("Accept-Encoding", ""):
            stat = target.stat()
            key = (str(target), stat.st_size, stat.st_mtime_ns)
            with self.compression_lock:
                compressed = self.compressed_assets.pop(key, None)
                if compressed is None:
                    compressed = gzip.compress(body, compresslevel=3)
                self.compressed_assets[key] = compressed
                while len(self.compressed_assets) > 4:
                    self.compressed_assets.popitem(last=False)
            self.send_header("X-Uncompressed-Bytes", str(len(body)))
            body = compressed
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _post(self):
        route = urlsplit(self.path).path
        if route == "/api/housionna/client-timing":
            payload, error_response = self._read_json_body()
            if error_response:
                self._send_json(*error_response)
                return
            if (not isinstance(payload, dict) or not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("run_id", ""))) or
                    not isinstance(payload.get("timings_ms"), dict) or
                    any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 86_400_000
                        for value in payload["timings_ms"].values())):
                self._send_json(400, {"error": "Invalid client timing record"})
                return
            path = self.project_root / "outputs/performance_refinement/client_timings.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with self.timing_lock, path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, allow_nan=False) + "\n")
            self._send_json(200, {"saved": True})
            return
        if route == "/api/housionna/import-latest" and self.housionna_imports:
            try:
                job = self.housionna_imports.start()
                self._send_json(202 if job["status"] == "running" else 200, job)
            except HousionnaApiError as error:
                self._send_json(error.status, {"error": str(error)})
            return
        if route == "/api/housionna/import" and self.housionna_imports:
            payload, error_response = self._read_json_body()
            if error_response:
                self._send_json(*error_response)
                return
            if not isinstance(payload, dict) or set(payload) != {"run_id"}:
                self._send_json(400, {"error": "Request body must contain only run_id"})
                return
            try:
                job = self.housionna_imports.start(payload["run_id"])
                self._send_json(202, job)
            except HousionnaApiError as error:
                self._send_json(error.status, {"error": str(error)})
            return
        if route == "/api/housionna/compare" and self.housionna_imports:
            payload, error_response = self._read_json_body()
            if error_response:
                self._send_json(*error_response)
                return
            try:
                self._send_json(200, api_compare(self.project_root, payload))
            except HousionnaApiError as error:
                self._send_json(error.status, {"error": str(error)[:360]})
            return
        if route in {"/api/housionna/simulate", "/api/housionna/radio-map"} and self.housionna_simulations:
            payload, error_response = self._read_json_body()
            if error_response:
                self._send_json(*error_response)
                return
            try:
                with self.simulation_gate or nullcontext():
                    if self.live_simulations and self.live_simulations.active_run_id is not None:
                        raise HousionnaSimulationApiError(409, "A Sionna simulation is already running")
                    job = self.housionna_simulations.start(payload, map_job=route.endswith("radio-map"))
            except HousionnaSimulationApiError as error:
                self._send_json(error.status, {"error": str(error)})
                return
            except Exception as error:
                print(f"HOUSIONNA Sionna job request failed: {type(error).__name__}: {error}")
                self._send_json(500, {"error": "The Sionna job could not be started"})
                return
            self._send_json(200 if job.get("cache_hit") else 202, job)
            return
        if route != "/api/simulate" or not self.live_simulations:
            self._send_json(404, {"error": "Not found"})
            return
        payload, error_response = self._read_json_body()
        if error_response:
            self._send_json(*error_response)
            return
        try:
            with self.simulation_gate or nullcontext():
                if self.housionna_simulations and self.housionna_simulations.active_job_id is not None:
                    self._send_json(409, {"error": "A HOUSIONNA Sionna simulation is already running"})
                    return
                status, result = self.live_simulations.start(payload)
        except LiveApiError as error:
            self._send_json(error.status, {"error": str(error)})
            return
        except Exception as error:
            print(f"Live simulation request failed: {type(error).__name__}: {error}")
            self._send_json(500, {"error": "The simulation request could not be started"})
            return
        self._send_json(status, result)

    def _read_json_body(self, *, required: bool = True):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, (400, {"error": "Content-Length must be an integer"})
        if content_length <= 0 and not required:
            return {}, None
        if content_length <= 0:
            return None, (400, {"error": "A JSON request body is required"})
        if content_length > 64 * 1024:
            return None, (413, {"error": "Request body must be 64 KiB or smaller"})
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            return payload, None
        except UnicodeDecodeError:
            return None, (400, {"error": "Request body must be UTF-8 JSON"})
        except json.JSONDecodeError as error:
            return None, (400, {"error": f"Malformed JSON: {error.msg}"})

    def log_message(self, format, *args):
        return


def serve(project_root: Path, *, open_browser: bool = True, port: int | None = None) -> None:
    project_root = Path(project_root).resolve()
    digital_twin_root = project_root / "viewer" / "digital-twin-dist"
    try:
        build_viewer_scene(project_root)
    except FileNotFoundError as error:
        # The 3D view still opens if the optional study outputs are missing; it shows the remedy in the page.
        print(f"Digital Twin data is not ready yet: {error}")
    routes = {
        "/digital-twin": digital_twin_root / "index.html",
        "/digital-twin/": digital_twin_root / "index.html",
        "/outputs/digital_twin/viewer_scene.json": project_root / "outputs" / "digital_twin" / "viewer_scene.json",
    }

    if not (digital_twin_root / "index.html").is_file():
        raise FileNotFoundError(
            "The Three.js bundle is missing. Build it with "
            "'npm.cmd --prefix frontend install' and 'npm.cmd --prefix frontend run build'."
        )
    live_simulations = LiveSimulationManager(project_root)
    housionna_imports = HousionnaImportManager(project_root)
    housionna_simulations = HousionnaLiveSimulationManager(project_root)
    handler = type("LocalDashboardHandler", (DashboardHandler,), {
        "routes": routes, "digital_twin_root": digital_twin_root,
        "live_simulations": live_simulations, "housionna_imports": housionna_imports,
        "housionna_simulations": housionna_simulations,
        "simulation_gate": threading.Lock(),
        "project_root": project_root,
    })
    server = None
    for candidate_port in ([port] if port is not None else range(8765, 8785)):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate_port), handler)
            break
        except OSError:
            continue
    if server is None:
        raise OSError("Could not find an available local port between 8765 and 8784")

    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Opening the local digital twin viewer at {url}")
    print("Leave this terminal running while you use the page. Press Ctrl+C to stop it.")
    if open_browser:
        Timer(0.8, webbrowser.open_new_tab, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLocal viewer stopped.")
    finally:
        server.server_close()
