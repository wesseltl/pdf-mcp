"""Tests for versioned extraction profiles."""
import json
import os
import tempfile
import unittest

from pdf_mcp import profiles


def basic_profile():
    return {
        "profile_schema_version": "1.0",
        "id": "test-profile",
        "version": "1.0.0",
        "description": "A test profile.",
        "table": {
            "columns": [
                {"name": "name", "aliases": ["Name"], "required": True},
                {"name": "amount", "aliases": ["Amount"], "type": "decimal"},
            ]
        },
    }


class ProfileTests(unittest.TestCase):
    def test_builtin_profiles_are_versioned_and_hashed(self):
        found = {profile["id"]: profile for profile in profiles.list_builtin_profiles()}
        self.assertEqual(set(found), {"invoice-lines-v1", "lab-coa-v1"})
        self.assertEqual(len(found["lab-coa-v1"]["sha256"]), 64)
        loaded = profiles.load_profile("lab-coa-v1")
        self.assertEqual(loaded["profile_schema_version"], "1.0")

    def test_custom_profile_loads_from_json(self):
        path = os.path.join(tempfile.mkdtemp(), "profile.json")
        with open(path, "w", encoding="utf-8") as output:
            json.dump(basic_profile(), output)
        loaded = profiles.load_profile(path)
        self.assertEqual(loaded["id"], "test-profile")
        self.assertEqual(loaded["table"]["header_search_rows"], 3)

    def test_hash_is_independent_of_object_key_order(self):
        profile = basic_profile()
        reversed_profile = dict(reversed(list(profile.items())))
        self.assertEqual(profiles.profile_sha256(profile), profiles.profile_sha256(reversed_profile))

    def test_ambiguous_aliases_are_rejected(self):
        profile = basic_profile()
        profile["table"]["columns"][1]["aliases"] = ["Name"]
        with self.assertRaises(profiles.ProfileError):
            profiles.validate_profile(profile)

    def test_invalid_numeric_bounds_are_rejected(self):
        profile = basic_profile()
        profile["table"]["columns"][1]["minimum"] = "not-a-number"
        with self.assertRaises(profiles.ProfileError):
            profiles.validate_profile(profile)

    def test_unknown_profile_keys_are_rejected_instead_of_ignored(self):
        profile = basic_profile()
        profile["table"]["columns"][0]["requried"] = True
        with self.assertRaises(profiles.ProfileError):
            profiles.validate_profile(profile)

    def test_canonical_column_names_are_stable_identifiers(self):
        profile = basic_profile()
        profile["table"]["columns"][0]["name"] = "Display Name"
        with self.assertRaises(profiles.ProfileError):
            profiles.validate_profile(profile)

    def test_non_finite_bounds_and_empty_aliases_are_rejected(self):
        profile = basic_profile()
        profile["table"]["columns"][1]["minimum"] = "NaN"
        with self.assertRaises(profiles.ProfileError):
            profiles.validate_profile(profile)
        profile = basic_profile()
        profile["table"]["columns"][0]["aliases"] = ["!!!"]
        with self.assertRaises(profiles.ProfileError):
            profiles.validate_profile(profile)

    def test_duplicate_json_keys_are_rejected(self):
        path = os.path.join(tempfile.mkdtemp(), "profile.json")
        with open(path, "w", encoding="utf-8") as output:
            output.write('{"id":"one","id":"two"}')
        with self.assertRaises(profiles.ProfileError):
            profiles.load_profile(path)


if __name__ == "__main__":
    unittest.main()
