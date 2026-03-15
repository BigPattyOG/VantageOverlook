"""PluginManager — repo registry and plugin installation tracking.

Used by both the CLI (offline) and the running bot (runtime).

Directory layout
----------------
``<data_dir>/repos/``            — root for all repos (added to sys.path at startup).
``<data_dir>/repos/<name>/``     — GitHub repos cloned here.
``<data_dir>/repos/<name>``      — Local repos symlinked here (symlink → local path).
``<data_dir>/plugin_data.json``  — Persisted repo / plugin registry.

The data directory is resolved via :func:`framework.config.resolve_data_dir`
(checks ``VPROD_DATA_DIR`` env var, then ``/var/lib/vprod``, then local
``data/`` fallback).

Plugin module paths
-------------------
A plugin is referenced by ``<repo_name>.<plugin_name>`` (e.g. ``my_plugins.welcome``).
Since ``<data_dir>/repos/`` is on sys.path, ``import my_plugins.welcome`` resolves
to ``<data_dir>/repos/my_plugins/welcome.py`` (or package ``__init__.py``).
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
PLUGIN_DATA_FILE = DATA_DIR / "plugin_data.json"

_DEFAULT: Dict = {
    "repos": {},
    "installed_plugins": [],
    "autoload": [],
    "ext_plugins": {},   # external / local plugins: {name: {path, enabled, hash, ...}}
}


class PluginManager:
    """Manages plugin repos, autoload state, and external plugin registry."""

    def __init__(self) -> None:
        self._data = self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        PLUGIN_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not PLUGIN_DATA_FILE.exists():
            return {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in _DEFAULT.items()}
        with open(PLUGIN_DATA_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        # Migrate legacy key name from old installs
        if "installed_cogs" in data and "installed_plugins" not in data:
            data["installed_plugins"] = data.pop("installed_cogs")
        return {**_DEFAULT, **data}

    def _save(self) -> None:
        PLUGIN_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PLUGIN_DATA_FILE, "w", encoding="utf-8") as fh:
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
            "installed_plugins": [],
        }
        self._save()
        return dest

    def add_local_repo(self, name: str, path: str) -> None:
        """Register a local directory as a repo via a symlink in ``data/repos/``.

        The symlink means plugins load under ``<name>.<plugin>`` just like
        GitHub repos — no extra sys.path entries needed.
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
            "installed_plugins": [],
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

        # Remove plugins from this repo
        prefix = f"{name}."
        self._data["installed_plugins"] = [
            p for p in self._data["installed_plugins"] if not p.startswith(prefix)
        ]
        self._data["autoload"] = [
            p for p in self._data["autoload"] if not p.startswith(prefix)
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

    # ── plugin management ─────────────────────────────────────────────────────

    def install_plugin(self, repo_name: str, plugin_name: str) -> str:
        """Register ``<repo_name>.<plugin_name>`` as installed.

        Verifies the plugin file/package exists in the repo directory.
        Returns the full module path string.
        """
        if repo_name not in self._data["repos"]:
            raise ValueError(
                f"Repo '{repo_name}' not found. Add it with:\n"
                f"  python launcher.py repos add <URL>"
            )

        repo_info = self._data["repos"][repo_name]
        repo_path = Path(repo_info["path"])

        plugin_file = repo_path / f"{plugin_name}.py"
        plugin_pkg  = repo_path / plugin_name / "__init__.py"
        if not plugin_file.exists() and not plugin_pkg.exists():
            raise FileNotFoundError(
                f"Plugin '{plugin_name}' not found in repo '{repo_name}'.\n"
                f"  Checked: {plugin_file}\n"
                f"           {plugin_pkg}"
            )

        plugin_path = f"{repo_name}.{plugin_name}"
        if plugin_path not in self._data["installed_plugins"]:
            self._data["installed_plugins"].append(plugin_path)
            repo_info.setdefault("installed_plugins", [])
            if plugin_name not in repo_info["installed_plugins"]:
                repo_info["installed_plugins"].append(plugin_name)
            self._save()

        return plugin_path

    def uninstall_plugin(self, plugin_path: str) -> None:
        """Unregister a plugin from the installed list."""
        if plugin_path not in self._data["installed_plugins"]:
            raise ValueError(f"Plugin '{plugin_path}' is not installed.")

        self._data["installed_plugins"].remove(plugin_path)
        self._data["autoload"] = [p for p in self._data["autoload"] if p != plugin_path]

        parts = plugin_path.split(".", 1)
        if len(parts) == 2:
            repo_name, plugin_name = parts
            repo = self._data["repos"].get(repo_name)
            if repo and plugin_name in repo.get("installed_plugins", []):
                repo["installed_plugins"].remove(plugin_name)

        self._save()

    def get_installed_plugins(self) -> List[str]:
        """Return a list of all installed plugin paths."""
        return list(self._data["installed_plugins"])

    def get_autoload(self) -> List[str]:
        """Return a list of plugin paths set to autoload on bot start."""
        return list(self._data["autoload"])

    def toggle_autoload(self, plugin_path: str) -> bool:
        """Toggle autoload for an installed plugin.

        Returns ``True`` if autoload is now *enabled*, ``False`` if disabled.
        """
        if plugin_path not in self._data["installed_plugins"]:
            raise ValueError(
                f"Plugin '{plugin_path}' is not installed. Install it first:\n"
                f"  python launcher.py plugins install <repo> <plugin>"
            )

        if plugin_path in self._data["autoload"]:
            self._data["autoload"].remove(plugin_path)
            self._save()
            return False

        self._data["autoload"].append(plugin_path)
        self._save()
        return True

    # ── sys.path setup ────────────────────────────────────────────────────────

    def setup_paths(self) -> None:
        """Add ``data/repos/`` to ``sys.path``.

        Call once at bot startup before loading any extensions.  All GitHub
        clones and local symlinks live under ``data/repos/``, so a single
        path entry makes every repo importable.
        """
        repos_dir = str(REPOS_DIR.resolve())
        if repos_dir not in sys.path:
            sys.path.insert(0, repos_dir)

    # ── external plugin registry ──────────────────────────────────────────────

    def get_ext_plugins(self) -> Dict[str, dict]:
        """Return the external plugin registry dict."""
        return dict(self._data.get("ext_plugins", {}))

    def register_ext_plugin(
        self,
        name: str,
        path: str,
        plugin_hash: str,
        manifest: Optional[dict] = None,
        enabled: bool = True,
    ) -> None:
        """Register an external plugin in the registry.

        Called by the install flow after a plugin has been copied/linked into
        ``ext_plugins_dir`` and its SHA-256 hash computed.
        """
        from datetime import datetime, timezone
        self._data.setdefault("ext_plugins", {})[name] = {
            "path": path,
            "enabled": enabled,
            "hash": plugin_hash,
            "manifest": manifest or {},
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def enable_ext_plugin(self, name: str, enabled: bool = True) -> None:
        """Enable or disable an external plugin without removing it."""
        reg = self._data.setdefault("ext_plugins", {})
        if name not in reg:
            raise ValueError(f"External plugin '{name}' is not registered.")
        reg[name]["enabled"] = enabled
        self._save()

    def remove_ext_plugin(self, name: str) -> None:
        """Remove an external plugin from the registry (does not delete files)."""
        reg = self._data.setdefault("ext_plugins", {})
        if name not in reg:
            raise ValueError(f"External plugin '{name}' is not registered.")
        del reg[name]
        self._save()

    def update_ext_plugin_hash(self, name: str, new_hash: str) -> None:
        """Update the stored hash after a plugin has been updated on disk."""
        reg = self._data.setdefault("ext_plugins", {})
        if name not in reg:
            raise ValueError(f"External plugin '{name}' is not registered.")
        reg[name]["hash"] = new_hash
        self._save()


