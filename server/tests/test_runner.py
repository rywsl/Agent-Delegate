"""The in-sandbox runner's workspace handling, run against real git in a temp directory."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[2] / "sandbox" / "runner.py"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("sandbox_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, sub in (("WORKSPACE", "workspace"), ("TASK_DIR", "task"), ("OUT_DIR", "out"), ("OUTPUTS", "outputs")):
        path = tmp_path / sub
        path.mkdir()
        monkeypatch.setattr(module, name, path)
    monkeypatch.setattr(module, "PATCH_FILE", tmp_path / "out" / "changes.patch")
    monkeypatch.setattr(module, "OUTPUTS_FILE", tmp_path / "out" / "outputs.tar.gz")
    # hermetic git, like the sandbox image (no host autocrlf etc.)
    (tmp_path / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    emitted = []
    monkeypatch.setattr(module, "emit", emitted.append)
    module.emitted = emitted
    (tmp_path / "task" / "uploads").mkdir()
    return module


def _tar(members: list[tarfile.TarInfo | tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for m in members:
            if isinstance(m, tarfile.TarInfo):
                tar.addfile(m)
            else:
                info = tarfile.TarInfo(m[0])
                info.size = len(m[1])
                tar.addfile(info, io.BytesIO(m[1]))
    return buf.getvalue()


def test_upload_extraction_is_confined(runner):
    evil_link = tarfile.TarInfo("escape")
    evil_link.type = tarfile.SYMTYPE
    evil_link.linkname = "../../outside"
    ok_link = tarfile.TarInfo("docs/link")
    ok_link.type = tarfile.SYMTYPE
    ok_link.linkname = "../src/app.py"
    (runner.TASK_DIR / "uploads" / "u1").write_bytes(_tar([
        ("src/app.py", b"print(1)\n"), ("../evil.txt", b"x"), ("/abs.txt", b"x"), evil_link, ok_link,
    ]))
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("data/table.csv", "a,b\n")
        zf.writestr("../../zipslip.txt", "x")
    (runner.TASK_DIR / "uploads" / "u2").write_bytes(zbuf.getvalue())
    (runner.TASK_DIR / "uploads" / "u3").write_bytes(b"\x00raw")

    assert runner.place_upload({"id": "u1", "kind": "tgz", "dest": "."}) == 1
    assert runner.place_upload({"id": "u2", "kind": "zip", "dest": "vendor"}) == 1
    assert runner.place_upload({"id": "u3", "kind": "file", "dest": "bin/blob.dat"}) == 1
    ws = runner.WORKSPACE
    assert (ws / "src/app.py").read_text() == "print(1)\n"
    assert (ws / "vendor/data/table.csv").exists() and (ws / "bin/blob.dat").read_bytes() == b"\x00raw"
    assert not (ws.parent / "evil.txt").exists() and not (ws.parent / "zipslip.txt").exists()
    assert not (ws / "escape").exists()
    assert (ws / "docs/link").is_symlink() or not (ws / "docs/link").exists()  # symlinks may be unsupported on Windows


def test_patch_and_outputs_roundtrip(runner, tmp_path):
    (runner.TASK_DIR / "uploads" / "u1").write_bytes(_tar([("app.py", b"print(1)\n"), ("keep.txt", b"same\n")]))
    files = runner.TASK_DIR / "files"
    (files / "notes").mkdir(parents=True)
    (files / "notes" / "brief.md").write_text("inline file")
    baseline = runner.prepare_workspace({"uploads": [{"id": "u1", "kind": "tgz", "dest": "."}]})
    ws = runner.WORKSPACE
    assert (ws / "notes/brief.md").read_text() == "inline file"

    # what an agent would do
    (ws / "app.py").write_bytes(b"print(2)\n")
    (ws / "new.bin").write_bytes(bytes(range(256)))
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "junk.js").write_text("ignored")
    (runner.OUTPUTS / "report.md").write_text("# done")

    stats = runner.collect_patch(baseline)
    assert stats["files"] == 2 and set(stats["paths"]) == {"app.py", "new.bin"}
    patch = runner.PATCH_FILE.read_bytes()
    assert b"GIT binary patch" in patch and b"node_modules" not in patch

    # the patch applies cleanly onto a copy of the original inputs (what the local agent does)
    local = tmp_path / "local"
    local.mkdir()
    (local / "app.py").write_bytes(b"print(1)\n")
    (local / "keep.txt").write_bytes(b"same\n")
    import subprocess

    subprocess.run(["git", "apply", str(runner.PATCH_FILE)], cwd=local, check=True)
    assert (local / "app.py").read_bytes() == b"print(2)\n" and (local / "new.bin").read_bytes() == bytes(range(256))

    outputs = runner.collect_outputs(1024 * 1024)
    assert outputs["count"] == 1 and outputs["files"] == [{"path": "report.md", "size": 6}]
    with tarfile.open(runner.OUTPUTS_FILE) as tar:
        assert tar.getnames() == ["report.md"]
    assert runner.collect_outputs(3)["count"] == 0  # over the limit: nothing returned


def test_sdk_harness_needs_no_external_command(runner):
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "sandbox" / "harness.py"
    spec = importlib.util.spec_from_file_location("sandbox_harness", path)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    assert "sdk" not in harness.DEFAULT_COMMANDS
    assert {"claude-code", "codex", "gemini", "grok", "pi", "deepseek"} <= set(harness.DEFAULT_COMMANDS)
