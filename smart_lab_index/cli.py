"""Local command-line interface for deterministic LabOverlay indexing."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from smart_lab_index.application import (
    backup_database,
    build_application,
    default_backup_path,
    restore_database,
    verify_backup,
    verify_backup_manifest,
)
from smart_lab_index.branding import CLI_NAME
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.domain import IndexRunStatus
from smart_lab_index.core.paths import (
    default_database_path,
    default_operator_token_path,
)
from smart_lab_index.core.security import OPERATOR_USERNAME, create_operator_token
from smart_lab_index.core.storage import KnowledgeStore
from smart_lab_index.modules.connectors.filesystem import (
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_TOTAL_BYTES,
)


def _parser() -> argparse.ArgumentParser:
    default_database = str(default_database_path())
    parser = argparse.ArgumentParser(
        prog=CLI_NAME,
        description="Build a local, provenance-first index above laboratory files.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="incrementally index a local folder")
    index.add_argument("root", help="read-only folder to scan recursively")
    index.add_argument("--database", default=default_database)
    index.add_argument("--source-id")
    index.add_argument("--disable", action="append", default=[], metavar="MODULE_ID")
    index.add_argument("--enable", action="append", default=[], metavar="MODULE_ID")
    index.add_argument(
        "--max-files",
        type=int,
        default=DEFAULT_MAX_FILES,
        help=f"stop before indexing more than this many files (default: {DEFAULT_MAX_FILES})",
    )
    index.add_argument(
        "--max-total-gb",
        type=float,
        default=DEFAULT_MAX_TOTAL_BYTES / (1024**3),
        help=(
            "stop before indexing a larger source scope "
            f"(default: {DEFAULT_MAX_TOTAL_BYTES // 1024**3} GiB)"
        ),
    )
    index.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="exclude a relative path or filename glob; may be repeated",
    )
    index.add_argument(
        "--verify-all-content",
        action="store_true",
        help="re-hash unchanged files instead of trusting filesystem change metadata",
    )
    index.add_argument(
        "--no-egress",
        action="store_true",
        help="fail closed for modules requiring non-loopback network access",
    )
    index.add_argument(
        "--production",
        action="store_true",
        help="enforce no-egress and hard parser isolation requirements",
    )

    status = commands.add_parser("status", help="show index counts and the latest run")
    status.add_argument("--database", default=default_database)

    health = commands.add_parser("health", help="verify database integrity and schema")
    health.add_argument("--database", default=default_database)

    inspect = commands.add_parser("inspect", help="show indexed knowledge as JSON")
    inspect.add_argument("--database", default=default_database)

    modules = commands.add_parser("modules", help="show built-in module health and security")
    modules.add_argument("root", help="folder used to validate the filesystem connector")
    modules.add_argument("--source-id")
    modules.add_argument("--disable", action="append", default=[], metavar="MODULE_ID")
    modules.add_argument("--enable", action="append", default=[], metavar="MODULE_ID")
    modules.add_argument("--no-egress", action="store_true")

    operator = commands.add_parser(
        "init-operator",
        help="create an owner-only operator access key",
    )
    operator.add_argument(
        "--output",
        default=str(default_operator_token_path()),
    )
    operator.add_argument("--force", action="store_true")

    backup = commands.add_parser("backup", help="create and verify a consistent backup")
    backup.add_argument("--database", default=default_database)
    backup.add_argument("--output")

    verify = commands.add_parser("verify-backup", help="verify a backup and its checksum")
    verify.add_argument("backup")
    verify.add_argument("--sha256")
    verify.add_argument(
        "--without-manifest",
        action="store_true",
        help="verify only SQLite and an optional --sha256",
    )

    restore = commands.add_parser("restore", help="restore a verified backup while offline")
    restore.add_argument("backup")
    restore.add_argument("--database", default=default_database)
    restore.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "index":
            return _index(args)
        if args.command == "status":
            with _existing_store(args.database) as store:
                _print_json(store.summary())
            return 0
        if args.command == "health":
            with _existing_store(args.database) as store:
                report = store.integrity_report()
            _print_json(report)
            return 0 if report["healthy"] else 1
        if args.command == "inspect":
            with _existing_store(args.database) as store:
                _print_json(_knowledge(store))
            return 0
        if args.command == "modules":
            with build_application(
                args.root,
                database=":memory:",
                source_id=args.source_id,
                policy=_policy(args.no_egress),
                disabled_module_ids=args.disable,
                enabled_module_ids=args.enable,
            ) as application:
                _print_json({
                    "startup_errors": application.startup_errors,
                    "source": {
                        "source_id": application.source.source_id,
                        "connector_module_id": application.source.connector_module_id,
                        "configuration": dict(application.source.configuration),
                    },
                    "modules": application.registry.snapshot(),
                })
            return 0
        if args.command == "init-operator":
            token = create_operator_token(args.output, force=args.force)
            _print_json({
                "path": str(Path(args.output).expanduser().absolute()),
                "username": OPERATOR_USERNAME,
                "token": token,
            })
            return 0
        if args.command == "backup":
            output = args.output or default_backup_path(args.database)
            _print_json(backup_database(args.database, output))
            return 0
        if args.command == "verify-backup":
            if args.without_manifest:
                result = verify_backup(args.backup, expected_sha256=args.sha256)
            else:
                if args.sha256 is not None:
                    raise ValueError("use --without-manifest with an explicit --sha256")
                result = verify_backup_manifest(args.backup)
            _print_json(result)
            return 0
        if args.command == "restore":
            _print_json(restore_database(
                args.backup,
                args.database,
                replace=args.replace,
            ))
            return 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"{CLI_NAME}: {exc}", file=sys.stderr)
        return 2
    return 2


def _index(args: argparse.Namespace) -> int:
    with build_application(
        args.root,
        database=args.database,
        source_id=args.source_id,
        policy=_policy(args.no_egress, production_mode=args.production),
        disabled_module_ids=args.disable,
        enabled_module_ids=args.enable,
        max_files=args.max_files,
        max_total_bytes=_gib_to_bytes(args.max_total_gb),
        exclude_patterns=args.exclude,
        verify_unchanged_content=args.verify_all_content,
    ) as application:
        connector_error = application.startup_errors.get(application.connector_module_id)
        if connector_error:
            raise RuntimeError(connector_error)
        result = application.indexing.run(application.source)
        value = result.to_dict()
        if application.startup_errors:
            value["startup_errors"] = application.startup_errors
        _print_json(value)
        return 1 if result.status == IndexRunStatus.COMPLETED_WITH_ERRORS else 0


def _policy(force_no_egress: bool, *, production_mode: bool = False) -> RuntimePolicy:
    environment_policy = RuntimePolicy.from_env()
    effective_production = production_mode or environment_policy.production_mode
    return replace(
        environment_policy,
        no_egress=(
            force_no_egress or effective_production or environment_policy.no_egress
        ),
        production_mode=effective_production,
    )


def _gib_to_bytes(value: float) -> int:
    if value <= 0:
        raise ValueError("--max-total-gb must be positive")
    return int(value * 1024**3)


def _existing_store(database: str) -> KnowledgeStore:
    if database != ":memory:" and not Path(database).expanduser().is_file():
        raise ValueError(f"index database does not exist: {database}")
    return KnowledgeStore(database)


def _knowledge(store: KnowledgeStore) -> dict[str, Any]:
    return {
        "summary": store.summary(),
        "sources": store.list_sources(),
        "documents": store.list_documents(),
        "entities": [
            {
                "entity_id": entity.entity_id,
                "entity_type": entity.entity_type.value,
                "canonical_name": entity.canonical_name,
                "subtype": entity.subtype,
                "identifier": entity.identifier,
                "metadata": dict(entity.metadata),
            }
            for entity in store.list_entities()
        ],
        "assertions": [
            {
                "assertion_id": assertion.assertion_id,
                "subject_entity_id": assertion.subject_entity_id,
                "predicate": assertion.predicate,
                "object_entity_id": assertion.object_entity_id,
                "literal": assertion.literal,
                "source_record_id": assertion.source_record_id,
                "document_id": assertion.document_id,
                "source_generation": assertion.source_generation,
                "source_checksum": assertion.source_checksum,
                "provenance": dict(assertion.provenance),
                "confidence": assertion.confidence,
                "status": assertion.status.value,
                "module_id": assertion.module_id,
                "module_version": assertion.module_version,
            }
            for assertion in store.list_assertions()
        ],
        "issues": store.list_issues(),
    }


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
