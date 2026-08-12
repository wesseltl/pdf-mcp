"""Build and smoke-test a standalone Smart Lab Index desktop archive."""

from __future__ import annotations

import argparse
import hashlib
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

from smart_lab_index import __version__

ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build" / "smart-lab-desktop-app"
APP_DIST = BUILD_ROOT / "dist"
FINAL_DIST = ROOT / "dist"
APP_NAME = "smart-lab-index"
APP_DISPLAY_NAME = "Smart Lab Index"
APP_PUBLISHER = "Wessel ter Laak"
SIGNING_REQUIRED_ENV = "SMART_LAB_REQUIRE_SIGNING"
_SMOKE_ENVIRONMENT = {
    "ALLUSERSPROFILE",
    "APPDATA",
    "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)",
    "COMMONPROGRAMW6432",
    "COMSPEC",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LC_ALL",
    "LOCALAPPDATA",
    "OS",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "PUBLIC",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERDOMAIN",
    "USERNAME",
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
    return APP_DIST / APP_NAME / f"{APP_NAME}{suffix}"


def signing_target() -> Path:
    if sys.platform == "darwin":
        return APP_DIST / f"{APP_NAME}.app"
    return executable_path()


def sign_desktop_app() -> str:
    """Sign the platform artifact when release credentials are configured."""
    target = signing_target()
    if sys.platform == "win32":
        return sign_windows_file(target)

    if sys.platform == "darwin":
        identity = os.environ.get("SMART_LAB_MACOS_SIGNING_IDENTITY")
        if not identity:
            return "unsigned"
        subprocess.run(
            [
                "codesign",
                "--deep",
                "--force",
                "--options",
                "runtime",
                "--timestamp",
                "--sign",
                identity,
                str(target),
            ],
            check=True,
        )
        subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(target)],
            check=True,
        )
        profile = os.environ.get("SMART_LAB_MACOS_NOTARY_PROFILE")
        if profile:
            _notarize_macos_app(target, profile)
            return "notarized"
        return "signed"

    return "unsigned"


def sign_windows_file(target: Path) -> str:
    """Authenticode-sign and verify one Windows release artifact when configured."""
    certificate_value = os.environ.get("SMART_LAB_WINDOWS_CERTIFICATE_PATH")
    if not certificate_value:
        return "unsigned"
    certificate = Path(certificate_value).expanduser().resolve(strict=True)
    password = os.environ.get("SMART_LAB_WINDOWS_CERTIFICATE_PASSWORD")
    command = [
        str(_windows_signtool()),
        "sign",
        "/fd",
        "SHA256",
        "/tr",
        os.environ.get(
            "SMART_LAB_WINDOWS_TIMESTAMP_URL",
            "http://timestamp.digicert.com",
        ),
        "/td",
        "SHA256",
        "/f",
        str(certificate),
    ]
    if password:
        command.extend(["/p", password])
    command.append(str(target))
    subprocess.run(command, check=True)
    subprocess.run(
        [str(_windows_signtool()), "verify", "/pa", "/v", str(target)],
        check=True,
    )
    return "signed"


def _windows_signtool() -> Path:
    discovered = shutil.which("signtool.exe") or shutil.which("signtool")
    if discovered:
        return Path(discovered)
    program_files = os.environ.get("ProgramFiles(x86)")
    if program_files:
        candidates = sorted(
            Path(program_files).glob("Windows Kits/10/bin/*/x64/signtool.exe"),
            reverse=True,
        )
        if candidates:
            return candidates[0]
    raise FileNotFoundError("signtool.exe was not found in the Windows SDK")


def _notarize_macos_app(target: Path, profile: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        submission = Path(temporary) / f"{APP_NAME}.zip"
        subprocess.run(
            ["ditto", "-c", "-k", "--keepParent", str(target), str(submission)],
            check=True,
        )
        subprocess.run(
            [
                "xcrun",
                "notarytool",
                "submit",
                str(submission),
                "--keychain-profile",
                profile,
                "--wait",
            ],
            check=True,
        )
    subprocess.run(["xcrun", "stapler", "staple", str(target)], check=True)
    subprocess.run(["xcrun", "stapler", "validate", str(target)], check=True)


def write_windows_icon(target: Path) -> Path:
    """Create the bundled multi-resolution Windows icon from simple local geometry."""
    from PIL import Image, ImageDraw

    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (8, 8, size - 8, size - 8),
        radius=48,
        fill="#174f49",
    )
    draw.line((67, 61, 67, 195), fill="#8fd3c7", width=11)
    for y, end_x in ((66, 199), (128, 181), (190, 211)):
        draw.ellipse((48, y - 19, 86, y + 19), fill="#dcebea")
        draw.rounded_rectangle(
            (102, y - 10, end_x, y + 10),
            radius=10,
            fill="#ffffff",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(
        target,
        format="ICO",
        sizes=[
            (16, 16),
            (24, 24),
            (32, 32),
            (48, 48),
            (64, 64),
            (128, 128),
            (256, 256),
        ],
    )
    return target


def windows_version_quad(version: str) -> tuple[int, int, int, int]:
    """Convert the product version into the numeric tuple required by Windows."""
    parts = [int(value) for value in re.findall(r"\d+", version)[:4]]
    values = (parts + [0] * 4)[:4]
    return values[0], values[1], values[2], values[3]


def write_windows_version_info(target: Path, version: str = __version__) -> Path:
    """Write the PyInstaller version-resource definition for the desktop executable."""
    version_quad = windows_version_quad(version)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_quad!r},
    prodvers={version_quad!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'{APP_PUBLISHER}'),
         StringStruct(u'FileDescription', u'{APP_DISPLAY_NAME} local laboratory knowledge index'),
         StringStruct(u'FileVersion', u'{version}'),
         StringStruct(u'InternalName', u'{APP_NAME}'),
         StringStruct(u'LegalCopyright', u'Copyright (c) {APP_PUBLISHER}'),
         StringStruct(u'OriginalFilename', u'{APP_NAME}.exe'),
         StringStruct(u'ProductName', u'{APP_DISPLAY_NAME}'),
         StringStruct(u'ProductVersion', u'{version}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return target


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def smoke_test(executable: Path) -> None:
    port = available_port()
    url = f"http://127.0.0.1:{port}/"
    sample = ROOT / "examples" / "smart_lab_index" / "sample_lab"
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryFile() as output:
        database = Path(temporary) / "index.db"
        environment = _smoke_environment()
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
            token = _wait_for_expected_index(process, output, url)
            _request_shutdown(url, token)
            process.wait(timeout=15)
        finally:
            if process.poll() is None:
                _terminate_process_tree(process)


def _smoke_environment() -> dict[str, str]:
    """Keep native runtime state while withholding credentials from the app."""
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _SMOKE_ENVIRONMENT
    }


def _wait_for_expected_index(
    process: subprocess.Popen[bytes],
    output: BinaryIO,
    url: str,
) -> str:
    deadline = time.monotonic() + 90
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
                with urllib.request.urlopen(url, timeout=1) as response:
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
                with urllib.request.urlopen(
                    f"{url}icons.svg", timeout=1
                ) as response:
                    icons = response.read().decode("utf-8")
                if 'id="shield-check"' not in icons:
                    raise RuntimeError("desktop app did not bundle the interface icons")
            request = urllib.request.Request(
                f"{url}api/state",
                headers={"X-Smart-Lab-Session": token},
            )
            with urllib.request.urlopen(request, timeout=1) as response:
                state = json.load(response)
            if _index_pending(state["operation"]):
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
                failures = _index_failure_detail(state)
                suffix = f"; failures: {failures}" if failures else ""
                raise RuntimeError(
                    f"desktop app returned unexpected synthetic counts: {observed}"
                    f"{suffix}"
                )
            if not state["source"]["no_egress"]:
                raise RuntimeError("desktop app did not preserve no-egress mode")
            isolation = state["source"].get("parser_isolation", {})
            required_isolation = {
                "process_boundary",
                "wall_clock_timeout",
                "serialized_output_limit",
                "network_audit_guard",
            }
            if not all(isolation.get(key) for key in required_isolation):
                raise RuntimeError(
                    "desktop app did not preserve the parser process boundary"
                )
            return token
        except OSError:
            time.sleep(0.4)
    detail = _startup_detail(output)
    message = "desktop app did not complete its smoke index within 90 seconds"
    raise RuntimeError(f"{message}:\n{detail}" if detail else message)


def _index_pending(operation: dict[str, object]) -> bool:
    state = operation.get("state")
    return state == "INDEXING" or (
        state == "IDLE" and operation.get("completed_at") is None
    )


def _request_shutdown(url: str, token: str) -> None:
    request = urllib.request.Request(
        f"{url}api/shutdown",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Origin": url.rstrip("/"),
            "X-Smart-Lab-Session": token,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.load(response)
    if result != {"ok": True}:
        raise RuntimeError("desktop app did not confirm graceful shutdown")


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _index_failure_detail(state: dict[str, object]) -> str:
    details: list[str] = []
    operation = state.get("operation")
    if isinstance(operation, dict) and operation.get("error"):
        details.append(f"operation={operation['error']}")
    issues = state.get("issues")
    if isinstance(issues, list):
        for issue in issues[:8]:
            if not isinstance(issue, dict) or issue.get("status") != "OPEN":
                continue
            evidence = issue.get("evidence")
            error = evidence.get("error") if isinstance(evidence, dict) else None
            details.append(f"{issue.get('code', 'ISSUE')}={error or 'open'}")
    return "; ".join(details)[:2_000]


def _startup_detail(output: BinaryIO) -> str:
    output.flush()
    output.seek(0)
    return output.read().decode("utf-8", errors="replace").strip()


def archive_app(signing_status: str) -> Path:
    staging = BUILD_ROOT / "archive" / APP_NAME
    shutil.rmtree(staging.parent, ignore_errors=True)
    staging.mkdir(parents=True)

    app_bundle = APP_DIST / f"{APP_NAME}.app"
    if app_bundle.exists():
        shutil.copytree(app_bundle, staging / app_bundle.name)
        launch_instruction = f"Double-click {APP_NAME}.app."
    else:
        app_directory = APP_DIST / APP_NAME
        shutil.copytree(app_directory, staging, dirs_exist_ok=True)
        executable = executable_path()
        launch_instruction = f"Double-click {executable.name}."

    trust_note = {
        "notarized": "This macOS build is signed, notarized, and has its notarization ticket stapled.",
        "signed": "This build is digitally signed by its publisher.",
        "unsigned": (
            "This build is unsigned. Your operating system may ask you to confirm that you want to "
            "open it."
        ),
    }[signing_status]
    (staging / "README.txt").write_text(
        "Smart Lab Index local operator app\n"
        "==================================\n\n"
        f"{launch_instruction}\n"
        "The first time, connect a laboratory folder in the system dialog. The local browser "
        "workspace opens and starts a read-only file sync. Smart Lab Index remembers that folder "
        "and repeats incremental syncs automatically. Use Manage source to switch folders and "
        "Close application when finished.\n\n"
        "The desktop flow starts in no-egress mode and serves only bundled assets on loopback. "
        "If a system folder dialog is unavailable, the app opens its own local folder navigator.\n\n"
        f"{trust_note}\n",
        encoding="utf-8",
    )
    shutil.copy2(
        ROOT / "requirements" / "smart-lab-production-constraints.txt",
        staging / "DEPENDENCY-CONSTRAINTS.txt",
    )
    lock_name = "smart-lab-production-linux-x86_64-py312.lock"
    shutil.copy2(
        ROOT / "requirements" / lock_name,
        staging / "DEPENDENCY-LOCK-LINUX-X64-PY312.txt",
    )
    shutil.copy2(
        ROOT / "PRODUCTION_DEPLOYMENT.md",
        staging / "PRODUCTION_DEPLOYMENT.md",
    )
    shutil.copy2(
        ROOT / "SELF_SERVICE_ARCHITECTURE.md",
        staging / "SELF_SERVICE_ARCHITECTURE.md",
    )

    FINAL_DIST.mkdir(exist_ok=True)
    archive = FINAL_DIST / f"{APP_NAME}-v{__version__}-{platform_label()}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in staging.parent.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(staging.parent))
    return archive


def write_checksum(archive: Path) -> Path:
    hasher = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    checksum = archive.with_suffix(f"{archive.suffix}.sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return checksum


def main() -> int:
    import PyInstaller.__main__

    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()

    shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    APP_DIST.mkdir(parents=True)
    pyinstaller_arguments = [
        str(ROOT / "smart_lab_index" / "web_app.py"),
        f"--name={APP_NAME}",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        f"--distpath={APP_DIST}",
        f"--workpath={BUILD_ROOT / 'work'}",
        f"--specpath={BUILD_ROOT / 'spec'}",
        "--collect-data=smart_lab_index.web_ui",
    ]
    if sys.platform == "win32":
        icon = write_windows_icon(BUILD_ROOT / f"{APP_NAME}.ico")
        version_info = write_windows_version_info(
            BUILD_ROOT / f"{APP_NAME}-version.txt"
        )
        pyinstaller_arguments.extend(
            [f"--icon={icon}", f"--version-file={version_info}"]
        )
    PyInstaller.__main__.run(pyinstaller_arguments)

    executable = executable_path()
    if not executable.exists():
        raise FileNotFoundError(f"PyInstaller did not create {executable}")
    signing_status = sign_desktop_app()
    require_signing = os.environ.get(SIGNING_REQUIRED_ENV, "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if (
        require_signing
        and sys.platform in {"win32", "darwin"}
        and signing_status == "unsigned"
    ):
        raise RuntimeError(
            "platform signing is required but no signing identity was configured"
        )
    if not args.skip_smoke:
        smoke_test(executable)

    archive = archive_app(signing_status)
    checksum = write_checksum(archive)
    print(archive)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
