"""Application services that compose Smart Lab Core and enabled modules."""

from smart_lab_index.application.bootstrap import SmartLabApplication, build_application
from smart_lab_index.application.indexing import IndexingService, IndexRunResult
from smart_lab_index.application.operations import (
    backup_database,
    default_backup_path,
    restore_database,
    verify_backup,
    verify_backup_manifest,
)
from smart_lab_index.application.parsing import (
    InProcessParserExecutor,
    ParserExecutionError,
    ParserResourceLimitError,
    ParserTimeoutError,
    ProcessParserExecutor,
)
from smart_lab_index.application.query import KnowledgeQueryService
from smart_lab_index.application.review import IssueReviewService

__all__ = [
    "InProcessParserExecutor",
    "IndexRunResult",
    "IndexingService",
    "IssueReviewService",
    "KnowledgeQueryService",
    "ParserExecutionError",
    "ParserResourceLimitError",
    "ParserTimeoutError",
    "ProcessParserExecutor",
    "SmartLabApplication",
    "backup_database",
    "build_application",
    "default_backup_path",
    "restore_database",
    "verify_backup",
    "verify_backup_manifest",
]
