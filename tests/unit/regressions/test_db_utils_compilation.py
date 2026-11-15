"""Fresh compilation of the database utilities must be warning-free."""

import unittest
import warnings
from pathlib import Path


class TestDbUtilsCompilation(unittest.TestCase):
    def test_compiles_without_syntax_warnings(self):
        source = Path(__file__).resolve().parents[3] / "dblift" / "cli" / "db_utils.py"
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(source.read_bytes(), str(source), "exec")
