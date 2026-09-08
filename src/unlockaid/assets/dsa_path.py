"""Asset adapter: context-manager that exposes daily_stock_analysis packages.

DSA uses absolute `src.*` / `data_provider.*` imports rooted at its repo dir.
We prepend its path only while executing the adapter block, so the platform's
own `unlockaid` namespace is never shadowed and imports resolve to the real
asset code (Playbook Amendment A: invocation, not mention).
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager


@contextmanager
def dsa_importable(dsa_path: str):
    """Make `/root/repos/daily_stock_analysis` importable as `src`/`data_provider`."""
    inserted = dsa_path not in sys.path
    if inserted:
        sys.path.insert(0, dsa_path)
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(dsa_path)
            except ValueError:
                pass


def dsa_module(name: str, dsa_path: str):
    """Import (and cache) a module from the DSA asset, e.g. 'src.notification'."""
    with dsa_importable(dsa_path):
        return importlib.import_module(name)
