"""Redshift database provider plugin (PostgreSQL-compatible)."""

__plugin_name__ = "redshift"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Redshift database provider"
__plugin_dialects__ = ["redshift"]
__plugin_transport__ = "native"
__plugin_class__ = "RedshiftProvider"

from .provider import RedshiftProvider

__all__ = ["RedshiftProvider"]
