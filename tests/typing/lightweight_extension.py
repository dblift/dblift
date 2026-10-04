"""Statically checked example of public extension imports."""

from typing import assert_type

from dblift.extensions.logging import OperationResult
from dblift.extensions.providers import PluginInfo, ProviderRegistry, ProviderTransport
from dblift.extensions.sql_model import Table

transport: ProviderTransport = "native"
plugins: list[PluginInfo] = ProviderRegistry.list_plugins()
result: OperationResult = OperationResult(success=True)
model_type: type[Table] = Table

assert_type(ProviderRegistry.list_plugins(), list[PluginInfo])
assert_type(OperationResult(success=True), OperationResult)
assert_type(Table, type[Table])
