"""Install the current release of every built-in CLI into the shared harness volume.

Package names are fixed; versions are not. The next sandbox starts with whatever this just installed.
"""

from __future__ import annotations

from collections.abc import Callable

from .config import get_settings
from .harness import NPM_PACKAGES

NODE_IMAGE = "node:22-bookworm-slim"


def install_command() -> list[str]:
    packages = " ".join(NPM_PACKAGES)
    script = (
        f"npm install -g --prefix /opt/harness {packages}"
        " && chmod -R a+rX /opt/harness"
    )
    return ["bash", "-lc", script]


def update_clis(run: Callable[[list[str], str], str] | None = None) -> str:
    volume = get_settings().harness_volume
    if not volume:
        raise RuntimeError("DELEGATE_HARNESS_VOLUME is empty; there is nowhere to install the CLIs")
    command = install_command()
    if run is not None:
        return run(command, volume)
    from .sandbox import docker_client

    client = docker_client()
    output = client.containers.run(
        NODE_IMAGE,
        command,
        volumes={volume: {"bind": "/opt/harness", "mode": "rw"}},
        remove=True,
        user="root",
    )
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output or "updated")
