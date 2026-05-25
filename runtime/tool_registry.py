from __future__ import annotations

import os
import re
import shlex
import subprocess


class ToolRegistryError(RuntimeError):
    pass


class ToolRegistry:
    """Best-effort adapter around a host application's toolset registry.

    This runtime is host-agnostic. Tool availability can be supplied by either:

    - `AGENTFLOW_TOOLSETS`: comma-separated enabled toolsets.
    - `AGENTFLOW_TOOLS_COMMAND`: command that prints enabled/disabled toolsets.

    If neither is configured, no external toolsets are assumed available.
    """

    def __init__(self, *, tools_command: str | None = None, platform: str = "cli") -> None:
        self.tools_command = tools_command or os.environ.get("AGENTFLOW_TOOLS_COMMAND")
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
        loaded = self._load_from_env()
        if loaded:
            return loaded
        loaded = self._load_from_command()
        if loaded:
            return loaded
        return {}

    def _load_from_env(self) -> dict[str, bool]:
        raw = os.environ.get("AGENTFLOW_TOOLSETS", "")
        output: dict[str, bool] = {}
        for name in raw.split(","):
            name = name.strip()
            if name:
                output[_canonical_toolset(name)] = True
        return output

    def _load_from_command(self) -> dict[str, bool]:
        if not self.tools_command:
            return {}
        try:
            proc = subprocess.run(
                shlex.split(self.tools_command),
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
                continue
            bare = line.strip()
            if re.fullmatch(r"[a-zA-Z0-9_-]+", bare):
                output[_canonical_toolset(bare)] = True
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
