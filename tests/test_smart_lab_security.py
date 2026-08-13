"""Security-boundary tests for local operator credentials."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from smart_lab_index.core.security import (
    CredentialError,
    _is_systemd_credential,
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

    @unittest.skipUnless(os.name == "posix", "POSIX systemd credential contract")
    def test_systemd_credential_contract_is_root_owned_and_tightly_scoped(self) -> None:
        credential_directory = Path("/run/credentials/laboverlay.service")
        target = credential_directory / "operator.token"
        directory = SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o550,
            st_uid=0,
            st_gid=0,
        )
        credential = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o440,
            st_uid=0,
            st_gid=0,
        )
        with (
            patch.dict(
                os.environ,
                {"CREDENTIALS_DIRECTORY": str(credential_directory)},
            ),
            patch.object(Path, "lstat", return_value=directory),
        ):
            self.assertTrue(_is_systemd_credential(target, credential))
            self.assertFalse(
                _is_systemd_credential(
                    target,
                    SimpleNamespace(
                        st_mode=stat.S_IFREG | 0o444,
                        st_uid=0,
                        st_gid=0,
                    ),
                )
            )
            self.assertFalse(
                _is_systemd_credential(
                    credential_directory.parent / "other.token",
                    credential,
                )
            )

    @unittest.skipUnless(os.name == "posix", "POSIX systemd credential contract")
    def test_systemd_managed_group_readable_token_can_be_loaded(self) -> None:
        token = create_operator_token(self.token_path)
        self.token_path.chmod(0o440)

        with patch(
            "smart_lab_index.core.security._is_systemd_credential",
            return_value=True,
        ):
            self.assertEqual(load_operator_token(self.token_path), token)

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
