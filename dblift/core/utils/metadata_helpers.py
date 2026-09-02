"""Neutral metadata helpers shared by introspection extractors and plugin quirks."""

import re
from typing import Any, Dict, List, Optional

from dblift.core.sql_model.base import ConstraintType, SqlConstraint

_PG_SIMPLE_OPERAND_RE = (
    r"(?:'(?:''|[^'])*'|"
    r'(?:(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*))*))'
)
_PG_TEXT_CAST_RE = re.compile(
    rf"\bCAST\(\s*(?P<operand>{_PG_SIMPLE_OPERAND_RE})\s+AS\s+TEXT\s*\)",
    re.IGNORECASE,
)
_PG_TEXT_COLON_CAST_RE = re.compile(
    rf"(?P<operand>{_PG_SIMPLE_OPERAND_RE})\s*::\s*TEXT\b",
    re.IGNORECASE,
)


def normalize_postgresql_index_predicate(predicate: Optional[str]) -> Optional[str]:
    """Remove redundant PostgreSQL text casts from simple index predicates."""
    if predicate is None:
        return None

    def replace_cast(match: re.Match[str]) -> str:
        return re.sub(r"\s*\.\s*", ".", match.group("operand").strip())

    normalized = _PG_TEXT_CAST_RE.sub(replace_cast, predicate)
    normalized = _PG_TEXT_COLON_CAST_RE.sub(replace_cast, normalized)
    return normalized


def _build_unique_constraints_from_dict(
    extractor: Any, unique_indexes: Dict[str, Dict[str, Any]]
) -> List[SqlConstraint]:
    """Convert per-index dictionaries into sanitized unique constraints."""
    constraints: List[SqlConstraint] = []
    for idx_data in unique_indexes.values():
        idx_data["columns"].sort(key=lambda x: x["position"])
        constraints.append(
            SqlConstraint(
                constraint_type=ConstraintType.UNIQUE,
                name=extractor._sanitize_constraint_name(idx_data["name"]),
                column_names=[col["column"] for col in idx_data["columns"]],
                dialect=extractor.dialect,
            )
        )
    return constraints


def _fetch_mysql_show_create_routine(
    extractor: Any, schema: str, name: str, kind: str, status: Any = None
) -> Optional[str]:
    """Fetch a full MySQL/MariaDB routine definition through SHOW CREATE."""
    keyword = "PROCEDURE" if kind == "procedure" else "FUNCTION"
    try:
        safe_schema = schema.replace("`", "``")
        safe_name = name.replace("`", "``")
        show_sql = f"SHOW CREATE {keyword} `{safe_schema}`.`{safe_name}`"
        show_rows = extractor.provider.query_executor.execute_query(
            extractor.connection, show_sql, []
        )
        if not show_rows:
            return None
        title = f"Create {keyword.title()}"
        create_stmt = show_rows[0].get(title) or show_rows[0].get(title.lower())
        if create_stmt:
            return str(create_stmt)
    except Exception as exc:
        extractor.log.debug(f"Could not fetch SHOW CREATE {keyword} for {schema}.{name}: {exc}")
        if status:
            status.add_property_status("definition", False)
        if extractor.result_tracker:
            extractor.result_tracker._track_warning(
                f"Could not fetch {keyword.lower()} definition: {exc}",
                object_type=keyword.lower(),
                object_name=name,
                property_name="definition",
                exception=exc,
            )
    return None
