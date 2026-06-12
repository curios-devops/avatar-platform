"""
Minimal chumpy stub — lets pickle load FLAME .pkl files without real chumpy.

Real chumpy doesn't import on numpy>=1.24 (uses removed np.bool/np.int APIs).
FLAME model pickles (FLAME2020 generic_model.pkl, deca_model.tar internals)
store arrays as chumpy.Ch / chumpy.ch.Ch objects; this stub registers fake
modules in sys.modules BEFORE unpickling so those objects deserialize into
plain numpy-backed containers.

Usage: `import chumpy_stub` before any code that unpickles a FLAME model
(e.g. MICA's models/flame.py). Registration is skipped if real chumpy exists.

The state-dict key priority ('x' first) matters: FLAME 2023 pickles store the
array under 'x'.
"""

import sys
import types

import numpy as np

try:
    import scipy.sparse as _sp
except ImportError:  # scipy always present in the worker image
    _sp = None


def _register() -> None:
    if "chumpy" in sys.modules:
        return  # real chumpy (or an earlier stub) already importable

    class Ch:
        def __init__(self, x=None, **kw):
            if x is not None:
                self._array = np.asarray(x)

        def __setstate__(self, state):
            if isinstance(state, dict):
                for key in ("x", "r", "_array", "val", "v"):
                    if key in state:
                        v = state[key]
                        if _sp is not None and _sp.issparse(v):
                            v = v.toarray()
                        self._array = np.asarray(v)
                        return

        def __array__(self, dtype=None):
            a = getattr(self, "_array", np.array([]))
            return a.astype(dtype) if dtype is not None else a

        @property
        def r(self):
            return getattr(self, "_array", np.array([]))

        @property
        def shape(self):
            return getattr(self, "_array", np.array([])).shape

    ch_mod = types.ModuleType("chumpy")
    chch = types.ModuleType("chumpy.ch")
    ch_mod.Ch = Ch
    chch.Ch = Ch
    sys.modules.update({
        "chumpy": ch_mod,
        "chumpy.ch": chch,
        "chumpy.utils": types.ModuleType("chumpy.utils"),
        "chumpy.reordering": types.ModuleType("chumpy.reordering"),
        "chumpy.math_utils": types.ModuleType("chumpy.math_utils"),
    })


_register()
