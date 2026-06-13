"""Object-level diff sections (extensions, foreign data wrappers, servers, events).

Extracted from ``core/logger/formatters/formatter.py`` (PR-H11) as part of
the per-format sibling split. The mixin is consumed by
``OutputFormatter`` so the bound-method call sites continue to work
unchanged.
"""

from core.logger.results import DiffResult


class _DiffObjectFormatterMixin:
    """Mixin providing extension/FDW/server/event diff section formatters."""

    def _format_extension_diff(self, result: DiffResult) -> str:
        """Format extensions diff section."""
        if not result.schema_diff:
            return ""
        has_exts = (
            getattr(result, "missing_extensions", [])
            or getattr(result, "extra_extensions", [])
            or getattr(result.schema_diff, "modified_extensions", [])
        )
        if not has_exts:
            return ""
        lines = []

        if getattr(result, "missing_extensions", []):
            lines.append(f"\nMissing Extensions ({len(result.missing_extensions)}):")
            for ext in result.missing_extensions:
                lines.append(f"  - {ext}")

        if getattr(result, "extra_extensions", []):
            lines.append(f"\nExtra Extensions ({len(result.extra_extensions)}):")
            for ext in result.extra_extensions:
                lines.append(f"  + {ext}")

        if getattr(result.schema_diff, "modified_extensions", []):
            lines.append(f"\nModified Extensions ({len(result.schema_diff.modified_extensions)}):")
            for ext_diff in result.schema_diff.modified_extensions:
                severity_symbol = "✗" if ext_diff.severity.value == "error" else "⚠"
                lines.append(
                    f"\n  Extension: {ext_diff.extension_name} "
                    f"[{ext_diff.severity.value.upper()}] {severity_symbol}"
                )
                lines.append("  " + "-" * 60)
                if ext_diff.version_changed:
                    expected, actual = ext_diff.version_changed
                    lines.append(f"    ⚠ Version: {expected or 'n/a'} → {actual or 'n/a'}")
                if ext_diff.schema_changed:
                    expected, actual = ext_diff.schema_changed
                    lines.append(f"    ⚠ Schema: {expected or 'n/a'} → {actual or 'n/a'}")

        return "\n".join(lines)

    def _format_fdw_diff(self, result: DiffResult) -> str:
        """Format foreign data wrappers diff section."""
        if not result.schema_diff:
            return ""
        has_fdw = (
            getattr(result, "missing_foreign_data_wrappers", [])
            or getattr(result, "extra_foreign_data_wrappers", [])
            or getattr(result.schema_diff, "modified_foreign_data_wrappers", [])
        )
        if not has_fdw:
            return ""
        lines = []

        if getattr(result, "missing_foreign_data_wrappers", []):
            lines.append(
                f"\nMissing Foreign Data Wrappers ({len(result.missing_foreign_data_wrappers)}):"
            )
            for fdw in result.missing_foreign_data_wrappers:
                lines.append(f"  - {fdw}")

        if getattr(result, "extra_foreign_data_wrappers", []):
            lines.append(
                f"\nExtra Foreign Data Wrappers ({len(result.extra_foreign_data_wrappers)}):"
            )
            for fdw in result.extra_foreign_data_wrappers:
                lines.append(f"  + {fdw}")

        if getattr(result.schema_diff, "modified_foreign_data_wrappers", []):
            lines.append(
                f"\nModified Foreign Data Wrappers ({len(result.schema_diff.modified_foreign_data_wrappers)}):"
            )
            for fdw_diff in result.schema_diff.modified_foreign_data_wrappers:
                lines.append(
                    f"\n  Foreign Data Wrapper: {fdw_diff.fdw_name} "
                    f"[{fdw_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)
                if fdw_diff.handler_changed:
                    expected, actual = fdw_diff.handler_changed
                    lines.append(f"    ⚠ Handler: {expected or 'n/a'} → {actual or 'n/a'}")
                if fdw_diff.validator_changed:
                    expected, actual = fdw_diff.validator_changed
                    lines.append(f"    ⚠ Validator: {expected or 'n/a'} → {actual or 'n/a'}")
                if fdw_diff.options_changed:
                    expected, actual = fdw_diff.options_changed
                    lines.append(f"    ⚠ Options: {expected or 'n/a'} → {actual or 'n/a'}")

        return "\n".join(lines)

    def _format_server_diff(self, result: DiffResult) -> str:
        """Format foreign servers diff section."""
        if not result.schema_diff:
            return ""
        has_servers = (
            getattr(result, "missing_foreign_servers", [])
            or getattr(result, "extra_foreign_servers", [])
            or getattr(result.schema_diff, "modified_foreign_servers", [])
        )
        if not has_servers:
            return ""
        lines = []

        if getattr(result, "missing_foreign_servers", []):
            lines.append(f"\nMissing Foreign Servers ({len(result.missing_foreign_servers)}):")
            for server in result.missing_foreign_servers:
                lines.append(f"  - {server}")

        if getattr(result, "extra_foreign_servers", []):
            lines.append(f"\nExtra Foreign Servers ({len(result.extra_foreign_servers)}):")
            for server in result.extra_foreign_servers:
                lines.append(f"  + {server}")

        if getattr(result.schema_diff, "modified_foreign_servers", []):
            lines.append(
                f"\nModified Foreign Servers ({len(result.schema_diff.modified_foreign_servers)}):"
            )
            for server_diff in result.schema_diff.modified_foreign_servers:
                lines.append(
                    f"\n  Foreign Server: {server_diff.server_name} "
                    f"[{server_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)
                if server_diff.fdw_changed:
                    expected, actual = server_diff.fdw_changed
                    lines.append(f"    ⚠ FDW: {expected or 'n/a'} → {actual or 'n/a'}")
                if server_diff.host_changed:
                    expected, actual = server_diff.host_changed
                    lines.append(f"    ⚠ Host: {expected or 'n/a'} → {actual or 'n/a'}")
                if server_diff.port_changed:
                    expected, actual = server_diff.port_changed
                    lines.append(f"    ⚠ Port: {expected or 'n/a'} → {actual or 'n/a'}")
                if server_diff.dbname_changed:
                    expected, actual = server_diff.dbname_changed
                    lines.append(f"    ⚠ Database: {expected or 'n/a'} → {actual or 'n/a'}")
                if server_diff.options_changed:
                    expected, actual = server_diff.options_changed
                    lines.append(f"    ⚠ Options: {expected or 'n/a'} → {actual or 'n/a'}")

        return "\n".join(lines)

    def _format_event_diff(self, result: DiffResult) -> str:
        """Format events diff section."""
        if not result.schema_diff:
            return ""
        has_events = (
            getattr(result, "missing_events", [])
            or getattr(result, "extra_events", [])
            or getattr(result.schema_diff, "modified_events", [])
        )
        if not has_events:
            return ""
        lines = []

        if getattr(result, "missing_events", []):
            lines.append(f"\nMissing Events ({len(result.missing_events)}):")
            for event in result.missing_events:
                lines.append(f"  - {event}")

        if getattr(result, "extra_events", []):
            lines.append(f"\nExtra Events ({len(result.extra_events)}):")
            for event in result.extra_events:
                lines.append(f"  + {event}")

        if getattr(result.schema_diff, "modified_events", []):
            lines.append(f"\nModified Events ({len(result.schema_diff.modified_events)}):")
            for event_diff in result.schema_diff.modified_events:
                lines.append(
                    f"\n  Event: {event_diff.event_name} [{event_diff.severity.value.upper()}]"
                )
                lines.append("  " + "-" * 60)
                if event_diff.definition_changed:
                    lines.append("    ⚠ Definition changed")
                if event_diff.schedule_changed:
                    expected, actual = event_diff.schedule_changed
                    lines.append(f"    ⚠ Schedule: {expected or 'n/a'} → {actual or 'n/a'}")
                if getattr(event_diff, "enabled_changed", None):
                    expected, actual = event_diff.enabled_changed
                    lines.append(f"    ⚠ Enabled: {expected} → {actual}")

        return "\n".join(lines)
