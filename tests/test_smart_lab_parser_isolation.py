"""Adversarial tests for the disposable parser process boundary."""

from __future__ import annotations

import hashlib
import io
import os
import socket
import time
import unittest
from typing import BinaryIO

from smart_lab_index.application.parsing import (
    ParserExecutionError,
    ParserResourceLimitError,
    ParserTimeoutError,
    ProcessParserExecutor,
)
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.domain import (
    DocumentContent,
    DocumentSource,
    OperationCancelled,
)
from smart_lab_index.core.modules import (
    FileAccess,
    ModuleCapability,
    ModuleManifest,
    ModuleType,
    NetworkAccess,
    ParserModule,
)


class IsolationProbeParser(ParserModule):
    manifest = ModuleManifest(
        module_id="parser.test_isolation",
        name="Isolation probe parser",
        version="1.0.0",
        module_type=ModuleType.PARSER,
        description="Test-only parser process probe.",
        capabilities=(ModuleCapability("parser.document", "1.0.0"),),
        configuration_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"mode": {"type": "string"}},
        },
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def supports(self, _source: DocumentSource) -> bool:
        return True

    def parse(self, source: DocumentSource, content: BinaryIO) -> DocumentContent:
        content.read()
        mode = self.configuration.get("mode", "ok")
        if mode == "sleep":
            time.sleep(5)
        elif mode == "network":
            with socket.socket() as client:
                client.connect(("127.0.0.1", 9))
        elif mode == "crash":
            os._exit(7)
        metadata = {"probe": "x" * 20_000} if mode == "large" else {"probe": "ok"}
        return DocumentContent(
            source_external_id=source.external_id,
            content_type=source.content_type,
            parser_module_id=self.manifest.module_id,
            parser_version=self.manifest.version,
            metadata=metadata,
        )


class ParserIsolationTests(unittest.TestCase):
    payload = b"synthetic parser input"

    def source(self) -> DocumentSource:
        return DocumentSource(
            external_id="probe.txt",
            source_id="test-source",
            name="probe.txt",
            path="probe.txt",
            content_type="text/plain",
            modified_at="2026-08-11T00:00:00+00:00",
            size_bytes=len(self.payload),
            checksum=hashlib.sha256(self.payload).hexdigest(),
        )

    def policy(self, **overrides: object) -> RuntimePolicy:
        values = {
            "no_egress": True,
            "parser_timeout_seconds": 3.0,
            "parser_cpu_seconds": 2,
            "parser_memory_bytes": 512 * 1024 * 1024,
            "parser_output_bytes": 1024 * 1024,
        }
        values.update(overrides)
        return RuntimePolicy(**values)

    def execute(
        self,
        mode: str,
        *,
        policy: RuntimePolicy | None = None,
        should_cancel=None,
    ) -> DocumentContent:
        parser = IsolationProbeParser({"mode": mode})
        return ProcessParserExecutor(policy or self.policy()).parse(
            parser,
            self.source(),
            io.BytesIO(self.payload),
            should_cancel=should_cancel,
        )

    def test_valid_parser_returns_only_normalized_serialized_content(self) -> None:
        document = self.execute("ok")
        self.assertEqual(document.metadata, {"probe": "ok"})
        self.assertEqual(document.source_external_id, "probe.txt")

    def test_wall_clock_timeout_terminates_worker(self) -> None:
        with self.assertRaises(ParserTimeoutError):
            self.execute(
                "sleep",
                policy=self.policy(parser_timeout_seconds=0.2),
            )

    def test_operator_cancellation_terminates_active_worker(self) -> None:
        started = time.monotonic()
        with self.assertRaises(OperationCancelled):
            self.execute(
                "sleep",
                should_cancel=lambda: time.monotonic() - started > 0.2,
            )

    def test_network_access_is_denied_inside_worker(self) -> None:
        with self.assertRaisesRegex(ParserExecutionError, "cannot access the network"):
            self.execute("network")

    def test_normalized_output_and_abrupt_exit_are_bounded(self) -> None:
        with self.assertRaises(ParserResourceLimitError):
            self.execute(
                "large",
                policy=self.policy(parser_output_bytes=1024),
            )
        with self.assertRaisesRegex(ParserExecutionError, "exited with code 7"):
            self.execute("crash")


if __name__ == "__main__":
    unittest.main()
