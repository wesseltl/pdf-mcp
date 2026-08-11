"""Explicit opt-in client for the authenticated pdf-mcp hosted beta."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from pdf_mcp import __version__, extractor
from smart_lab_index.core.config import no_egress_enabled

try:
    import httpx
except ImportError as exc:  # pragma: no cover - exercised when the optional command starts
    raise SystemExit(
        'The cloud bridge needs httpx. Install it with: pip install "pdf-agent-mcp[cloud]"'
    ) from exc


class CloudConfigurationError(RuntimeError):
    pass


class CloudServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudConfig:
    base_url: str
    api_key: str
    max_upload_bytes: int = 10_000_000
    timeout_seconds: float = 40.0

    @classmethod
    def from_env(cls) -> CloudConfig:
        if no_egress_enabled():
            raise CloudConfigurationError(
                "hosted extraction is disabled by SMART_LAB_INDEX_NO_EGRESS"
            )
        base_url = os.environ.get("PDF_MCP_CLOUD_URL", "").strip().rstrip("/")
        api_key = os.environ.get("PDF_MCP_CLOUD_API_KEY", "").strip()
        if not base_url:
            raise CloudConfigurationError("PDF_MCP_CLOUD_URL is required for the cloud bridge.")
        if not api_key:
            raise CloudConfigurationError("PDF_MCP_CLOUD_API_KEY is required for the cloud bridge.")
        parsed = urlparse(base_url)
        local_host = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local_host):
            raise CloudConfigurationError(
                "PDF_MCP_CLOUD_URL must use HTTPS; HTTP is allowed only for localhost."
            )
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CloudConfigurationError("PDF_MCP_CLOUD_URL is not a valid service base URL.")
        try:
            max_bytes = int(os.environ.get("PDF_MCP_CLOUD_MAX_UPLOAD_BYTES", "10000000"))
        except ValueError as exc:
            raise CloudConfigurationError(
                "PDF_MCP_CLOUD_MAX_UPLOAD_BYTES must be an integer."
            ) from exc
        if max_bytes <= 0:
            raise CloudConfigurationError("PDF_MCP_CLOUD_MAX_UPLOAD_BYTES must be positive.")
        return cls(base_url=base_url, api_key=api_key, max_upload_bytes=max_bytes)


def _document(path: str, config: CloudConfig) -> tuple[str, str, str]:
    resolved = extractor._check_path(path)
    extension = Path(resolved).suffix.lower()
    content_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    if extension not in content_types:
        raise ValueError("hosted extraction supports only .pdf and .docx files")
    size = os.path.getsize(resolved)
    if size == 0:
        raise ValueError("document is empty")
    if size > config.max_upload_bytes:
        raise ValueError(f"document exceeds the {config.max_upload_bytes} byte cloud upload limit")
    return resolved, f"document{extension}", content_types[extension]


def _detail(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "service returned a non-JSON error"
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, str) else "service rejected the request"


def _request(tool: str, path: str, fields: dict | None = None) -> dict:
    config = CloudConfig.from_env()
    resolved, upload_name, content_type = _document(path, config)
    timeout = httpx.Timeout(config.timeout_seconds, connect=10.0)
    try:
        with open(resolved, "rb") as document, httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "User-Agent": f"pdf-agent-cloud-mcp/{__version__}",
            },
        ) as client:
            response = client.post(
                f"{config.base_url}/v1/extract/{tool}",
                files={"file": (upload_name, document, content_type)},
                data=fields or {},
            )
    except httpx.TimeoutException as exc:
        raise CloudServiceError("hosted extraction timed out") from exc
    except httpx.RequestError as exc:
        raise CloudServiceError("hosted extraction service could not be reached") from exc

    if response.status_code == 401:
        raise CloudServiceError("hosted beta API key was rejected")
    if response.status_code == 429:
        raise CloudServiceError("hosted beta monthly operation limit reached")
    if response.status_code >= 400:
        raise CloudServiceError(
            f"hosted extraction failed with HTTP {response.status_code}: {_detail(response)}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise CloudServiceError("hosted extraction returned invalid JSON") from exc
    if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        raise CloudServiceError("hosted extraction returned an invalid response shape")
    return {**body["result"], "cloud_usage": body.get("usage", {})}


def extract_text(path: str, page: int | None = None) -> dict:
    fields = {} if page is None else {"page": str(page)}
    return _request("text", path, fields)


def extract_tables(path: str, page: int | None = None, merge_multipage: bool = False) -> dict:
    fields = {"merge_multipage": str(merge_multipage).lower()}
    if page is not None:
        fields["page"] = str(page)
    return _request("tables", path, fields)


def table_to_csv(path: str, page: int | None = None, index: int = 0) -> dict:
    fields = {"index": str(index)}
    if page is not None:
        fields["page"] = str(page)
    return _request("csv", path, fields)


def usage() -> dict:
    config = CloudConfig.from_env()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "User-Agent": f"pdf-agent-cloud-mcp/{__version__}",
            },
        ) as client:
            response = client.get(f"{config.base_url}/v1/usage")
    except httpx.RequestError as exc:
        raise CloudServiceError("hosted extraction service could not be reached") from exc
    if response.status_code != 200:
        raise CloudServiceError(f"hosted usage request failed with HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise CloudServiceError("hosted usage request returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise CloudServiceError("hosted usage request returned an invalid response shape")
    return body
