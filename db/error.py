"""
Database error classification and retry logic.

Provides pattern-based error classification along with exponential-backoff
retry for transient errors. Dialect-specific error patterns are supplied by
each dialect's quirks (``error_patterns()``); this module owns only the
generic, dialect-agnostic fallback patterns.
"""

import functools
import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union

from core.logger import NullLog


class ErrorCategory(str, Enum):
    """Classification categories for database errors."""

    NETWORK = "network"
    TIMEOUT = "timeout"
    LOCKING = "locking"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    SCHEMA = "schema"
    CONSTRAINT = "constraint"
    SQL_SYNTAX = "sql_syntax"
    RESOURCE = "resource"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


@dataclass
class DatabaseErrorInfo:
    """Detailed information about a database error."""

    exception: Exception
    sql: Optional[str] = None
    params: Optional[List[Any]] = None
    schema: Optional[str] = None
    category: ErrorCategory = ErrorCategory.UNKNOWN
    retry_count: int = 0
    context: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [f"[{self.category.value.upper()}]", str(self.exception)]
        if self.sql:
            # Truncate long SQL for readability
            sql_preview = self.sql[:120] + "..." if len(self.sql) > 120 else self.sql
            parts.append(f"SQL: {sql_preview}")
        if self.schema:
            parts.append(f"Schema: {self.schema}")
        if self.retry_count > 0:
            parts.append(f"Retry: {self.retry_count}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Generic (dialect-agnostic) error patterns
# ---------------------------------------------------------------------------
# Dialect-specific patterns now live in each plugin's quirks
# (``db/plugins/<X>/quirks.py`` ``error_patterns()``) and are sourced at
# classifier construction via ``ProviderRegistry.get_quirks`` (ADR-26 A2).

# Generic fallback patterns (checked for all database types)
_GENERIC_PATTERNS: List[Tuple[re.Pattern[str], ErrorCategory]] = [
    (
        re.compile(r"connection\s+(reset|refused|closed|lost|timed\s*out)", re.IGNORECASE),
        ErrorCategory.NETWORK,
    ),
    (re.compile(r"broken\s+pipe", re.IGNORECASE), ErrorCategory.NETWORK),
    (
        re.compile(r"socket\s+(error|closed|timeout|exception)", re.IGNORECASE),
        ErrorCategory.NETWORK,
    ),
    (re.compile(r"network\s+(error|unreachable)", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"insufficient\s+data", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"timeout|timed\s*out", re.IGNORECASE), ErrorCategory.TIMEOUT),
    (re.compile(r"deadlock", re.IGNORECASE), ErrorCategory.LOCKING),
    (re.compile(r"authentication\s+fail", re.IGNORECASE), ErrorCategory.AUTHENTICATION),
    (re.compile(r"permission\s+denied", re.IGNORECASE), ErrorCategory.AUTHORIZATION),
]

# Categories eligible for retry
_RETRYABLE_CATEGORIES = frozenset(
    {
        ErrorCategory.NETWORK,
        ErrorCategory.TIMEOUT,
        ErrorCategory.LOCKING,
    }
)


class DatabaseErrorClassifier:
    """Pattern-based database error classifier."""

    def __init__(self, db_type: str = "generic", log: Optional[Any] = None):
        """Initialize the classifier for *db_type*.

        ``db_type`` selects the dialect-specific pattern table from that
        dialect's quirks (``error_patterns()``); generic patterns are always
        appended afterwards. Unknown / missing ``db_type`` resolves to the
        ``BaseQuirks`` default (no dialect patterns), i.e. the generic-only
        ordering.
        """
        self.db_type = db_type.lower() if db_type else "generic"
        self.log = log if log is not None else NullLog()
        # Source dialect-specific patterns from the dialect's quirks (lazy
        # import avoids any import cycle through the plugin registry).
        from db.provider_registry import ProviderRegistry

        dialect_patterns = ProviderRegistry.get_quirks(self.db_type).error_patterns()
        # Build ordered pattern list: db-specific first, then generic
        self._patterns: List[Tuple[re.Pattern[str], ErrorCategory]] = list(dialect_patterns) + list(
            _GENERIC_PATTERNS
        )

    def categorize_error(self, error: Exception, sql: Optional[str] = None) -> ErrorCategory:
        """Classify a database exception into an ErrorCategory."""
        error_str = str(error)
        error_type = type(error).__name__

        # Also check the type name (e.g. "DisconnectException")
        text_to_search = f"{error_str} {error_type}"

        for pattern, category in self._patterns:
            if pattern.search(text_to_search):
                return category

        return ErrorCategory.UNKNOWN

    def is_retryable(
        self,
        category: ErrorCategory,
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> bool:
        """Return True if the error category is retryable and retries remain."""
        return category in _RETRYABLE_CATEGORIES and retry_count < max_retries


class RetryManager:
    """Executes operations with exponential-backoff retry on transient errors."""

    def __init__(
        self,
        error_classifier: DatabaseErrorClassifier,
        log: Optional[Any] = None,
        *,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_multiplier: float = 2.0,
        jitter: float = 0.2,
    ):
        """Initialize the retry manager with classifier and backoff parameters.

        Defaults give exponential backoff doubling from 1s up to 60s, with
        +/-20% jitter to avoid thundering-herd retries. ``error_classifier``
        decides which categories are retryable.
        """
        self.error_classifier = error_classifier
        self.log = log if log is not None else NullLog()
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier
        self.jitter = jitter

    def _compute_delay(self, attempt: int) -> float:
        """Compute delay with exponential backoff and jitter."""
        delay = min(self.base_delay * (self.backoff_multiplier**attempt), self.max_delay)
        jitter_amount = delay * self.jitter
        delay += random.uniform(-jitter_amount, jitter_amount)
        return max(0, delay)

    def execute_with_retry(
        self,
        operation: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute *operation* with retry on transient database errors.

        Special kwargs consumed (not forwarded to *operation*):
            sql, schema, context, exception_types
        """
        sql = kwargs.pop("sql", None)
        kwargs.pop("schema", None)
        kwargs.pop("context", None)
        exception_types = kwargs.pop("exception_types", Exception)

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                return operation(*args, **kwargs)
            except exception_types as exc:
                last_exception = exc
                category = self.error_classifier.categorize_error(exc, sql)

                if not self.error_classifier.is_retryable(category, attempt, self.max_retries):
                    raise

                delay = self._compute_delay(attempt)
                self.log.info(
                    f"Retryable {category.value} error (attempt {attempt + 1}/{self.max_retries}), "
                    f"retrying in {delay:.1f}s: {exc}"
                )
                time.sleep(delay)

        # Should not be reached, but just in case
        raise last_exception  # type: ignore[misc]

    def retry_on_db_error(
        self,
        *,
        max_retries: Optional[int] = None,
        exception_types: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception,
        sql: Optional[str] = None,
        schema: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Callable[..., Any]:
        """Return a decorator that wraps a function with retry logic."""
        effective_max = max_retries if max_retries is not None else self.max_retries

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(func)
            def wrapper(*args: Any, **kw: Any) -> Any:
                mgr = RetryManager(
                    self.error_classifier,
                    self.log,
                    max_retries=effective_max,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                    backoff_multiplier=self.backoff_multiplier,
                    jitter=self.jitter,
                )
                return mgr.execute_with_retry(
                    func,
                    *args,
                    sql=sql,
                    schema=schema,
                    context=context,
                    exception_types=exception_types,
                    **kw,
                )

            return wrapper

        return decorator
