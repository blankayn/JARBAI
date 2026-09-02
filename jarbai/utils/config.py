import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_env(path=None):
    """Read .env into os.environ. Secrets live there, never in config.yaml,
    because config.yaml is committed and .env is gitignored."""
    env_path = Path(path) if path else ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:      # a real env var wins over .env
            os.environ[key] = value


class Config:
    def __init__(self, data):
        self._data = data or {}

    def get(self, dotted, default=None):
        cur = self._data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def raw(self):
        return self._data


SETTINGS = ROOT / "settings.json"


def _apply_overrides(data):
    """Merge settings.json over config.yaml.

    Runtime changes (the dashboard's brain switch) go here rather than being
    written back into config.yaml, which is hand-commented and would lose
    those comments on a rewrite.
    """
    import json

    if not SETTINGS.is_file():
        return data
    try:
        overrides = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return data
    for dotted, value in (overrides or {}).items():
        parts = dotted.split(".")
        cursor = data
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
            if not isinstance(cursor, dict):
                break
        else:
            cursor[parts[-1]] = value
    return data


ENV_PATH = ROOT / ".env"


def mask_secret(value):
    """A hint that the right key is set, without revealing it."""
    if not value:
        return ""
    tail = value[-4:] if len(value) > 8 else ""
    return "•" * 8 + tail


def save_env_var(key, value):
    """Write one secret to .env, leaving the other entries alone.

    Secrets go here rather than config.yaml or settings.json because .env is
    the only one of the three that is gitignored.
    """
    lines = []
    if ENV_PATH.is_file():
        lines = [
            line for line in ENV_PATH.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith(f"{key}=")
        ]
    value = (value or "").strip()
    if value:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)
    return bool(value)


def save_override(dotted, value):
    import json

    current = {}
    if SETTINGS.is_file():
        try:
            current = json.loads(SETTINGS.read_text(encoding="utf-8")) or {}
        except (ValueError, OSError):
            current = {}
    current[dotted] = value
    SETTINGS.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def load_config(path="config.yaml"):
    load_env()
    config_path = Path(path)
    if not config_path.exists():
        return Config(_apply_overrides({}))
    with open(config_path, "r", encoding="utf-8") as handle:
        return Config(_apply_overrides(yaml.safe_load(handle) or {}))
