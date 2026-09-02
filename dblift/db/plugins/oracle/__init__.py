"""Oracle database provider plugin."""

__plugin_name__ = "oracle"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Oracle database provider"
__plugin_dialects__ = ["oracle"]
__plugin_class__ = "OracleProvider"

from .provider import OracleProvider

__all__ = ["OracleProvider"]
