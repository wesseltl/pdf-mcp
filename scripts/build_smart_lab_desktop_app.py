"""Build and smoke-test a standalone Smart Lab Index desktop archive."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import BinaryIO

import PyInstaller.__main__

from smart_lab_index import __version__

ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build" / "smart-lab-desktop-app"
APP_DIST = BUILD_ROOT / "dist"
FINAL_DIST = ROOT / "dist"
APP_NAME = "smart-lab-index"
_SMOKE_ENVIRONMENT = {
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "SystemRoot",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "WINDIR",
}


def platform_label() -> str:
    system = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(
        platform.system(), platform.system().lower()
    )
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    return f"{system}-{architecture}"


def executable_path() -> Path:
    if sys.platform == "darwin":
        return APP_DIST / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    suffix = ".exe" if sys.platform == "win32" else ""
    return APP_DIST / f"{APP_NAME}{suffix}"


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def smoke_test(executable: Path) -> None:
    port = available_port()
    sample = ROOT / "examples" / "smart_lab_index" / "sample_lab"
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryFile() as output:
        database = Path(temporary) / "index.db"
        environment = {
            key: value for key, value in os.environ.items() if key in _SMOKE_ENVIRONMENT
        }
        environment["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            [
                str(executable),
                str(sample),
                "--database",
                str(database),
                "--source-id",
                "desktop-smoke",
                "--no-egress",
                "--no-browser",
                "--index-on-start",
                "--port",
                str(port),
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            env=environment,
        )
        try:
            _wait_for_expected_index(process, output, port)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _wait_for_expected_index(
    process: subprocess.Popen[bytes],
    output: BinaryIO,
    port: int,
) -> None:
    deadline = time.monotonic() + 45
    token: str | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = _startup_detail(output)
            message = (
                f"desktop app exited during startup with code {process.returncode}"
            )
            raise RuntimeError(f"{message}:\n{detail}" if detail else message)
        try:
            if token is None:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/", timeout=1
                ) as response:
                    page = response.read().decode("utf-8")
                if "<title>Smart Lab Index</title>" not in page:
                    raise RuntimeError("desktop app returned an unexpected page")
                match = re.search(
                    r'name="smart-lab-session" content="([^"]+)"',
                    page,
                )
                if not match:
                    raise RuntimeError("desktop app did not provide a browser session")
                token = match.group(1)
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/state",
                headers={"X-Smart-Lab-Session": token},
            )
            with urllib.request.urlopen(request, timeout=1) as response:
                state = json.load(response)
            if state["operation"]["state"] == "INDEXING":
                time.sleep(0.2)
                continue
            summary = state["summary"]
            expected = {
                "sources": 4,
                "documents": 4,
                "entities": 4,
                "active_assertions": 3,
                "open_issues": 1,
            }
            observed = {key: summary.get(key) for key in expected}
            if observed != expected:
                raise RuntimeError(
                    f"desktop app returned unexpected synthetic counts: {observed}"
                )
            if not state["source"]["no_egress"]:
                raise RuntimeError("desktop app did not preserve no-egress mode")
            return
        except OSError:
            time.sleep(0.4)
    detail = _startup_detail(output)
    message = "desktop app did not complete its smoke index within 45 seconds"
    raise RuntimeError(f"{message}:\n{detail}" if detail else message)


def _startup_detail(output: BinaryIO) -> str:
    output.flush()
    output.seek(0)
    return output.read().decode("utf-8", errors="replace").strip()


def archive_app() -> Path:
    staging = BUILD_ROOT / "archive" / APP_NAME
    shutil.rmtree(staging.parent, ignore_errors=True)
    staging.mkdir(parents=True)

    app_bundle = APP_DIST / f"{APP_NAME}.app"
    if app_bundle.exists():
        shutil.copytree(app_bundle, staging / app_bundle.name)
        launch_instruction = f"Double-click {APP_NAME}.app."
    else:
        executable = executable_path()
        shutil.copy2(executable, staging / executable.name)
        launch_instruction = f"Double-click {executable.name}."

    (staging / "README.txt").write_text(
        "Smart Lab Index local operator app\n"
        "==================================\n\n"
        f"{launch_instruction}\n"
        "Choose a laboratory folder in the system dialog. The local browser workspace opens "
        "and indexes supported files without modifying them. Use Change folder to switch sources "
        "and Stop app when finished.\n\n"
        "The desktop flow starts in no-egress mode and serves only bundled assets on loopback. "
        "Linux folder selection requires zenity, kdialog, or yad from the desktop environment.\n\n"
        "This build is unsigned. Your operating system may ask you to confirm that you want to "
        "open it.\n",
        encoding="utf-8",
    )

    FINAL_DIST.mkdir(exist_ok=True)
    archive = FINAL_DIST / f"{APP_NAME}-v{__version__}-{platform_label()}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in staging.parent.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(staging.parent))
    return archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()

    shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    APP_DIST.mkdir(parents=True)
    bundle_mode = "--onedir" if sys.platform == "darwin" else "--onefile"
    PyInstaller.__main__.run(
        [
            str(ROOT / "smart_lab_index" / "web_app.py"),
            f"--name={APP_NAME}",
            bundle_mode,
            "--windowed",
            "--noconfirm",
            "--clean",
            f"--distpath={APP_DIST}",
            f"--workpath={BUILD_ROOT / 'work'}",
            f"--specpath={BUILD_ROOT / 'spec'}",
            "--collect-data=smart_lab_index.web_ui",
        ]
    )

    executable = executable_path()
    if not executable.exists():
        raise FileNotFoundError(f"PyInstaller did not create {executable}")
    if not args.skip_smoke:
        smoke_test(executable)

    archive = archive_app()
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
