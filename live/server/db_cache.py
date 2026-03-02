"""Database cache — sync DB + QXW from GitHub, serve from local cache."""

from __future__ import annotations

import base64
import json
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import Config

log = logging.getLogger("live.db_cache")

# Repo-root relative paths cached under live/data/
_CACHE_FILES = {
    "db": "lighting-ai-db.json",
    "qxw": "ThePact.qxw",
}


def _data_dir(cfg: Config) -> Path:
    return cfg.base_dir / "data"


def _repo_root(cfg: Config) -> Path:
    """Try to find the repo root (two levels up from live/)."""
    return cfg.base_dir.parent


def _sync_via_git(cfg: Config) -> bool:
    """Try a quick `git pull` if we're inside the repo."""
    repo = _repo_root(cfg)
    if not (repo / ".git").exists():
        return False
    try:
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo,
            capture_output=True,
            timeout=30,
            check=True,
        )
        log.info("git pull succeeded")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("git pull failed: %s", exc)
        return False


def _sync_via_api(cfg: Config) -> bool:
    """Fetch DB and QXW via GitHub REST API."""
    if not cfg.github.token:
        log.warning("No GitHub token — skipping API sync")
        return False

    headers = {
        "Authorization": f"Bearer {cfg.github.token}",
        "Accept": "application/vnd.github.v3+json",
    }
    data_dir = _data_dir(cfg)
    data_dir.mkdir(parents=True, exist_ok=True)

    files_to_fetch = {
        "db": cfg.github.db_path,
        "qxw": cfg.github.qxw_path,
    }

    ok = True
    for key, repo_path in files_to_fetch.items():
        url = f"https://api.github.com/repos/{cfg.github.repo}/contents/{repo_path}"
        try:
            resp = httpx.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            content = base64.b64decode(data["content"])
            dest = data_dir / _CACHE_FILES[key]
            dest.write_bytes(content)
            log.info("Fetched %s (%d bytes)", repo_path, len(content))
        except Exception as exc:
            log.warning("API fetch failed for %s: %s", repo_path, exc)
            ok = False
    return ok


def _copy_from_repo(cfg: Config) -> bool:
    """Copy DB and QXW from the local repo clone into data/."""
    repo = _repo_root(cfg)
    data_dir = _data_dir(cfg)
    data_dir.mkdir(parents=True, exist_ok=True)

    sources = {
        "db": repo / cfg.github.db_path,
        "qxw": repo / cfg.github.qxw_path,
    }

    ok = True
    for key, src in sources.items():
        dest = data_dir / _CACHE_FILES[key]
        if src.exists():
            shutil.copy2(src, dest)
            log.info("Copied %s -> %s", src, dest)
        else:
            log.warning("Local file not found: %s", src)
            ok = False
    return ok


def sync(cfg: Config) -> dict:
    """Sync DB + QXW. Returns status dict."""
    result = {"ok": False, "method": "none", "time": None}

    # 1) Try git pull first (updates the whole repo)
    if _sync_via_git(cfg):
        _copy_from_repo(cfg)
        result.update(ok=True, method="git")
    # 2) Fall back to GitHub API
    elif _sync_via_api(cfg):
        result.update(ok=True, method="api")
    # 3) Fall back to copying from local repo
    elif _copy_from_repo(cfg):
        result.update(ok=True, method="local")
    else:
        # Check if we have cached data at all
        data_dir = _data_dir(cfg)
        if (data_dir / _CACHE_FILES["db"]).exists():
            log.warning("Using stale cache — no sync possible")
            result.update(ok=True, method="cache")
        else:
            log.error("No DB available — sync failed and no cache")

    if result["ok"]:
        result["time"] = datetime.now(timezone.utc).isoformat()

    return result


def load_db(cfg: Config) -> dict:
    """Load the cached DB JSON and return as dict."""
    path = _data_dir(cfg) / _CACHE_FILES["db"]
    if not path.exists():
        raise FileNotFoundError(f"DB not found at {path} — run sync() first")
    return json.loads(path.read_text(encoding="utf-8"))


def load_qxw_path(cfg: Config) -> Path:
    """Return path to the cached QXW file."""
    path = _data_dir(cfg) / _CACHE_FILES["qxw"]
    if not path.exists():
        raise FileNotFoundError(f"QXW not found at {path} — run sync() first")
    return path
