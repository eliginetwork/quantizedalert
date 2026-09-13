"""QuantizedAlert — Autonomous Quant Research-to-Alert Revenue Engine."""
__version__ = "0.1.0"

# Pre-load libgomp on Linux to prevent ARM64/glibc static TLS exhaustion errors
import ctypes

for _lib in ("/lib/aarch64-linux-gnu/libgomp.so.1", "/usr/lib/aarch64-linux-gnu/libgomp.so.1", "libgomp.so.1"):
    try:
        ctypes.CDLL(_lib, mode=ctypes.RTLD_GLOBAL)
        break
    except Exception:
        pass

