"""Process-isolated execution boundary for untrusted document parsers."""

from __future__ import annotations

import hashlib
import io
import json
import multiprocessing
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import BinaryIO, Protocol

from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.domain import (
    DocumentContent,
    DocumentSource,
    OperationCancelled,
)
from smart_lab_index.core.events import EventBus
from smart_lab_index.core.modules import ModuleContext, ParserModule

MAX_PARSER_INPUT_BYTES = 100 * 1024 * 1024
_POLL_INTERVAL_SECONDS = 0.05
_TERMINATE_GRACE_SECONDS = 1.0


class ParserExecutionError(RuntimeError):
    """Raised when a parser worker violates or cannot complete its contract."""


class ParserTimeoutError(ParserExecutionError):
    pass


class ParserResourceLimitError(ParserExecutionError):
    pass


class ParserExecutor(Protocol):
    def parse(
        self,
        parser: ParserModule,
        source: DocumentSource,
        content: BinaryIO,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> DocumentContent: ...


class InProcessParserExecutor:
    """Small test/debug executor; production composition uses a child process."""

    def parse(
        self,
        parser: ParserModule,
        source: DocumentSource,
        content: BinaryIO,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> DocumentContent:
        if should_cancel is not None and should_cancel():
            raise OperationCancelled("indexing cancelled")
        document = parser.parse(source, content)
        _validate_document(document, parser, source)
        return document


@dataclass(frozen=True)
class ParserIsolationStatus:
    process_boundary: bool
    wall_clock_timeout: bool
    serialized_output_limit: bool
    network_audit_guard: bool
    cpu_limit: bool
    memory_limit: bool

    def to_dict(self) -> dict[str, bool]:
        return {
            "process_boundary": self.process_boundary,
            "wall_clock_timeout": self.wall_clock_timeout,
            "serialized_output_limit": self.serialized_output_limit,
            "network_audit_guard": self.network_audit_guard,
            "cpu_limit": self.cpu_limit,
            "memory_limit": self.memory_limit,
        }


class ProcessParserExecutor:
    """Runs one document in one disposable process with bounded IPC output."""

    def __init__(
        self,
        policy: RuntimePolicy,
        *,
        context: multiprocessing.context.BaseContext | None = None,
    ) -> None:
        self.policy = policy
        self._context = context or multiprocessing.get_context("spawn")
        self.status = ParserIsolationStatus(
            process_boundary=True,
            wall_clock_timeout=True,
            serialized_output_limit=True,
            network_audit_guard=True,
            cpu_limit=_resource_limit_available("RLIMIT_CPU"),
            memory_limit=_resource_limit_available("RLIMIT_AS"),
        )
        if policy.production_mode and not (
            self.status.cpu_limit and self.status.memory_limit
        ):
            raise ParserExecutionError(
                "production mode requires OS CPU and memory limits for parser workers"
            )

    def parse(
        self,
        parser: ParserModule,
        source: DocumentSource,
        content: BinaryIO,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> DocumentContent:
        payload = _read_input(content, source)
        receive, send = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=_parser_worker,
            name=f"smart-lab-parser-{parser.manifest.module_id}",
            args=(
                type(parser),
                dict(parser.configuration),
                self.policy,
                source,
                payload,
                send,
                self.policy.parser_cpu_seconds,
                self.policy.parser_memory_bytes,
                self.policy.parser_output_bytes,
            ),
            daemon=False,
        )
        try:
            process.start()
        except Exception:
            receive.close()
            send.close()
            raise
        send.close()
        deadline = time.monotonic() + self.policy.parser_timeout_seconds
        message: bytes | None = None
        try:
            while True:
                if should_cancel is not None and should_cancel():
                    _stop_process(process)
                    raise OperationCancelled("indexing cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _stop_process(process)
                    raise ParserTimeoutError(
                        f"parser exceeded {self.policy.parser_timeout_seconds:g} seconds"
                    )
                if receive.poll(min(_POLL_INTERVAL_SECONDS, remaining)):
                    try:
                        message = receive.recv_bytes(
                            self.policy.parser_output_bytes + 4096
                        )
                    except (EOFError, OSError) as exc:
                        process.join(_TERMINATE_GRACE_SECONDS)
                        raise _worker_exit_error(process.exitcode) from exc
                    break
                if not process.is_alive():
                    process.join(_TERMINATE_GRACE_SECONDS)
                    raise _worker_exit_error(process.exitcode)
        finally:
            receive.close()

        process.join(_TERMINATE_GRACE_SECONDS)
        if process.is_alive():
            _stop_process(process)
            raise ParserExecutionError(
                "parser worker did not exit after returning output"
            )
        if process.exitcode != 0:
            raise _worker_exit_error(process.exitcode)
        if message is None:
            raise ParserExecutionError("parser worker returned no output")
        return _decode_worker_message(message, parser, source)


def _parser_worker(
    parser_type: type[ParserModule],
    configuration: dict[str, object],
    policy: RuntimePolicy,
    source: DocumentSource,
    payload: bytes,
    connection: Connection,
    cpu_seconds: int,
    memory_bytes: int,
    output_bytes: int,
) -> None:
    try:
        os.umask(0o077)
        _apply_resource_limits(cpu_seconds, memory_bytes)
        _install_worker_audit_guard()
        parser = parser_type(configuration)
        parser.initialize(ModuleContext(policy=policy, events=EventBus()))
        parser.start()
        document = parser.parse(source, io.BytesIO(payload))
        _validate_document(document, parser, source)
        encoded = json.dumps(
            {"ok": True, "document": document.to_dict()},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > output_bytes:
            raise ParserResourceLimitError("normalized parser output exceeds its limit")
    except BaseException as exc:  # noqa: BLE001 - worker must return one bounded failure
        encoded = json.dumps(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": _bounded_error(exc),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    try:
        connection.send_bytes(encoded)
    finally:
        connection.close()


def _read_input(content: BinaryIO, source: DocumentSource) -> bytes:
    content.seek(0)
    payload = content.read(MAX_PARSER_INPUT_BYTES + 1)
    if len(payload) > MAX_PARSER_INPUT_BYTES:
        raise ParserResourceLimitError(
            "parser input exceeds the process-isolation limit"
        )
    if len(payload) != source.size_bytes:
        raise ParserExecutionError("parser input size does not match source metadata")
    if hashlib.sha256(payload).hexdigest() != source.checksum:
        raise ParserExecutionError(
            "parser input checksum does not match source metadata"
        )
    return payload


def _decode_worker_message(
    message: bytes,
    parser: ParserModule,
    source: DocumentSource,
) -> DocumentContent:
    try:
        value = json.loads(message)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParserExecutionError(
            "parser worker returned invalid serialized output"
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("ok"), bool):
        raise ParserExecutionError(
            "parser worker returned an invalid response envelope"
        )
    if not value["ok"]:
        error_type = str(value.get("error_type", "ParserExecutionError"))[:80]
        detail = str(value.get("error", "parser failed"))[:500]
        if error_type == "ParserResourceLimitError":
            raise ParserResourceLimitError(detail)
        raise ParserExecutionError(f"{error_type}: {detail}")
    document_value = value.get("document")
    if not isinstance(document_value, dict):
        raise ParserExecutionError("parser worker returned no normalized document")
    try:
        document = DocumentContent.from_dict(document_value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ParserExecutionError(
            "parser worker returned an invalid document"
        ) from exc
    _validate_document(document, parser, source)
    return document


def _validate_document(
    document: DocumentContent,
    parser: ParserModule,
    source: DocumentSource,
) -> None:
    if not isinstance(document, DocumentContent):
        raise ParserExecutionError("parser did not return DocumentContent")
    if document.source_external_id != source.external_id:
        raise ParserExecutionError("parser output belongs to a different source")
    if document.content_type != source.content_type:
        raise ParserExecutionError("parser output changed the source content type")
    if document.parser_module_id != parser.manifest.module_id:
        raise ParserExecutionError("parser output contains the wrong module ID")
    if document.parser_version != parser.manifest.version:
        raise ParserExecutionError("parser output contains the wrong module version")


def _resource_limit_available(name: str) -> bool:
    if name == "RLIMIT_AS" and sys.platform == "darwin":
        return False
    try:
        import resource
    except ImportError:
        return False
    return hasattr(resource, name)


def _apply_resource_limits(cpu_seconds: int, memory_bytes: int) -> None:
    try:
        import resource
    except ImportError:
        return
    _set_resource_limit(resource.RLIMIT_CORE, 0, 0)
    _set_resource_limit(resource.RLIMIT_FSIZE, 0, 0)
    _set_resource_limit(resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1)
    if _resource_limit_available("RLIMIT_AS"):
        _set_resource_limit(resource.RLIMIT_AS, memory_bytes, memory_bytes)


def _set_resource_limit(kind: int, soft: int, hard: int) -> None:
    import resource

    _current_soft, current_hard = resource.getrlimit(kind)
    if current_hard != resource.RLIM_INFINITY:
        hard = min(hard, current_hard)
    soft = min(soft, hard)
    resource.setrlimit(kind, (soft, hard))


def _install_worker_audit_guard() -> None:
    blocked_events = {
        "os.posix_spawn",
        "os.spawn",
        "os.system",
        "subprocess.Popen",
    }

    def guard(event: str, args: tuple[object, ...]) -> None:
        if event.startswith("socket.") and event != "socket.__new__":
            raise PermissionError("parser workers cannot access the network")
        if event in blocked_events:
            raise PermissionError("parser workers cannot start subprocesses")
        if event == "open" and _open_is_write(args):
            raise PermissionError("parser workers cannot write files")

    sys.addaudithook(guard)


def _open_is_write(args: tuple[object, ...]) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else None
    if isinstance(mode, str) and any(value in mode for value in ("w", "a", "x", "+")):
        return True
    if isinstance(flags, int):
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        return bool(flags & write_flags)
    return False


def _worker_exit_error(exitcode: int | None) -> ParserExecutionError:
    if exitcode is None:
        return ParserExecutionError("parser worker state is unavailable")
    if exitcode < 0:
        signal_number = -exitcode
        if signal_number in {
            getattr(signal, "SIGKILL", -1),
            getattr(signal, "SIGXCPU", -1),
            getattr(signal, "SIGSEGV", -1),
        }:
            return ParserResourceLimitError(
                f"parser worker was stopped by signal {signal_number}"
            )
        return ParserExecutionError(
            f"parser worker was stopped by signal {signal_number}"
        )
    return ParserExecutionError(f"parser worker exited with code {exitcode}")


def _stop_process(process: multiprocessing.Process) -> None:
    if not process.is_alive():
        process.join(_TERMINATE_GRACE_SECONDS)
        return
    process.terminate()
    process.join(_TERMINATE_GRACE_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(_TERMINATE_GRACE_SECONDS)


def _bounded_error(error: BaseException) -> str:
    detail = " ".join(str(error).split())
    if not detail:
        detail = "parser failed"
    return detail[:500]
