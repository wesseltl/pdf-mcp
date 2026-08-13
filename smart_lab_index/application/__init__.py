"""Application services that compose LabOverlay Core and enabled modules."""

from smart_lab_index.application.bootstrap import SmartLabApplication, build_application
from smart_lab_index.application.desktop_settings import (
    DEFAULT_DESKTOP_INDEX_INTERVAL_MINUTES,
    DesktopSettings,
    DesktopSettingsError,
    default_desktop_settings_path,
    forget_desktop_settings,
    load_desktop_settings,
    save_desktop_settings,
)
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
    "DEFAULT_DESKTOP_INDEX_INTERVAL_MINUTES",
    "DesktopSettings",
    "DesktopSettingsError",
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
    "default_desktop_settings_path",
    "forget_desktop_settings",
    "load_desktop_settings",
    "restore_database",
    "save_desktop_settings",
    "verify_backup",
    "verify_backup_manifest",
]
