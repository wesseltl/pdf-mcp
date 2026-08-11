"""Tests for the explicit opt-in hosted bridge without network calls."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from pdf_mcp import cloud_client


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {
            "result": {"tables": [], "n_tables": 0, "warnings": ["no tables"]},
            "usage": {"remaining_operations": 24, "page_count": 1},
        }

    def json(self):
        return self._body


class FakeClient:
    response = FakeResponse()
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, **kwargs):
        upload_name, document, content_type = kwargs["files"]["file"]
        self.__class__.calls.append({
            "method": "POST",
            "url": url,
            "upload_name": upload_name,
            "content_type": content_type,
            "bytes": document.read(),
            "data": kwargs["data"],
            "headers": self.kwargs["headers"],
        })
        return self.__class__.response

    def get(self, url):
        self.__class__.calls.append({"method": "GET", "url": url})
        return self.__class__.response


class CloudClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "customer-secret-name.pdf")
        with open(self.path, "wb") as document:
            document.write(b"%PDF-1.4\nredacted test")
        self.environment = {
            "PDF_MCP_CLOUD_URL": "https://cloud.example.test",
            "PDF_MCP_CLOUD_API_KEY": "pdfc_secret_test_key",
        }
        FakeClient.calls = []
        FakeClient.response = FakeResponse()

    def tearDown(self):
        self.temp.cleanup()

    def test_cloud_configuration_is_explicit_and_https_only(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(cloud_client.CloudConfigurationError):
                cloud_client.CloudConfig.from_env()
        with mock.patch.dict(os.environ, {
            "PDF_MCP_CLOUD_URL": "http://cloud.example.test",
            "PDF_MCP_CLOUD_API_KEY": "key",
        }, clear=True):
            with self.assertRaises(cloud_client.CloudConfigurationError):
                cloud_client.CloudConfig.from_env()

    def test_localhost_http_is_allowed_for_development(self):
        with mock.patch.dict(os.environ, {
            "PDF_MCP_CLOUD_URL": "http://127.0.0.1:8000",
            "PDF_MCP_CLOUD_API_KEY": "key",
        }, clear=True):
            config = cloud_client.CloudConfig.from_env()
        self.assertEqual(config.base_url, "http://127.0.0.1:8000")

    def test_upload_uses_generic_filename_and_returns_quota(self):
        with mock.patch.dict(os.environ, self.environment, clear=True), \
                mock.patch.object(cloud_client.httpx, "Client", FakeClient):
            result = cloud_client.extract_tables(self.path, merge_multipage=True)

        call = FakeClient.calls[0]
        self.assertEqual(call["upload_name"], "document.pdf")
        self.assertNotIn("customer-secret-name", repr(call))
        self.assertEqual(call["data"]["merge_multipage"], "true")
        self.assertEqual(result["cloud_usage"]["remaining_operations"], 24)
        self.assertNotIn(self.environment["PDF_MCP_CLOUD_API_KEY"], str(result))

    def test_table_csv_returns_structured_response(self):
        FakeClient.response = FakeResponse(body={
            "result": {"csv": "A,B\n1,2\n", "warnings": []},
            "usage": {"remaining_operations": 20},
        })
        with mock.patch.dict(os.environ, self.environment, clear=True), \
                mock.patch.object(cloud_client.httpx, "Client", FakeClient):
            result = cloud_client.table_to_csv(self.path, index=1)
        self.assertEqual(result["csv"], "A,B\n1,2\n")
        self.assertEqual(FakeClient.calls[0]["data"]["index"], "1")

    def test_authentication_and_quota_errors_do_not_expose_key(self):
        for status in (401, 429):
            FakeClient.response = FakeResponse(status_code=status, body={"detail": "rejected"})
            with self.subTest(status=status), \
                    mock.patch.dict(os.environ, self.environment, clear=True), \
                    mock.patch.object(cloud_client.httpx, "Client", FakeClient):
                with self.assertRaises(cloud_client.CloudServiceError) as raised:
                    cloud_client.extract_tables(self.path)
                self.assertNotIn(self.environment["PDF_MCP_CLOUD_API_KEY"], str(raised.exception))

    def test_usage_endpoint(self):
        FakeClient.response = FakeResponse(body={
            "period": "2026-08",
            "operations": 3,
            "remaining_operations": 22,
        })
        with mock.patch.dict(os.environ, self.environment, clear=True), \
                mock.patch.object(cloud_client.httpx, "Client", FakeClient):
            result = cloud_client.usage()
        self.assertEqual(result["operations"], 3)
        self.assertEqual(FakeClient.calls[0]["method"], "GET")


if __name__ == "__main__":
    unittest.main()
