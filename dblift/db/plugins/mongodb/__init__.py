"""MongoDB database provider plugin."""

__plugin_name__ = "mongodb"
__plugin_version__ = "1.0.0"
__plugin_description__ = "MongoDB provider"
__plugin_dialects__ = ["mongodb", "mongo"]
__plugin_transport__ = "native"
__plugin_class__ = "MongoDbProvider"

from .provider import MongoDbProvider

__all__ = ["MongoDbProvider"]
