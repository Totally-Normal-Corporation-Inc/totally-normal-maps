"""Backward-compatible Ontario entry points for the shared refresh engine."""
from .catalogue import ROOT
from .jurisdiction_refresh import MAX_BYTES, source_identity, compare_extents
from .jurisdiction_refresh import build_refresh as _build_refresh, checked_source as _checked_source

PLAN = ROOT / 'ontario-refresh-2026-09.json'


def checked_source(path, source):
    return _checked_source(path, source, bounds=(-96, 41, -74, 57))


def build_refresh(run, destination, *, source_dir, plan_path=None):
    return _build_refresh(run, destination, source_dir=source_dir, plan_path=plan_path or PLAN,
                          province='35', legacy_ontario=True)
