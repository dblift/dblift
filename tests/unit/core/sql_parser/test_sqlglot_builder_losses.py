"""SQL-file models retain metadata already present in sqlglot's AST."""

import pytest

from dblift.core.sql_model.base import ConstraintType

pytestmark = pytest.mark.unit
DIALECTS = ("oracle", "sqlserver")
