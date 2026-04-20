import os
from pathlib import Path


ENV_CANDIDATES = (
    Path(__file__).resolve().parent.parent / ".env",
)


def load_env_from_file() -> None:
    for env_path in ENV_CANDIDATES:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_env(name: str, default: str = "") -> str:
    load_env_from_file()
    return os.getenv(name, default).strip()
