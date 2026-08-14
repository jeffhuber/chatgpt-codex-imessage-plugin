from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import check_version


class ChangelogVersionTests(unittest.TestCase):
    def check(self, content: str, version: str = "1.2.0") -> tuple[bool, str]:
        with tempfile.TemporaryDirectory(prefix="chatgpt-version-check-") as td:
            root = Path(td)
            (root / "CHANGELOG.md").write_text(content, encoding="utf-8")
            with mock.patch.object(check_version, "REPO_ROOT", root):
                return check_version.check_changelog(version)

    def test_historical_release_date_remains_valid(self) -> None:
        self.assertEqual(
            self.check("# Changelog\n\n## 1.2.0 - 2020-01-02\n"),
            (True, ""),
        )

    def test_duplicate_version_headings_are_rejected(self) -> None:
        valid, error = self.check(
            "# Changelog\n\n"
            "## 1.2.0 - 2020-01-02\n\n"
            "## 1.2.0 - 2020-01-03\n"
        )
        self.assertFalse(valid)
        self.assertIn("found 2", error)

    def test_invalid_calendar_date_is_rejected(self) -> None:
        valid, error = self.check("# Changelog\n\n## 1.2.0 - 2020-02-31\n")
        self.assertFalse(valid)
        self.assertIn("invalid date", error)

    def test_heading_cannot_span_lines(self) -> None:
        valid, error = self.check(
            "# Changelog\n\n## 1.2.0\n  - 2020-01-02\n"
        )
        self.assertFalse(valid)
        self.assertIn("found 0", error)

    def test_missing_version_heading_is_rejected(self) -> None:
        valid, error = self.check("# Changelog\n\n## 1.1.0 - 2020-01-02\n")
        self.assertFalse(valid)
        self.assertIn("found 0", error)


if __name__ == "__main__":
    unittest.main()
