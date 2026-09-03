"""MariaDB database provider plugin (Epic 26 story 26-13)."""

from typing import List

__plugin_name__ = "mariadb"
__plugin_version__ = "1.0.0"
__plugin_description__ = "MariaDB database provider"
__plugin_dialects__: List[str] = ["mariadb"]
__plugin_class__ = "MariadbProvider"

from .provider import MariadbProvider

__all__ = ["MariadbProvider"]
