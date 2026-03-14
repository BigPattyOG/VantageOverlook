"""CogManager — repo registry and cog installation tracking.

The manager is used by both the CLI (offline) and the running bot (runtime).

Directory layout
----------------
``<data_dir>/repos/``         — root for all repos (added to sys.path at startup).
``<data_dir>/repos/<name>/``  — GitHub repos cloned here.
``<data_dir>/repos/<name>``   — Local repos symlinked here (symlink -> local path).
``<data_dir>/cog_data.json``  — Persisted repo / cog registry.

The data directory is resolved via :func:`core.config.resolve_data_dir` (checks
``VPROD_DATA_DIR`` env var, then ``/var/lib/vprod/<BotName>``, then local
``data/`` fallback).

Cog module paths
----------------
A cog is referenced by ``<repo_name>.<cog_name>`` (e.g. ``my_cogs.welcome``).
Since ``<data_dir>/repos/`` is on sys.path, ``import my_cogs.welcome`` resolves
to ``<data_dir>/repos/my_cogs/welcome.py`` (or ``__init__.py``).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .config import resolve_data_dir

DATA_DIR = resolve_data_dir()
REPOS_DIR = DATA_DIR / "repos"
COG_DATA_FILE = DATA_DIR / "cog_data.json"

_DEFAULT: Dict = {
    "repos": {},
    "installed_cogs": [],
    "autoload": [],
}


class CogManager:
    """Manages cog repos and installation state."""

    def __init__(self) -> None:
        self._data = self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        COG_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not COG_DATA_FILE.exists():
            return {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in _DEFAULT.items()}
        with open(COG_DATA_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return {**_DEFAULT, **data}

    def _save(self) -> None:
        COG_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(COG_DATA_FILE, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)

    # ── repo management ───────────────────────────────────────────────────────

    def list_repos(self) -> Dict[str, dict]:
        """Return the registered repo registry."""
        return self._data["repos"]

    def add_github_repo(self, name: str, url: str) -> Path:
        """Clone a GitHub repo into ``data/repos/<name>/`` and register it.

        Returns the cloned path.
        """
        import git  # imported lazily; only needed for GitHub repo operations

        if name in self._data["repos"]:
            raise ValueError(f"Repo '{name}' is already registered.")

        REPOS_DIR.mkdir(parents=True, exist_ok=True)
        dest = REPOS_DIR / name
        if dest.exists():
            raise ValueError(f"Directory '{dest}' already exists. Use a different name.")

        git.Repo.clone_from(url, str(dest))

        self._data["repos"][name] = {
            "name": name,
            "url": url,
            "type": "github",
            "path": str(dest.resolve()),
            "installed_cogs": [],
        }
        self._save()
        return dest

    def add_local_repo(self, name: str, path: str) -> None:
        """Register a local directory as a repo via a symlink in ``data/repos/``.

        The symlink means cogs load under ``<name>.<cog>`` just like GitHub
        repos — no extra sys.path entries needed.
        """
        if name in self._data["repos"]:
            raise ValueError(f"Repo '{name}' is already registered.")

        resolved = Path(path).resolve()
        if not resolved.exists():
            raise ValueError(f"Path '{resolved}' does not exist.")

        REPOS_DIR.mkdir(parents=True, exist_ok=True)
        link = REPOS_DIR / name
        if link.exists() or link.is_symlink():
            raise ValueError(f"'{link}' already exists. Use a different name.")

        link.symlink_to(resolved)

        self._data["repos"][name] = {
            "name": name,
            "url": None,
            "type": "local",
            "path": str(resolved),
            "installed_cogs": [],
        }
        self._save()

    def remove_repo(self, name: str) -> None:
        """Remove a repo from the registry and disk (if GitHub-cloned)."""
        if name not in self._data["repos"]:
            raise ValueError(f"Repo '{name}' not found.")

        info = self._data["repos"][name]

        # Clean up disk
        if info["type"] == "github":
            path = Path(info["path"])
            if path.exists() and REPOS_DIR in path.parents:
                shutil.rmtree(path)
        elif info["type"] == "local":
            link = REPOS_DIR / name
            if link.is_symlink():
                link.unlink()

        # Remove cogs from this repo
        prefix = f"{name}."
        self._data["installed_cogs"] = [
            c for c in self._data["installed_cogs"] if not c.startswith(prefix)
        ]
        self._data["autoload"] = [
            c for c in self._data["autoload"] if not c.startswith(prefix)
        ]
        del self._data["repos"][name]
        self._save()

    def update_github_repo(self, name: str) -> None:
        """Pull latest changes for a GitHub-cloned repo."""
        import git

        if name not in self._data["repos"]:
            raise ValueError(f"Repo '{name}' not found.")

        info = self._data["repos"][name]
        if info["type"] != "github":
            raise ValueError(f"'{name}' is a local repo — update it via git manually.")

        repo = git.Repo(info["path"])
        repo.remotes.origin.pull()

    # ── cog management ────────────────────────────────────────────────────────

    def install_cog(self, repo_name: str, cog_name: str) -> str:
        """Register ``<repo_name>.<cog_name>`` as installed.

        Verifies the cog file/package exists in the repo directory.
        Returns the full module path string.
        """
        if repo_name not in self._data["repos"]:
            raise ValueError(f"Repo '{repo_name}' not found. Add it with:\n"
                             f"  python launcher.py repos add <URL>")

        repo_info = self._data["repos"][repo_name]
        repo_path = Path(repo_info["path"])

        cog_file = repo_path / f"{cog_name}.py"
        cog_pkg = repo_path / cog_name / "__init__.py"
        if not cog_file.exists() and not cog_pkg.exists():
            raise FileNotFoundError(
                f"Cog '{cog_name}' not found in repo '{repo_name}'.\n"
                f"  Checked: {cog_file}\n"
                f"           {cog_pkg}"
            )

        cog_path = f"{repo_name}.{cog_name}"
        if cog_path not in self._data["installed_cogs"]:
            self._data["installed_cogs"].append(cog_path)
            repo_info.setdefault("installed_cogs", [])
            if cog_name not in repo_info["installed_cogs"]:
                repo_info["installed_cogs"].append(cog_name)
            self._save()

        return cog_path

    def uninstall_cog(self, cog_path: str) -> None:
        """Unregister a cog from the installed list."""
        if cog_path not in self._data["installed_cogs"]:
            raise ValueError(f"Cog '{cog_path}' is not installed.")

        self._data["installed_cogs"].remove(cog_path)
        self._data["autoload"] = [c for c in self._data["autoload"] if c != cog_path]

        parts = cog_path.split(".", 1)
        if len(parts) == 2:
            repo_name, cog_name = parts
            repo = self._data["repos"].get(repo_name)
            if repo and cog_name in repo.get("installed_cogs", []):
                repo["installed_cogs"].remove(cog_name)

        self._save()

    def get_installed_cogs(self) -> List[str]:
        return list(self._data["installed_cogs"])

    def get_autoload(self) -> List[str]:
        return list(self._data["autoload"])

    def toggle_autoload(self, cog_path: str) -> bool:
        """Toggle autoload for an installed cog.

        Returns ``True`` if autoload is now *enabled*, ``False`` if disabled.
        """
        if cog_path not in self._data["installed_cogs"]:
            raise ValueError(
                f"Cog '{cog_path}' is not installed. Install it first:\n"
                f"  python launcher.py cogs install <repo> <cog>"
            )

        if cog_path in self._data["autoload"]:
            self._data["autoload"].remove(cog_path)
            self._save()
            return False

        self._data["autoload"].append(cog_path)
        self._save()
        return True

    # ── sys.path setup ────────────────────────────────────────────────────────

    def setup_paths(self) -> None:
        """Add ``data/repos/`` to ``sys.path``.

        Call this once at bot startup before loading any extensions.  All
        GitHub clones and local symlinks live under ``data/repos/``, so a
        single path entry makes every repo importable.
        """
        repos_dir = str(REPOS_DIR.resolve())
        if repos_dir not in sys.path:
            sys.path.insert(0, repos_dir)
