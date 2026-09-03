"""DB2 database provider plugin."""

__plugin_name__ = "db2"
__plugin_version__ = "1.0.0"
__plugin_description__ = "DB2 database provider"
__plugin_dialects__ = ["db2", "ibm_db_sa"]
__plugin_class__ = "Db2Provider"

from .provider import Db2Provider

__all__ = ["Db2Provider"]
