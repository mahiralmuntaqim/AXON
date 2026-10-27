"""Dockerized attacker toolbox (Option A) — run allowlisted tools inside a container.

The host usually has none of the pentest tools installed, so an allowlisted command like
``ffuf -u http://web/ ...`` fails with "command not found". This module runs each command
*inside* a toolbox container (built from ``toolbox/Dockerfile``) that has the tools preinstalled
and is joined to the challenge's Docker network, so the target is reachable by its compose
service name.

Two pieces:

* :class:`DockerToolbox` — lifecycle: ensure the image exists (optionally build it), start an
  idle container, connect it to the challenge network(s), tear it down.
* :class:`DockerExecBackend` — a :class:`~axon.execution.tools.Target` that runs one action via
  ``docker exec`` and reads the flag from the real output (same rule as the host backend).

Authorization is unchanged: the sandbox allowlist is still enforced in :class:`ToolRunner`
*before* a command reaches this backend. This only changes *where* an already-permitted,
documented command runs — never *what* runs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, Optional

from .result import ActionResult
from .tools import Action, Target, result_from_output


class ToolboxError(RuntimeError):
    """The toolbox image/container could not be prepared."""


class DockerToolbox:
    """Lifecycle for the attacker-toolbox container."""

    def __init__(
        self,
        image: str,
        *,
        name: str,
        build_context: Optional[Path] = None,
        build: bool = False,
    ) -> None:
        self.image = image
        self.name = name
        self.build_context = Path(build_context) if build_context else None
        self.build = build

    # -- helpers --------------------------------------------------------------------------
    @staticmethod
    def _run(args: list[str], *, timeout: int = 1200) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)

    def _image_exists(self) -> bool:
        return self._run(["image", "inspect", self.image], timeout=60).returncode == 0

    # -- lifecycle ------------------------------------------------------------------------
    def ensure_image(self) -> None:
        """Build the image if it is missing and building is allowed."""
        if self._image_exists():
            return
        if not self.build or self.build_context is None:
            raise ToolboxError(
                f"toolbox image {self.image!r} not found and build is disabled. "
                f"Build it with:  docker build -t {self.image} {self.build_context or '<ctx>'}"
            )
        r = self._run(["build", "-t", self.image, str(self.build_context)])
        if r.returncode != 0:
            raise ToolboxError(f"toolbox image build failed: {r.stderr[-800:]}")

    def start(self, networks: Iterable[str] = ()) -> None:
        """Start a fresh idle container and connect it to each challenge network."""
        self._run(["rm", "-f", self.name], timeout=60)  # clear any stale container
        r = self._run(["run", "-d", "--name", self.name, self.image, "sleep", "infinity"], timeout=120)
        if r.returncode != 0:
            raise ToolboxError(f"could not start toolbox container: {r.stderr[-500:]}")
        for net in networks:
            c = self._run(["network", "connect", net, self.name], timeout=60)
            if c.returncode != 0 and "already exists" not in (c.stderr or ""):
                raise ToolboxError(f"could not join network {net!r}: {c.stderr[-300:]}")

    def stop(self) -> None:
        self._run(["rm", "-f", self.name], timeout=60)


class DockerExecBackend(Target):
    """Run one allowlisted action inside the toolbox container via ``docker exec``."""

    def __init__(self, container: str, *, flag: Optional[str] = None, timeout_s: float = 120.0) -> None:
        self.container = container
        self.flag = flag
        self.timeout_s = timeout_s

    def observe(self, action: Action) -> ActionResult:
        cmd = ["docker", "exec", self.container, "sh", "-lc", action.command]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s)
        except subprocess.TimeoutExpired as exc:
            # ToolRunner turns this into a timed-out ActionResult (classified as a tool error).
            raise TimeoutError(str(exc)) from exc
        return result_from_output(
            action, exit_code=proc.returncode,
            stdout=proc.stdout or "", stderr=proc.stderr or "", flag=self.flag,
        )
