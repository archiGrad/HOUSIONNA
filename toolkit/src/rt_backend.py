"""Lightweight RT initialization without importing plotting libraries."""
from pathlib import Path
import ctypes
import os

ROOT=Path(__file__).resolve().parents[1]


def windows_cuda_driver_version():
    if os.name!='nt':return None
    try:
        value=ctypes.c_int()
        library=ctypes.WinDLL('nvcuda.dll')
        return value.value if library.cuDriverGetVersion(ctypes.byref(value))==0 else None
    except (OSError,AttributeError):return None


def load_rt():
    requested=os.environ.get('SIONNA_RT_BACKEND','auto').lower()
    if requested not in {'auto','llvm','cuda'}:
        raise ValueError('SIONNA_RT_BACKEND must be auto, llvm, or cuda')
    configured=os.environ.get('DRJIT_LIBLLVM_PATH')
    llvm=Path(configured) if configured else ROOT/'.runtime/llvm-18.1.8/bin/LLVM-C.dll' if os.name=='nt' else None
    if llvm is not None and requested!='cuda':
        if llvm.is_file():os.environ['DRJIT_LIBLLVM_PATH']=str(llvm.resolve())
        elif requested=='auto' and (windows_cuda_driver_version() or 0)>=12020:requested='cuda'  # no local LLVM: use the GPU
        else:raise FileNotFoundError(f'The configured Dr.Jit LLVM library does not exist: {llvm}. See README.md.')
    import mitsuba as mi
    if mi.variant() is None:
        if requested=='cuda':mi.set_variant('cuda_ad_mono_polarized')
        elif requested=='llvm':mi.set_variant('llvm_ad_mono_polarized')
        elif os.name=='nt':
            driver=windows_cuda_driver_version()
            # Installed Dr.Jit 1.5 reports CUDA >=12.2/R535 as its minimum.
            # Avoid trying to initialize a known incompatible GPU driver.
            if driver is not None and driver<12020:mi.set_variant('llvm_ad_mono_polarized')
    from sionna import rt
    return rt,mi
