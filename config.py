# File: lazy_develop/config.py
# Lightweight config loader for Sloth.
# - Reads JSON file `sloth_config.json` from the same directory.
# - Exposes get_config() returning dict.
# - All callers should provide sensible fallbacks when keys are absent.

import json
import os
from typing import Any, Dict

_CONFIG_CACHE: Dict[str, Any] | None = None

CONFIG_FILENAME = "sloth_config.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, CONFIG_FILENAME)


def _load_from_disk() -> Dict[str, Any]:
    try:
        if not os.path.exists(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except Exception:
        # Be resilient: never crash on config read
        return {}


def get_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = _load_from_disk()
    return _CONFIG_CACHE


def get(path: str, default: Any = None) -> Any:
    """
    Retrieve a value by dotted path, e.g. "model.name".
    If key is absent, return default.
    """
    cfg = get_config()
    cur: Any = cfg
    if not path:
        return default
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
