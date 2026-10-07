import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from .env import load_local_env


class LocalEnvTests(TestCase):
    def test_quotes_comments_bom_and_literal_values(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text('\ufeff# local settings\nDG_FIRST=one # comment\n'
                'DG_SECRET="hash#with space"\nDG_EMPTY= # waiting\n'
                "DG_LITERAL='C:\\local\\${NAME}' # literal\n", encoding="utf-8")
            load_local_env(path)
            self.assertEqual(os.environ["DG_FIRST"], "one")
            self.assertEqual(os.environ["DG_SECRET"], "hash#with space")
            self.assertEqual(os.environ["DG_EMPTY"], "")
            self.assertEqual(os.environ["DG_LITERAL"], r"C:\local\${NAME}")

    def test_existing_environment_takes_precedence(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"DG_EXISTING": "from-process"}):
            path = Path(directory) / ".env"
            path.write_text("DG_EXISTING=from-file\n", encoding="utf-8")
            load_local_env(path)
            self.assertEqual(os.environ["DG_EXISTING"], "from-process")

    def test_missing_file_is_optional(self):
        with TemporaryDirectory() as directory:
            load_local_env(Path(directory) / "missing.env")

    def test_malformed_file_fails_without_exposing_values_or_partially_loading(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text('DG_FIRST=one\nDG_SECRET="private-test-value\n', encoding="utf-8")
            with self.assertRaises(ValueError) as error:
                load_local_env(path)
            self.assertNotIn("private-test-value", str(error.exception))
            self.assertNotIn("DG_FIRST", os.environ)
