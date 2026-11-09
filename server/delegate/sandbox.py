"""Docker orchestration for sandbox containers (one container per task)."""

from __future__ import annotations

import io
import json
import logging
import shutil
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import IO

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container

from .config import get_settings

log = logging.getLogger(__name__)

SANDBOX_UID = 10001
LABEL_TASK = "delegate.task"
LABEL_USER = "delegate.user"
PATCH_PATH = "/out/changes.patch"
OUTPUTS_PATH = "/out/outputs.tar.gz"
MAX_PATCH_BYTES = 50 * 1024 * 1024


@dataclass
class SandboxSpec:
    task_id: str
    user_id: int
    spec: dict  # serialised to /task/spec.json (readable by the agent; no platform secrets)
    files: dict[str, bytes]  # relative path -> content, placed under /task/files
    uploads: dict[str, Path]  # upload id -> file on the host, placed under /task/uploads
    gateway_key: str


@lru_cache(maxsize=1)
def docker_client() -> docker.DockerClient:
    settings = get_settings()
    if settings.docker_host:
        return docker.DockerClient(base_url=settings.docker_host)
    return docker.from_env()


def limits() -> dict:
    s = get_settings()
    return {"memory": s.sandbox_memory, "cpus": s.sandbox_cpus, "pids": s.sandbox_pids, "network": s.sandbox_network}


def _task_archive(spec: SandboxSpec) -> IO[bytes]:
    buf = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    with tarfile.open(fileobj=buf, mode="w") as tar:

        def add(name: str, data: bytes | None, mode: int) -> None:
            info = tarfile.TarInfo(name)
            info.uid = info.gid = SANDBOX_UID
            info.mode = mode
            if data is None:
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

        add("task/spec.json", json.dumps(spec.spec, ensure_ascii=False).encode(), 0o644)
        if spec.files:
            add("task/files", None, 0o755)
            seen_dirs: set[str] = set()
            for rel, content in spec.files.items():
                parts = rel.split("/")
                for i in range(1, len(parts)):
                    d = "task/files/" + "/".join(parts[:i])
                    if d not in seen_dirs:
                        seen_dirs.add(d)
                        add(d, None, 0o755)
                add("task/files/" + rel, content, 0o644)
        if spec.uploads:
            add("task/uploads", None, 0o755)
            for upload_id, path in spec.uploads.items():
                info = tarfile.TarInfo("task/uploads/" + upload_id)
                info.uid = info.gid = SANDBOX_UID
                info.mode = 0o644
                info.size = path.stat().st_size
                with path.open("rb") as fh:
                    tar.addfile(info, fh)
    buf.seek(0)
    return buf


def create_and_start(spec: SandboxSpec) -> Container:
    s = get_settings()
    client = docker_client()
    name = f"delegate-{spec.task_id}"
    try:  # leftover from a crashed worker
        client.containers.get(name).remove(force=True)
    except NotFound:
        pass
    env_var = "DELEGATE_LLM_API_KEY" if (spec.spec.get("auth") or {}).get("mode") == "byok" else "DELEGATE_GATEWAY_KEY"
    volumes = None
    if s.harness_volume:
        # Updated CLIs land here and take PATH priority over the ones baked into the image.
        volumes = {s.harness_volume: {"bind": "/opt/harness", "mode": "ro"}}
    container = client.containers.create(
        s.sandbox_image,
        name=name,
        init=True,
        user="agent",
        working_dir="/workspace",
        environment={
            **s.sandbox_agent_env,
            env_var: spec.gateway_key,
            "DELEGATE_TASK_ID": spec.task_id,
            "PATH": "/opt/harness/bin:/usr/local/bin:/usr/bin:/bin",
        },
        volumes=volumes,
        network=s.sandbox_network,
        mem_limit=s.sandbox_memory,
        memswap_limit=s.sandbox_memory,
        nano_cpus=int(s.sandbox_cpus * 1e9),
        pids_limit=s.sandbox_pids,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        labels={LABEL_TASK: spec.task_id, LABEL_USER: str(spec.user_id)},
    )
    with _task_archive(spec) as archive:
        container.put_archive("/", archive)
    container.start()
    return container


def stream_lines(container: Container) -> Iterator[tuple[str, str]]:
    """Yield (docker timestamp, line) for the container's combined output until it exits."""
    buffer = b""
    for chunk in container.logs(stream=True, follow=True, stdout=True, stderr=True, timestamps=True):
        buffer += chunk
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            yield _split_ts(raw.decode("utf-8", errors="replace"))
    if buffer.strip():
        yield _split_ts(buffer.decode("utf-8", errors="replace"))


def _split_ts(line: str) -> tuple[str, str]:
    ts, sep, rest = line.partition(" ")
    if sep and len(ts) >= 20 and ts[4] == "-" and "T" in ts:
        return ts, rest
    return "", line


def stop(container: Container, grace_s: int) -> None:
    try:
        container.stop(timeout=grace_s)
    except NotFound:
        pass
    except APIError as exc:
        log.warning("stopping %s failed: %s", container.name, exc)


def wait_exit(container: Container) -> int | None:
    try:
        return int(container.wait(timeout=60).get("StatusCode"))
    except Exception as exc:  # noqa: BLE001 - docker raises several transport errors here
        log.warning("waiting for %s failed: %s", container.name, exc)
        return None


def fetch_file(container: Container, path: str, dest: Path, max_bytes: int) -> int | None:
    """Copy one regular file out of the (stopped) container. Returns its size, or None if absent/too big."""
    try:
        stream, stat = container.get_archive(path)
    except NotFound:
        return None
    if stat.get("size", 0) > max_bytes:
        log.warning("%s in %s too large (%s bytes)", path, container.name, stat.get("size"))
        return None
    with tempfile.TemporaryFile() as tmp:
        for chunk in stream:
            tmp.write(chunk)
        tmp.seek(0)
        with tarfile.open(fileobj=tmp) as tar:
            member = next((m for m in tar if m.isfile()), None)
            if member is None:
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, dest.open("wb") as out:  # type: ignore[union-attr]
                shutil.copyfileobj(src, out)
    return dest.stat().st_size


def remove(container: Container) -> None:
    try:
        container.remove(force=True)
    except NotFound:
        pass
    except APIError as exc:
        log.warning("removing %s failed: %s", container.name, exc)


def find_task_containers() -> dict[str, Container]:
    client = docker_client()
    return {c.labels.get(LABEL_TASK): c for c in client.containers.list(all=True, filters={"label": LABEL_TASK})}


def ping() -> tuple[bool, str]:
    try:
        client = docker_client()
        client.ping()
        image_ok = True
        try:
            client.images.get(get_settings().sandbox_image)
        except NotFound:
            image_ok = False
        return True, "ok" if image_ok else f"image {get_settings().sandbox_image} not found"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
