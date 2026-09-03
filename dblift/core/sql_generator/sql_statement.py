"""Re-export shim - SqlStatement now lives in core.state.sql_statement."""

from dblift.core.state.sql_statement import GenerationOptions, SqlStatement

__all__ = ["GenerationOptions", "SqlStatement"]
