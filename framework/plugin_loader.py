"""Secure loader for external Vantage plugins.

External plugins live in a dedicated directory outside the main framework
(default: ``<data_dir>/ext_plugins/``).  They can be single Python files or
packages (directories with ``__init__.py``).  An optional ``vantage.toml``
manifest in each plugin provides metadata.

Safety guarantees
-----------------
* **Path containment** — every resolved plugin path must be inside the
  configured ``plugins_dir``.  Symlinks are resolved before the check so a
  crafted symlink cannot escape.
* **SHA-256 integrity** — a fingerprint of all ``*.py`` files is computed at
  install time and stored in ``plugin_data.json``.  On every load, the hash
  is recomputed; a mismatch triggers a warning (but the plugin still loads so
  a legitimate ``git pull`` update doesn't break the bot).
* **Isolated exceptions** — each plugin is loaded in its own try/except block.
  A broken plugin is added to the ``failed`` list; it never crashes the
  framework or prevents other plugins from loading.
* **No sys.path mutation per plugin** — the single ``ext_plugins/`` directory
  root is added to ``sys.path`` once.  Individual plugin directories are
  *not* added, which prevents cross-plugin import collisions.

Plugin module namespace
-----------------------
External plugins are imported as ``_vp_ext.<plugin_name>`` (e.g.
``_vp_ext.welcome``).  This namespace is invisible to Discord's extension
system so plugin names can never conflict with built-ins or user-installed
community plugins from ``data/repos/``.

vantage.toml manifest (optional)
---------------------------------
Place a ``vantage.toml`` at the root of the plugin file or directory:

.. code-block:: toml

    [plugin]
    name        = "Welcome"
    version     = "1.0.0"
    description = "Greets new members"
    author      = "BigPatty"
    min_framework = "1.0.0"
"""

from __future__ import annotations

import hashlib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from discord.ext import commands

log = logging.getLogger("vprod.plugin_loader")

# Namespace prefix used when importing external plugins
_EXT_NAMESPACE = "_vp_ext"


# ── Manifest ──────────────────────────────────────────────────────────────────

def _read_manifest(plugin_root: Path) -> Dict[str, Any]:
    """Parse ``vantage.toml`` if present; return an empty dict otherwise."""
    manifest_path = plugin_root / "vantage.toml"
    if not manifest_path.exists():
        return {}
    try:
        # tomllib is in stdlib from Python 3.11; fall back to tomli if older.
        try:
            import tomllib  # type: ignore[import]
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore[import, no-redef]
            except ImportError:
                log.debug(
                    "Could not read vantage.toml for %s — "
                    "install 'tomli' for Python < 3.11 (pip install tomli).",
                    plugin_root.name,
                )
                return {}
        with open(manifest_path, "rb") as fh:
            return tomllib.load(fh).get("plugin", {})
    except Exception as exc:
        log.warning("Failed to parse vantage.toml in %s: %s", plugin_root.name, exc)
        return {}


# ── Integrity hash ────────────────────────────────────────────────────────────

def compute_plugin_hash(plugin_root: Path) -> str:
    """Return a SHA-256 hex digest over all ``*.py`` files in *plugin_root*.

    Files are sorted so the hash is deterministic regardless of OS ordering.
    For a single-file plugin, *plugin_root* is the ``.py`` file itself.
    """
    h = hashlib.sha256()
    if plugin_root.is_file():
        paths = [plugin_root]
    else:
        paths = sorted(plugin_root.rglob("*.py"))
    for path in paths:
        try:
            h.update(path.read_bytes())
        except OSError:
            pass
    return h.hexdigest()


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class ExternalPlugin:
    """Metadata about a discovered external plugin."""

    name: str               # module name (no namespace prefix)
    path: Path              # resolved filesystem path
    manifest: Dict[str, Any] = field(default_factory=dict)
    module_path: str = ""   # e.g. "_vp_ext.welcome"
    current_hash: str = ""
    stored_hash: str = ""
    loaded: bool = False
    error: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.manifest.get("name", self.name)

    @property
    def version(self) -> str:
        return self.manifest.get("version", "?")

    @property
    def hash_ok(self) -> bool:
        """True when stored and current hashes match (or no stored hash yet)."""
        return not self.stored_hash or self.stored_hash == self.current_hash


# ── Loader ────────────────────────────────────────────────────────────────────

class PluginLoader:
    """Discovers, validates, and loads external plugins from *plugins_dir*."""

    def __init__(self, plugins_dir: Path) -> None:
        self.plugins_dir = plugins_dir.resolve()

    # ── path safety ───────────────────────────────────────────────────────────

    def _safe_resolve(self, path: Path) -> Optional[Path]:
        """Resolve *path* and check it is inside ``self.plugins_dir``.

        Returns the resolved path on success, ``None`` on containment failure.
        """
        try:
            resolved = path.resolve()
            resolved.relative_to(self.plugins_dir)
            return resolved
        except ValueError:
            log.error(
                "Security: plugin path %s escapes plugins_dir %s — skipped.",
                path,
                self.plugins_dir,
            )
            return None

    # ── discovery ─────────────────────────────────────────────────────────────

    def discover(self, registry: Dict[str, Dict]) -> List[ExternalPlugin]:
        """Return ``ExternalPlugin`` objects for every entry in *registry*.

        *registry* is the ``ext_plugins`` dict from ``plugin_data.json``.
        Plugins whose ``enabled`` flag is ``False`` are skipped.
        """
        plugins: List[ExternalPlugin] = []
        for name, info in registry.items():
            if not info.get("enabled", True):
                continue
            raw_path = Path(info.get("path", self.plugins_dir / name))
            resolved = self._safe_resolve(raw_path)
            if resolved is None:
                continue
            if not resolved.exists():
                log.warning("External plugin '%s' path does not exist: %s", name, resolved)
                continue
            manifest = _read_manifest(resolved if resolved.is_dir() else resolved.parent)
            current_hash = compute_plugin_hash(resolved)
            ep = ExternalPlugin(
                name=name,
                path=resolved,
                manifest=manifest,
                module_path=f"{_EXT_NAMESPACE}.{name}",
                current_hash=current_hash,
                stored_hash=info.get("hash", ""),
            )
            if not ep.hash_ok:
                log.warning(
                    "Plugin '%s' hash mismatch — file may have changed since install. "
                    "Run '!plugin verify' to review. Continuing load.",
                    name,
                )
            plugins.append(ep)
        return plugins

    # ── loading ───────────────────────────────────────────────────────────────

    async def load_all(
        self,
        bot: "commands.Bot",
        registry: Dict[str, Dict],
    ) -> tuple[List[ExternalPlugin], List[ExternalPlugin]]:
        """Load all enabled external plugins.

        Returns ``(loaded, failed)`` lists of :class:`ExternalPlugin`.
        """
        # Add the ext_plugins directory root to sys.path once.
        self._add_to_syspath()

        plugins = self.discover(registry)
        loaded: List[ExternalPlugin] = []
        failed: List[ExternalPlugin] = []

        for ep in plugins:
            success = await self._load_one(bot, ep)
            if success:
                loaded.append(ep)
            else:
                failed.append(ep)

        return loaded, failed

    async def _load_one(self, bot: "commands.Bot", ep: ExternalPlugin) -> bool:
        """Load a single external plugin.  Returns True on success."""
        # Ensure the plugin's parent is importable.
        self._register_module_path(ep)

        try:
            await bot.load_extension(ep.module_path)
            ep.loaded = True
            log.info(
                "Loaded external plugin '%s' v%s from %s",
                ep.display_name,
                ep.version,
                ep.path,
            )
            return True
        except Exception as exc:
            ep.loaded = False
            ep.error = str(exc)
            log.error(
                "Failed to load external plugin '%s': %s",
                ep.name,
                exc,
                exc_info=True,
            )
            return False

    async def reload_one(self, bot: "commands.Bot", name: str, registry: Dict[str, Dict]) -> ExternalPlugin:
        """Reload a single plugin by name.  Returns updated ExternalPlugin."""
        plugins = self.discover({name: registry[name]}) if name in registry else []
        if not plugins:
            raise ValueError(f"External plugin '{name}' not found in registry.")
        ep = plugins[0]
        try:
            if ep.module_path in bot.extensions:
                await bot.reload_extension(ep.module_path)
            else:
                await bot.load_extension(ep.module_path)
            ep.loaded = True
        except Exception as exc:
            ep.loaded = False
            ep.error = str(exc)
            raise
        return ep

    # ── sys.path helpers ──────────────────────────────────────────────────────

    def _add_to_syspath(self) -> None:
        """Add the ext_plugins root to sys.path if not already present."""
        root = str(self.plugins_dir)
        if root not in sys.path:
            sys.path.insert(0, root)

    def _register_module_path(self, ep: ExternalPlugin) -> None:
        """Ensure the ``_vp_ext`` namespace package exists in sys.modules."""
        import types
        if _EXT_NAMESPACE not in sys.modules:
            pkg = types.ModuleType(_EXT_NAMESPACE)
            pkg.__path__ = [str(self.plugins_dir)]  # type: ignore[attr-defined]
            pkg.__package__ = _EXT_NAMESPACE
            sys.modules[_EXT_NAMESPACE] = pkg
