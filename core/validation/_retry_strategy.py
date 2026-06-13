"""Drop-and-recreate retry strategy extracted from ``RoundTripTester``.

Oracle / DB2 "table already exists" CREATE failures are recovered by
re-issuing ``DROP TABLE`` against a sequence of candidate identifier
spellings (the data-dictionary may store the name upper-cased,
lower-cased, or as quoted). ``_RetryStrategyMixin`` provides the loop
and the dialect-specific candidate builder.

Logger name is hardcoded to ``core.validation.round_trip_tester`` so unit
tests using ``assertLogs("core.validation.round_trip_tester", ...)`` still
observe records emitted from this module.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    from db.base_quirks import BaseQuirks

# Preserve the historical logger name so `assertLogs("core.validation.round_trip_tester", ...)`
# in the unit tests keeps capturing records emitted from this mixin.
logger = logging.getLogger("core.validation.round_trip_tester")


class _RetryStrategyMixin:
    """Drop-and-recreate-on-error retry for ``RoundTripTester``.

    Requires the composing class to expose: ``dialect``, ``test_provider``,
    ``test_schema``, and ``_quirks``.
    """

    # Attributes supplied by the composing class (declared for mypy clarity).
    dialect: str
    test_provider: Any
    test_schema: str
    _quirks: "BaseQuirks"

    def _retry_drop_and_create(self, statement: str) -> bool:
        """Retry drop+create for Oracle/DB2 when table already exists. Returns True on success."""
        table_match = re.search(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))\.)?(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))',
            statement,
            re.IGNORECASE,
        )
        if not table_match:
            return False

        schema_name = table_match.group(1) or table_match.group(2) or self.test_schema
        table_name = table_match.group(3) or table_match.group(4)
        schema_was_quoted = table_match.group(1) is not None
        table_was_quoted = table_match.group(3) is not None

        if schema_was_quoted:
            schema_clean = f'"{schema_name}"'
        else:
            schema_clean = (
                schema_name.replace('"', "").upper() if schema_name else self.test_schema.upper()
            )

        if table_was_quoted:
            table_clean = f'"{table_name}"'
        else:
            table_clean = table_name.replace('"', "").upper()

        drop_strategies = self._build_retry_drop_strategies(schema_clean, table_clean)

        dropped = False
        for drop_target in drop_strategies:
            # Per-dialect DROP rendering lives on the Quirks layer:
            #   - Oracle: BEGIN/EXCEPTION wrapper + CASCADE CONSTRAINTS.
            #   - DB2:    plain DROP TABLE (no IF EXISTS).
            #   - Others: generic DROP TABLE IF EXISTS (BaseQuirks default).
            drop_retry_sql = self._quirks.render_round_trip_drop_table_sql(drop_target)
            try:
                self.test_provider.query_executor.execute_statement(  # type: ignore[attr-defined]
                    self.test_provider.connection, drop_retry_sql, []  # type: ignore[attr-defined]
                )
                if hasattr(self.test_provider.connection, "commit"):  # type: ignore[attr-defined]
                    self.test_provider.connection.commit()  # type: ignore[attr-defined]
                logger.debug(
                    f"{self.dialect.upper()}: Successfully dropped table {drop_target} after retry"
                )
                dropped = True
                break
            except Exception as drop_retry_err:
                logger.debug(
                    f"{self.dialect.upper()}: Drop strategy {drop_target} failed: {drop_retry_err}"
                )

        if dropped:
            try:
                self.test_provider.query_executor.execute_statement(  # type: ignore[attr-defined]
                    self.test_provider.connection, statement, []  # type: ignore[attr-defined]
                )
                logger.debug(f"{self.dialect.upper()}: Successfully created table after retry")
                return True
            except Exception as create_retry_err:
                logger.debug(f"{self.dialect.upper()}: CREATE retry failed: {create_retry_err}")
        else:
            logger.debug(f"{self.dialect.upper()}: All DROP strategies failed, cannot retry CREATE")
        return False

    def _build_retry_drop_strategies(self, schema_clean: str, table_clean: str) -> List[str]:
        """Build list of DROP target strings to try for retry.

        Delegates to ``self._quirks.build_retry_drop_strategies`` so each
        dialect owns its own data-dictionary lookup (Oracle ``ALL_TABLES``,
        DB2 ``SYSCAT.TABLES``). Default base quirks returns the obvious
        two forms — adequate for vendors that don't take this retry path
        (``retry_drop_create_on_error = False``).
        """
        return list(
            self._quirks.build_retry_drop_strategies(
                self.test_provider.query_executor,  # type: ignore[attr-defined]
                self.test_provider.connection,  # type: ignore[attr-defined]
                schema_clean,
                table_clean,
            )
        )
