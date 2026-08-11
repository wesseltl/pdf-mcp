"""Build and smoke-test a standalone pdf-mcp browser app archive."""
from __future__ import annotations

import argparse
import importlib.metadata
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build" / "desktop-app"
APP_DIST = BUILD_ROOT / "dist"
FINAL_DIST = ROOT / "dist"


def platform_label() -> str:
    system = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(
        platform.system(), platform.system().lower()
    )
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    return f"{system}-{architecture}"


def executable_path() -> Path:
    if sys.platform == "darwin":
        return APP_DIST / "pdf-mcp-app.app" / "Contents" / "MacOS" / "pdf-mcp-app"
    suffix = ".exe" if sys.platform == "win32" else ""
    return APP_DIST / f"pdf-mcp-app{suffix}"


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def smoke_test(executable: Path) -> None:
    port = available_port()
    process = subprocess.Popen(
        [str(executable), "--no-browser", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"desktop app exited during startup with code {process.returncode}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                    page = response.read()
                if b"Turn a PDF or Word table into a spreadsheet" not in page:
                    raise RuntimeError("desktop app returned an unexpected page")
                return
            except OSError:
                time.sleep(0.4)
        raise RuntimeError("desktop app did not start within 30 seconds")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def archive_app(version: str) -> Path:
    label = platform_label()
    staging = BUILD_ROOT / "archive" / "pdf-mcp-app"
    shutil.rmtree(staging.parent, ignore_errors=True)
    staging.mkdir(parents=True)

    app_bundle = APP_DIST / "pdf-mcp-app.app"
    if app_bundle.exists():
        shutil.copytree(app_bundle, staging / app_bundle.name)
        launch_instruction = "Double-click pdf-mcp-app.app."
    else:
        executable = executable_path()
        shutil.copy2(executable, staging / executable.name)
        launch_instruction = f"Double-click {executable.name}."

    (staging / "README.txt").write_text(
        "pdf-mcp simple document converter\n"
        "=================================\n\n"
        f"{launch_instruction}\n"
        "Your browser opens automatically. Choose a PDF or Word document, select an output, "
        "and click Convert document. Use Stop app in the browser when finished.\n\n"
        "Files are processed only on this computer and temporary copies are deleted after "
        "conversion. Scanned or photographed pages are not supported.\n\n"
        "This community beta is unsigned. Your operating system may ask you to confirm that "
        "you want to open it.\n",
        encoding="utf-8",
    )

    FINAL_DIST.mkdir(exist_ok=True)
    archive = FINAL_DIST / f"pdf-mcp-app-v{version}-{label}.zip"
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
    PyInstaller.__main__.run([
        str(ROOT / "pdf_mcp" / "web_app.py"),
        "--name=pdf-mcp-app",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        f"--distpath={APP_DIST}",
        f"--workpath={BUILD_ROOT / 'work'}",
        f"--specpath={BUILD_ROOT / 'spec'}",
        "--collect-data=pdf_mcp.web_ui",
    ])

    executable = executable_path()
    if not executable.exists():
        raise FileNotFoundError(f"PyInstaller did not create {executable}")
    if not args.skip_smoke:
        smoke_test(executable)

    version = importlib.metadata.version("pdf-agent-mcp")
    archive = archive_app(version)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
