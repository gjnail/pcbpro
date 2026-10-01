"""PCBPro - PCB design, 3D visualisation and ordering desktop application."""
import os as _os

# Single-threaded BLAS: the circuit simulator solves many small dense systems, and OpenBLAS's spinning worker threads
# make those thousands of times slower whenever the CPU is busy (a DAW, a build). Must be set before numpy loads.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_var, "1")

__version__ = "1.0.0"
APP_NAME = "PCBPro"
FILE_EXT = ".pcbpro"
