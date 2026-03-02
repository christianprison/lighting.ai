"""Configuration loader for lighting.ai Live Controller."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_BASE_DIR = Path(__file__).resolve().parent.parent  # live/


@dataclass
class GitHubConfig:
    repo: str = "christianprison/lighting.ai"
    db_path: str = "db/lighting-ai-db.json"
    qxw_path: str = "db/ThePact.qxw"
    token: str = ""


@dataclass
class QlcConfig:
    osc_host: str = "127.0.0.1"
    osc_port: int = 7700
    osc_universe: int = 0


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class Config:
    github: GitHubConfig = field(default_factory=GitHubConfig)
    qlc: QlcConfig = field(default_factory=QlcConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    base_dir: Path = _BASE_DIR


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, with env-var overrides."""
    if path is None:
        path = _BASE_DIR / "config.yaml"

    cfg = Config()

    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        gh = raw.get("github", {})
        cfg.github = GitHubConfig(
            repo=gh.get("repo", cfg.github.repo),
            db_path=gh.get("db_path", cfg.github.db_path),
            qxw_path=gh.get("qxw_path", cfg.github.qxw_path),
            token=gh.get("token", ""),
        )

        qlc = raw.get("qlc", {})
        cfg.qlc = QlcConfig(
            osc_host=qlc.get("osc_host", cfg.qlc.osc_host),
            osc_port=int(qlc.get("osc_port", cfg.qlc.osc_port)),
            osc_universe=int(qlc.get("osc_universe", cfg.qlc.osc_universe)),
        )

        srv = raw.get("server", {})
        cfg.server = ServerConfig(
            host=srv.get("host", cfg.server.host),
            port=int(srv.get("port", cfg.server.port)),
        )

    # Env overrides
    if tok := os.environ.get("GITHUB_TOKEN"):
        cfg.github.token = tok
    if repo := os.environ.get("GITHUB_REPO"):
        cfg.github.repo = repo

    return cfg
