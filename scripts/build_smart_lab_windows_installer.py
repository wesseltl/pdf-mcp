"""Build, sign, and smoke-test the Smart Lab Index Windows installer."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from scripts import build_smart_lab_desktop_app as desktop_build
from smart_lab_index import __version__

ROOT = Path(__file__).resolve().parents[1]
INNO_SCRIPT = ROOT / "installer" / "windows" / "smart-lab-index.iss"
INSTALLER_ARCHITECTURE = "windows-x64"
INSTALLER_BASE_NAME = (
    f"{desktop_build.APP_NAME}-setup-v{__version__}-{INSTALLER_ARCHITECTURE}"
)


def find_inno_compiler() -> Path:
    """Locate the Inno Setup command-line compiler on a Windows build host."""
    configured = os.environ.get("SMART_LAB_INNO_SETUP_COMPILER")
    if configured:
        return Path(configured).expanduser().resolve(strict=True)

    discovered = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if discovered:
        return Path(discovered).resolve()

    candidates: list[Path] = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        program_files = os.environ.get(variable)
        if program_files:
            candidates.extend(Path(program_files).glob("Inno Setup */ISCC.exe"))
    if candidates:
        return max(candidates)
    raise FileNotFoundError(
        "ISCC.exe was not found; install Inno Setup 6 or set "
        "SMART_LAB_INNO_SETUP_COMPILER"
    )


def installer_path() -> Path:
    return desktop_build.FINAL_DIST / f"{INSTALLER_BASE_NAME}.exe"


def build_installer(compiler: Path) -> Path:
    source = desktop_build.APP_DIST / desktop_build.APP_NAME
    executable = source / f"{desktop_build.APP_NAME}.exe"
    if not executable.is_file():
        raise FileNotFoundError(
            f"Windows desktop app was not built before the installer: {executable}"
        )

    icon = desktop_build.BUILD_ROOT / f"{desktop_build.APP_NAME}.ico"
    if not icon.is_file():
        desktop_build.write_windows_icon(icon)

    output = installer_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    subprocess.run(
        [
            str(compiler),
            "/Qp",
            f"/DAppVersion={__version__}",
            f"/DSourceDir={source.resolve()}",
            f"/DOutputDir={output.parent.resolve()}",
            f"/DOutputBaseFilename={output.stem}",
            f"/DIconFile={icon.resolve()}",
            str(INNO_SCRIPT),
        ],
        check=True,
    )
    if not output.is_file():
        raise FileNotFoundError(f"Inno Setup did not create {output}")
    return output


def smoke_test_installer(installer: Path) -> None:
    """Install silently, exercise the installed app, and uninstall it again."""
    if sys.platform != "win32":
        raise RuntimeError("the installer smoke test must run on Windows")

    with tempfile.TemporaryDirectory(prefix="smart-lab-installer-") as temporary:
        test_root = Path(temporary)
        install_directory = test_root / "installed"
        install_log = test_root / "install.log"
        subprocess.run(
            [
                str(installer),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/SP-",
                "/MERGETASKS=!desktopicon",
                f"/DIR={install_directory}",
                f"/LOG={install_log}",
            ],
            check=True,
            timeout=240,
        )

        executable = install_directory / f"{desktop_build.APP_NAME}.exe"
        uninstaller = install_directory / "unins000.exe"
        if not executable.is_file() or not uninstaller.is_file():
            raise RuntimeError("silent installation did not create the expected files")

        try:
            desktop_build.smoke_test(executable)
        finally:
            if uninstaller.is_file():
                subprocess.run(
                    [
                        str(uninstaller),
                        "/VERYSILENT",
                        "/SUPPRESSMSGBOXES",
                        "/NORESTART",
                    ],
                    check=True,
                    timeout=240,
                )

        deadline = time.monotonic() + 30
        while executable.exists() and time.monotonic() < deadline:
            time.sleep(0.25)
        if executable.exists():
            raise RuntimeError("silent uninstall left the application executable behind")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()

    if sys.platform != "win32":
        raise RuntimeError("the Smart Lab Index installer can only be built on Windows")

    installer = build_installer(find_inno_compiler())
    signing_status = desktop_build.sign_windows_file(installer)
    require_signing = os.environ.get(
        desktop_build.SIGNING_REQUIRED_ENV, ""
    ).lower() in {"1", "true", "yes", "on"}
    if require_signing and signing_status == "unsigned":
        raise RuntimeError(
            "Windows signing is required but no signing certificate was configured"
        )
    if not args.skip_smoke:
        smoke_test_installer(installer)

    checksum = desktop_build.write_checksum(installer)
    print(installer)
    print(checksum)
    print(f"signing: {signing_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
