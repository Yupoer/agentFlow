from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERMES_AGENT_ROOT = Path.home() / ".hermes" / "hermes-agent"


class ToolRegistryError(RuntimeError):
    pass


class HermesToolRegistry:
    """Best-effort adapter around Hermes' real toolset registry/config.

    Prefer importing Hermes source when available; fall back to `hermes tools list`
    so the workflow runtime can still make deterministic availability decisions
    outside the main Hermes process.
    """

    def __init__(self, *, hermes_root: str | Path | None = None, platform: str = "cli") -> None:
        self.hermes_root = Path(hermes_root) if hermes_root else HERMES_AGENT_ROOT
        self.platform = platform
        self._toolsets: dict[str, bool] | None = None

    def toolsets(self) -> dict[str, bool]:
        if self._toolsets is None:
            self._toolsets = self._load_toolsets()
        return dict(self._toolsets)

    def is_available(self, toolset: str) -> bool:
        return bool(self.toolsets().get(_canonical_toolset(toolset), False))

    def missing(self, toolsets: list[str] | tuple[str, ...]) -> list[str]:
        available = self.toolsets()
        missing = []
        for toolset in toolsets:
            canonical = _canonical_toolset(str(toolset))
            if not available.get(canonical, False):
                missing.append(str(toolset))
        return sorted(set(missing))

    def _load_toolsets(self) -> dict[str, bool]:
        # CLI output includes the user's enabled/disabled state; source import is
        # only a fallback for test/dev environments where the Hermes CLI is absent.
        loaded = self._load_from_cli()
        if loaded:
            return loaded
        loaded = self._load_from_hermes_source()
        if loaded:
            return loaded
        return {}

    def _load_from_hermes_source(self) -> dict[str, bool]:
        if not self.hermes_root.exists():
            return {}
        if str(self.hermes_root) not in sys.path:
            sys.path.insert(0, str(self.hermes_root))
        try:
            from toolsets import get_all_toolsets  # type: ignore
        except Exception:
            return {}
        try:
            names = get_all_toolsets()
        except Exception:
            return {}
        if isinstance(names, dict):
            return {_canonical_toolset(name): True for name in names}
        return {_canonical_toolset(str(name)): True for name in names}

    def _load_from_cli(self) -> dict[str, bool]:
        try:
            proc = subprocess.run(
                ["hermes", "tools", "list"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=20,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if proc.returncode != 0:
            return {}
        output: dict[str, bool] = {}
        for line in proc.stdout.splitlines():
            match = re.search(r"(?P<enabled>[✓✗])\s+(?:enabled|disabled)\s+(?P<name>[a-zA-Z0-9_-]+)\b", line)
            if match:
                output[_canonical_toolset(match.group("name"))] = match.group("enabled") == "✓"
        return output


def _canonical_toolset(toolset: str) -> str:
    aliases = {
        "discord": "messaging",
        "discord_admin": "messaging",
        "telegram": "messaging",
        "slack": "messaging",
        "send_message": "messaging",
        "execute_code": "code_execution",
        "delegation": "delegation",
    }
    return aliases.get(toolset, toolset)
