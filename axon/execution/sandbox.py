"""Sandbox allowlist enforcement (SEGMENT 10 / SEGMENT 12).

AXON's ethics position: it only touches systems it is authorized to test — Vulhub containers,
CTF/XBOW challenge containers — nothing live, nothing third-party. Every action is checked here
*before* it can run:

* the target host must be on the allowed list (literal hostnames or private CIDR ranges);
* the tool must be a known, documented tool on the allowlist (no novel payload generation);
* web search is hard-disabled during evaluation (the biggest contamination channel, SEGMENT 12).

A violation raises :class:`SandboxViolation` and the action never runs.
"""

from __future__ import annotations

import ipaddress
import shlex
from typing import Iterable, Optional


class SandboxViolation(RuntimeError):
    """Raised when an action would touch a disallowed host or use a disallowed tool."""


class Sandbox:
    def __init__(
        self,
        allowed_target_hosts: Iterable[str],
        allowed_tools: Iterable[str],
        *,
        allow_web_search: bool = False,
    ) -> None:
        self.allow_web_search = allow_web_search
        self.allowed_tools = {t.lower() for t in allowed_tools}
        self._literal_hosts: set[str] = set()
        self._networks: list[ipaddress._BaseNetwork] = []
        for h in allowed_target_hosts:
            try:
                self._networks.append(ipaddress.ip_network(h, strict=False))
            except ValueError:
                self._literal_hosts.add(h.lower())

    @classmethod
    def from_config(cls, cfg: dict) -> "Sandbox":
        ec = cfg.get("execution", {})
        return cls(
            ec.get("allowed_target_hosts", ["127.0.0.1", "localhost"]),
            ec.get("allowed_tools", []),
            allow_web_search=bool(ec.get("allow_web_search", False)),
        )

    # -- host ----------------------------------------------------------------------------
    def host_allowed(self, host: str) -> bool:
        if not host:
            return False
        h = host.strip().lower()
        if h in self._literal_hosts:
            return True
        try:
            ip = ipaddress.ip_address(h)
        except ValueError:
            return False  # a non-literal, non-IP hostname that isn't explicitly allowed
        return any(ip in net for net in self._networks)

    # -- tool ----------------------------------------------------------------------------
    def tool_allowed(self, tool: str) -> bool:
        return tool.strip().lower() in self.allowed_tools

    def command_tool(self, command: str) -> Optional[str]:
        """The invoked binary (first shell token) of a command string, or None."""
        try:
            parts = shlex.split(command)
        except ValueError:
            return None
        return parts[0] if parts else None

    # -- the gate ------------------------------------------------------------------------
    def validate(self, *, host: str, command: str) -> None:
        """Raise :class:`SandboxViolation` if this action is not permitted."""
        if not self.host_allowed(host):
            raise SandboxViolation(
                f"target host {host!r} is not on the sandbox allowlist; refusing to run"
            )
        tool = self.command_tool(command)
        if tool is None:
            raise SandboxViolation(f"could not parse a tool from command {command!r}")
        # Strip a path prefix: /usr/bin/nmap -> nmap
        base = tool.rsplit("/", 1)[-1]
        if not self.tool_allowed(base):
            raise SandboxViolation(
                f"tool {base!r} is not on the allowlist {sorted(self.allowed_tools)}; "
                "AXON composes documented tools only and generates no novel payloads"
            )

    def web_search_allowed(self) -> bool:
        return self.allow_web_search
