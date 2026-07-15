from __future__ import annotations

import os
from pathlib import Path


DATA_DIR_ENV = "ALPHA_POKER_DATA_DIR"


def get_data_dir() -> Path:
    """Return the writable runtime data directory.

    Packaged Electron builds provide a userData-backed directory through the
    environment.  Development keeps the existing backend/data location.
    Existing data is deliberately not moved or deleted.
    """

    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[1] / "data"
