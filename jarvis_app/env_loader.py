from __future__ import annotations

import os
import re
from pathlib import Path


ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_project_env(path: Path | str = DEFAULT_ENV_PATH) -> int:
    """Load a small, predictable subset of dotenv syntax without overriding the shell."""
    env_path = Path(path)
    if not env_path.is_file():
        return 0

    loaded = 0
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if not separator or not ENV_NAME_PATTERN.fullmatch(name):
            continue

        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if name not in os.environ:
            os.environ[name] = value
            loaded += 1
    return loaded
