"""Keep package and MCP Registry versions aligned."""
import importlib.metadata
import json
import os
import unittest

from pdf_mcp import __version__


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestVersionConsistency(unittest.TestCase):
    def test_distribution_package_and_server_versions_match(self):
        with open(os.path.join(ROOT, "server.json"), encoding="utf-8") as f:
            server = json.load(f)

        distribution_version = importlib.metadata.version("pdf-agent-mcp")
        self.assertEqual(__version__, distribution_version)
        self.assertEqual(server["version"], distribution_version)
        self.assertEqual(server["packages"][0]["version"], distribution_version)


if __name__ == "__main__":
    unittest.main()
