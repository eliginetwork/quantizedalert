"""Backward-compatibility alias module for quantizedalert."""
import importlib
import sys

import quantizedalert

# Forward root module
sys.modules["unlockaid"] = quantizedalert
from quantizedalert import __version__  # noqa: F401


class _CompatibilityFinder:
    def find_spec(self, fullname, path, target=None):
        if fullname == "unlockaid.cli":
            return None  # Let standard import load src/unlockaid/cli.py
        if fullname.startswith("unlockaid."):
            target_name = "quantizedalert." + fullname[len("unlockaid."):]
            try:
                mod = importlib.import_module(target_name)
                sys.modules[fullname] = mod
                return mod.__spec__
            except Exception:
                return None
        return None


if not any(isinstance(f, _CompatibilityFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _CompatibilityFinder())
