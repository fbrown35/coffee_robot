"""설정 로딩. config/config.yaml (없으면 config.example.yaml) 을 읽고 ~ 를 확장한다."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATHS = [ROOT / "config" / "config.yaml", ROOT / "config" / "config.example.yaml"]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def expand(path: str) -> str:
    return os.path.expanduser(os.path.expandvars(path))


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    _load_dotenv(ROOT / ".env")
    candidates = [Path(path)] if path else DEFAULT_PATHS
    for p in candidates:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            cfg["_path"] = str(p)
            return cfg
    raise FileNotFoundError(f"config not found: {candidates}")


def save_config(cfg: dict[str, Any], path: str | Path | None = None) -> Path:
    target = Path(path or cfg.get("_path") or DEFAULT_PATHS[0])
    if target.name == "config.example.yaml":
        target = DEFAULT_PATHS[0]
    data = {k: v for k, v in cfg.items() if not k.startswith("_")}
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return target
