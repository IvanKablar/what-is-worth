"""Paths and settings, overridable through environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


@dataclass(frozen=True)
class Config:
    data_dir: Path
    config_dir: Path
    cache_dir: Path

    @property
    def ledger_path(self) -> Path:
        return self.data_dir / "ledger.sqlite"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "sync.lock"

    @property
    def price_overrides_path(self) -> Path:
        return self.config_dir / "prices.json"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.config_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    home = Path.home()
    xdg_data = _env_path("XDG_DATA_HOME", home / ".local" / "share")
    xdg_config = _env_path("XDG_CONFIG_HOME", home / ".config")
    xdg_cache = _env_path("XDG_CACHE_HOME", home / ".cache")
    return Config(
        data_dir=_env_path("WIW_DATA_DIR", xdg_data / "what-is-worth"),
        config_dir=_env_path("WIW_CONFIG_DIR", xdg_config / "what-is-worth"),
        cache_dir=_env_path("WIW_CACHE_DIR", xdg_cache / "what-is-worth"),
    )
