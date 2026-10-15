"""Timing, atomic job records and bounded read-only import reuse."""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import ctypes
import ctypes.util
import json
import os
import platform
import time
import tempfile


def atomic_json(path: Path, document: dict, *, compact: bool = False) -> None:
    # Windows readers/antivirus can briefly hold a handle without delete sharing.
    # Keep the previous complete record until replacement succeeds; never truncate it.
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                    prefix=path.name+'-',suffix='.tmp',delete=False) as handle:
        temporary=Path(handle.name)
        json.dump(document,handle,allow_nan=False,indent=None if compact else 2,
                  separators=(',',':') if compact else None)
    try:
        for attempt in range(10):
            try:
                os.replace(temporary,path)
                break
            except PermissionError:
                if attempt==9:raise
                time.sleep(min(.01*2**attempt,.3))
    finally:
        try:temporary.unlink(missing_ok=True)
        except OSError:pass


class Timings:
    def __init__(self):
        self.started = time.perf_counter()
        self.seconds: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.seconds[name] = round(time.perf_counter() - start, 6)

    def payload(self) -> dict:
        return {"stages_seconds": self.seconds,
                "function_total_seconds": round(time.perf_counter() - self.started, 6),
                "timing_note": "Scene XML, its referenced PLY meshes and materials are loaded together by rt.load_scene; they are not reported as separate exclusive stages."}


class ImportCache:
    """Private immutable-by-convention documents; at most two imports in RAM."""
    def __init__(self, max_entries=2):
        self.max_entries = max_entries
        self.entries = OrderedDict()

    def read(self, root: Path, import_id: str, reader):
        path = root / "outputs/integrations/housionna" / import_id / "viewer_import.json"
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        entry = self.entries.pop(import_id, None)
        if entry is None or entry[0] != signature:
            entry = (signature, reader(root, import_id))
        self.entries[import_id] = entry
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)
        return entry[1]


def runtime_identity(root: Path) -> dict:
    packages = {}
    for name in ("sionna-rt", "mitsuba", "drjit", "numpy"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "unavailable"
    cuda_version = None
    try:
        library = ctypes.WinDLL("nvcuda.dll") if os.name == "nt" else ctypes.CDLL(ctypes.util.find_library("cuda") or "libcuda.so.1")
        value = ctypes.c_int()
        if library.cuDriverGetVersion(ctypes.byref(value)) == 0:
            cuda_version = value.value
    except (OSError, AttributeError):
        pass
    llvm = Path(os.environ.get("DRJIT_LIBLLVM_PATH") or root / ".runtime/llvm-18.1.8/bin/LLVM-C.dll")
    stat = llvm.stat() if llvm.is_file() else None
    return {"engine_contract": "housionna-live-v3", "packages": packages,
            "backend_preference": os.environ.get("SIONNA_RT_BACKEND", "auto").lower(),
            "system": platform.system(), "machine": platform.machine(),
            "cuda_driver_version": cuda_version,
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "llvm_library": {"name": llvm.name, "size": stat.st_size if stat else None,
                             "mtime_ns": stat.st_mtime_ns if stat else None}}
