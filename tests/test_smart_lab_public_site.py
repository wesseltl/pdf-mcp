"""Checks for the Smart Lab Index public request-only beta page."""

from __future__ import annotations

import json
import struct
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class AssetCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []
        self.json_ld: list[str] = []
        self._in_json_ld = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag in {"img", "script"} and attributes.get("src"):
            self.assets.append(attributes["src"])
        if tag == "source" and attributes.get("srcset"):
            self.assets.append(attributes["srcset"].split()[0])
        if tag == "link" and attributes.get("href"):
            self.assets.append(attributes["href"])
        self._in_json_ld = (
            tag == "script" and attributes.get("type") == "application/ld+json"
        )

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self.json_ld.append(data)


class SmartLabPublicSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (DOCS / "index.html").read_text(encoding="utf-8")
        cls.parser = AssetCollector()
        cls.parser.feed(cls.html)

    def test_homepage_leads_with_smart_lab_and_request_only_beta(self) -> None:
        self.assertIn('<h1 id="hero-title">Smart Lab Index</h1>', self.html)
        self.assertIn("Find what your lab has", self.html)
        self.assertIn("Request beta access", self.html)
        self.assertIn("Agent-readable beta offer", self.html)
        self.assertIn("No documents are needed to apply", self.html)
        self.assertNotIn("Download the simple app", self.html)
        self.assertNotIn("buy.stripe.com", self.html)

    def test_structured_data_describes_limited_free_smart_lab_beta(self) -> None:
        payload = json.loads("".join(self.parser.json_ld))
        self.assertEqual(payload["name"], "Smart Lab Index")
        self.assertEqual(payload["softwareVersion"], "0.4.0")
        self.assertEqual(payload["offers"]["price"], "0.00")
        self.assertEqual(
            payload["offers"]["availability"],
            "https://schema.org/LimitedAvailability",
        )

    def test_all_homepage_assets_are_local_and_present(self) -> None:
        for asset in self.parser.assets:
            parsed = urlparse(asset)
            if parsed.scheme or parsed.netloc or asset.startswith("#"):
                continue
            with self.subTest(asset=asset):
                self.assertTrue((DOCS / parsed.path).is_file())

    def test_workspace_images_have_stable_desktop_and_mobile_dimensions(self) -> None:
        expected = {
            "smart-lab-index-workspace.png": (1600, 1000),
            "smart-lab-index-workspace-mobile.png": (390, 1163),
        }
        for name, dimensions in expected.items():
            with self.subTest(image=name):
                with (DOCS / "assets" / name).open("rb") as image:
                    self.assertEqual(image.read(8), b"\x89PNG\r\n\x1a\n")
                    length = struct.unpack(">I", image.read(4))[0]
                    self.assertEqual(image.read(4), b"IHDR")
                    self.assertEqual(length, 13)
                    width, height = struct.unpack(">II", image.read(8))
                self.assertEqual((width, height), dimensions)


if __name__ == "__main__":
    unittest.main()
