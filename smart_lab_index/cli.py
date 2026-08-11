"""Local command-line interface for deterministic Smart Lab indexing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from smart_lab_index.application import build_application
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.domain import IndexRunStatus
from smart_lab_index.core.storage import KnowledgeStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-lab-index",
        description="Build a local, provenance-first index above laboratory files.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="incrementally index a local folder")
    index.add_argument("root", help="read-only folder to scan recursively")
    index.add_argument("--database", default="~/.smart-lab-index/index.db")
    index.add_argument("--source-id")
    index.add_argument("--disable", action="append", default=[], metavar="MODULE_ID")
    index.add_argument(
        "--no-egress",
        action="store_true",
        help="fail closed for modules requiring non-loopback network access",
    )

    status = commands.add_parser("status", help="show index counts and the latest run")
    status.add_argument("--database", default="~/.smart-lab-index/index.db")

    inspect = commands.add_parser("inspect", help="show indexed knowledge as JSON")
    inspect.add_argument("--database", default="~/.smart-lab-index/index.db")

    modules = commands.add_parser("modules", help="show built-in module health and security")
    modules.add_argument("root", help="folder used to validate the filesystem connector")
    modules.add_argument("--source-id")
    modules.add_argument("--disable", action="append", default=[], metavar="MODULE_ID")
    modules.add_argument("--no-egress", action="store_true")
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
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"smart-lab-index: {exc}", file=sys.stderr)
        return 2
    return 2


def _index(args: argparse.Namespace) -> int:
    with build_application(
        args.root,
        database=args.database,
        source_id=args.source_id,
        policy=_policy(args.no_egress),
        disabled_module_ids=args.disable,
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


def _policy(force_no_egress: bool) -> RuntimePolicy:
    environment_policy = RuntimePolicy.from_env()
    return RuntimePolicy(no_egress=force_no_egress or environment_policy.no_egress)


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
