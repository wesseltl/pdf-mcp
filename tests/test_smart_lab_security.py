"""Security-boundary tests for local operator credentials."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from smart_lab_index.core.security import (
    CredentialError,
    create_operator_token,
    load_operator_token,
)


class SmartLabCredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.token_path = Path(self.temporary.name) / "private" / "operator.token"

    def test_created_token_is_private_and_loadable(self) -> None:
        token = create_operator_token(self.token_path)

        self.assertEqual(load_operator_token(self.token_path), token)
        self.assertEqual(self.token_path.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(CredentialError, "already exists"):
            create_operator_token(self.token_path)

    @unittest.skipUnless(os.name == "posix", "POSIX permission check")
    def test_group_or_world_readable_token_is_rejected(self) -> None:
        create_operator_token(self.token_path)
        self.token_path.chmod(0o640)

        with self.assertRaisesRegex(CredentialError, "permissions"):
            load_operator_token(self.token_path)

    @unittest.skipUnless(os.name == "posix", "POSIX link checks")
    def test_linked_token_files_are_rejected(self) -> None:
        create_operator_token(self.token_path)
        symlink = self.token_path.with_name("operator-symlink.token")
        symlink.symlink_to(self.token_path)
        with self.assertRaisesRegex(CredentialError, "symbolic link"):
            load_operator_token(symlink)

        hardlink = self.token_path.with_name("operator-hardlink.token")
        os.link(self.token_path, hardlink)
        with self.assertRaisesRegex(CredentialError, "hard links"):
            load_operator_token(self.token_path)


if __name__ == "__main__":
    unittest.main()
