"""Read-only, incremental local filesystem connector."""

from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import stat as stat_module
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, ClassVar

from smart_lab_index.core.domain import (
    DiscoveredSource,
    DiscoveryBatch,
    DiscoveryChange,
    DiscoveryFailure,
    SourceDefinition,
    SourceRecord,
)
from smart_lab_index.core.modules import (
    ConnectorModule,
    FileAccess,
    ModuleCapability,
    ModuleConfigurationError,
    ModuleHealth,
    ModuleHealthState,
    ModuleManifest,
    ModuleType,
    NetworkAccess,
)

DEFAULT_EXTENSIONS = (".csv", ".docx", ".pdf", ".txt", ".xlsx")
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024
_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class FilesystemConnector(ConnectorModule):
    manifest = ModuleManifest(
        module_id="connector.filesystem",
        name="Filesystem Connector",
        version="0.1.0",
        module_type=ModuleType.CONNECTOR,
        description="Recursively discovers local files without modifying source content.",
        capabilities=(ModuleCapability("connector.source_records", "1.0.0"),),
        configuration_schema={"type": "object", "additionalProperties": False},
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.READ,
    )
    source_configuration_schema: ClassVar[Mapping[str, object]] = {
        "type": "object",
        "required": ["root"],
        "additionalProperties": False,
        "properties": {
            "root": {"type": "string"},
            "include_extensions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "include_hidden": {"type": "boolean"},
            "max_file_bytes": {"type": "integer"},
        },
    }

    def __init__(
        self,
        *,
        open_file: Callable[..., BinaryIO] | None = None,
        stat_file: Callable[[Path], os.stat_result] | None = None,
    ) -> None:
        super().__init__()
        self._open_file = open_file or _open_readonly
        self._stat_file = stat_file or (lambda path: path.stat())

    def source(
        self,
        root: str | Path,
        *,
        source_id: str | None = None,
        include_extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
        include_hidden: bool = False,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> SourceDefinition:
        resolved_root = Path(root).expanduser().resolve()
        identifier = source_id or (
            "filesystem-"
            + hashlib.sha256(str(resolved_root).encode("utf-8")).hexdigest()[:12]
        )
        definition = SourceDefinition(
            source_id=identifier,
            connector_module_id=self.manifest.module_id,
            configuration={
                "root": str(resolved_root),
                "include_extensions": tuple(sorted({
                    extension.lower() for extension in include_extensions
                })),
                "include_hidden": include_hidden,
                "max_file_bytes": max_file_bytes,
            },
        )
        self.validate_source(definition)
        return definition

    def validate_source(self, source: SourceDefinition) -> None:
        _settings(source, self.manifest.module_id)

    def source_identity(self, source: SourceDefinition) -> Mapping[str, object]:
        settings = _settings(source, self.manifest.module_id)
        return {"root": str(settings.root)}

    def health_check(self) -> ModuleHealth:
        if not self._started:
            return ModuleHealth(ModuleHealthState.DEGRADED, "module has not started")
        return ModuleHealth(ModuleHealthState.HEALTHY)

    def discover(
        self,
        definition: SourceDefinition,
        previous: Mapping[str, SourceRecord],
    ) -> DiscoveryBatch:
        settings = _settings(definition, self.manifest.module_id)
        sources: list[DiscoveredSource] = []
        failures: list[DiscoveryFailure] = []
        complete = True
        try:
            self._stat_file(settings.root)
        except OSError as exc:
            return DiscoveryBatch(
                failures=(
                    DiscoveryFailure(".", str(settings.root), _bounded_error(exc)),
                ),
                complete=False,
            )

        def walk_error(error: OSError) -> None:
            nonlocal complete
            complete = False
            path = Path(error.filename or settings.root)
            failures.append(DiscoveryFailure(
                _relative_or_dot(path, settings.root),
                str(path),
                _bounded_error(error),
            ))

        for directory, directory_names, filenames in os.walk(
            settings.root, topdown=True, onerror=walk_error, followlinks=False
        ):
            directory_path = Path(directory)
            retained_directories = []
            for name in sorted(directory_names):
                if not _include_name(name, settings):
                    continue
                candidate = directory_path / name
                if candidate.is_symlink():
                    complete = False
                    failures.append(DiscoveryFailure(
                        _relative_or_dot(candidate, settings.root),
                        str(candidate),
                        "PermissionError: symbolic-link directories are not indexed",
                    ))
                    continue
                retained_directories.append(name)
            directory_names[:] = retained_directories
            for filename in sorted(filenames):
                if not _include_name(filename, settings):
                    continue
                path = directory_path / filename
                if path.suffix.lower() not in settings.include_extensions:
                    continue
                external_id = _relative_or_dot(path, settings.root)
                try:
                    if path.is_symlink():
                        raise PermissionError("symbolic-link files are not indexed")
                    resolved = path.resolve(strict=True)
                    _require_inside(resolved, settings.root)
                    checksum, stat = self._checksum(resolved, settings)
                    record = SourceRecord(
                        external_id=external_id,
                        source_id=definition.source_id,
                        name=path.name,
                        path=external_id,
                        content_type=_content_type(path),
                        modified_at=datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat(),
                        size_bytes=stat.st_size,
                        checksum=checksum,
                        change_token=f"{stat.st_mtime_ns}:{stat.st_size}:{checksum}",
                        content_ref=str(resolved),
                        metadata={
                            "extension": path.suffix.lower(),
                            "device": stat.st_dev,
                            "inode": stat.st_ino,
                            "created_at": datetime.fromtimestamp(
                                stat.st_ctime, timezone.utc
                            ).isoformat(),
                        },
                        permission_metadata={
                            "mode": oct(stat.st_mode & 0o777),
                            "uid": getattr(stat, "st_uid", None),
                            "gid": getattr(stat, "st_gid", None),
                        },
                    )
                    prior = previous.get(external_id)
                    if prior is None:
                        change = DiscoveryChange.NEW
                    elif prior.checksum == checksum:
                        change = DiscoveryChange.UNCHANGED
                    else:
                        change = DiscoveryChange.CHANGED
                    sources.append(DiscoveredSource(change=change, record=record))
                except (OSError, ValueError) as exc:
                    failures.append(DiscoveryFailure(
                        external_id=external_id,
                        path=str(path),
                        error=_bounded_error(exc),
                    ))
        return DiscoveryBatch(
            sources=tuple(sources),
            failures=tuple(failures),
            complete=complete,
        )

    @contextmanager
    def open_content(
        self,
        definition: SourceDefinition,
        source: SourceRecord,
    ) -> Iterator[BinaryIO]:
        settings = _settings(definition, self.manifest.module_id)
        if source.source_id != definition.source_id:
            raise PermissionError("source record belongs to a different connector configuration")
        path = Path(source.content_ref)
        if path.is_symlink():
            raise PermissionError("symbolic-link files are not opened")
        resolved = path.resolve(strict=True)
        _require_inside(resolved, settings.root)
        stream = self._open_file(resolved, "rb")
        try:
            opened_stat = _stream_stat(stream, resolved, self._stat_file)
            _require_regular(opened_stat)
            _require_opened_inside(stream, settings.root)
            expected_device = source.metadata.get("device")
            expected_inode = source.metadata.get("inode")
            if expected_device is not None and opened_stat.st_dev != expected_device:
                raise OSError("source identity changed after discovery; retry the index run")
            if expected_inode is not None and opened_stat.st_ino != expected_inode:
                raise OSError("source identity changed after discovery; retry the index run")
            content = _read_bounded(stream, settings.max_file_bytes)
        finally:
            stream.close()
        if hashlib.sha256(content).hexdigest() != source.checksum:
            raise OSError("source changed after discovery; retry the index run")
        snapshot = io.BytesIO(content)
        try:
            yield snapshot
        finally:
            snapshot.close()

    def _checksum(
        self,
        path: Path,
        settings: _FilesystemSettings,
    ) -> tuple[str, os.stat_result]:
        digest = hashlib.sha256()
        stream = self._open_file(path, "rb")
        try:
            opened_stat = _stream_stat(stream, path, self._stat_file)
            _require_regular(opened_stat)
            _require_opened_inside(stream, settings.root)
            total = 0
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_file_bytes:
                    raise OSError(
                        f"file exceeds connector limit of {settings.max_file_bytes} bytes"
                    )
                digest.update(chunk)
        finally:
            stream.close()
        return digest.hexdigest(), opened_stat



@dataclass(frozen=True)
class _FilesystemSettings:
    root: Path
    include_extensions: tuple[str, ...]
    include_hidden: bool
    max_file_bytes: int


def _settings(
    source: SourceDefinition,
    expected_module_id: str,
) -> _FilesystemSettings:
    if source.connector_module_id != expected_module_id:
        raise ModuleConfigurationError("source uses a different connector module")
    allowed = {"root", "include_extensions", "include_hidden", "max_file_bytes"}
    unknown = set(source.configuration) - allowed
    if unknown:
        raise ModuleConfigurationError(
            f"source configuration has unknown fields: {', '.join(sorted(unknown))}"
        )
    root_value = source.configuration.get("root")
    if not isinstance(root_value, str) or not root_value.strip():
        raise ModuleConfigurationError("source configuration.root must be a string")
    root = Path(root_value).expanduser().resolve()
    extension_values = source.configuration.get("include_extensions", DEFAULT_EXTENSIONS)
    if not isinstance(extension_values, (list, tuple)) or not all(
        isinstance(value, str) for value in extension_values
    ):
        raise ModuleConfigurationError(
            "source configuration.include_extensions must be an array of strings"
        )
    extensions = tuple(sorted({value.lower() for value in extension_values}))
    if any(not value.startswith(".") or value != value.lower() for value in extensions):
        raise ModuleConfigurationError(
            "include_extensions must contain lowercase extensions beginning with a dot"
        )
    include_hidden = source.configuration.get("include_hidden", False)
    if not isinstance(include_hidden, bool):
        raise ModuleConfigurationError("source configuration.include_hidden must be boolean")
    maximum = source.configuration.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        raise ModuleConfigurationError("source configuration.max_file_bytes must be positive")
    if not root.is_dir():
        raise ModuleConfigurationError(f"filesystem root is not a directory: {root}")
    return _FilesystemSettings(root, extensions, include_hidden, maximum)


def _include_name(name: str, settings: _FilesystemSettings) -> bool:
    return settings.include_hidden or not name.startswith(".")


def _require_inside(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"path escapes configured root: {path}") from exc


def _relative_or_dot(path: Path, root: Path) -> str:
    try:
        value = path.absolute().relative_to(root).as_posix()
        return value or "."
    except ValueError:
        return "."


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(
        path.suffix.lower(),
        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )


def _bounded_error(error: BaseException) -> str:
    value = f"{type(error).__name__}: {error}"
    return value if len(value) <= 300 else f"{value[:297]}..."


def _open_readonly(path: Path, mode: str = "rb") -> BinaryIO:
    if mode != "rb":
        raise ValueError("filesystem sources can only be opened in binary read-only mode")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    return os.fdopen(descriptor, "rb")


def _stream_stat(
    stream: BinaryIO,
    path: Path,
    fallback: Callable[[Path], os.stat_result],
) -> os.stat_result:
    try:
        return os.fstat(stream.fileno())
    except (AttributeError, OSError):
        return fallback(path)


def _require_regular(value: os.stat_result) -> None:
    if not stat_module.S_ISREG(value.st_mode):
        raise OSError("source is not a regular file")


def _require_opened_inside(stream: BinaryIO, root: Path) -> None:
    try:
        descriptor = stream.fileno()
    except (AttributeError, OSError):
        return
    descriptor_path = Path(f"/proc/self/fd/{descriptor}")
    if descriptor_path.exists():
        _require_inside(descriptor_path.resolve(strict=True), root)


def _read_bounded(stream: BinaryIO, maximum: int) -> bytes:
    content = bytearray()
    while chunk := stream.read(min(1024 * 1024, maximum + 1 - len(content))):
        content.extend(chunk)
        if len(content) > maximum:
            raise OSError(f"file exceeds connector limit of {maximum} bytes")
    return bytes(content)
