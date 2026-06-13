"""
Trigger extractor for schema introspection.

This module extracts trigger metadata from databases using vendor-specific queries.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from core.introspection._utils import get_row_value
from core.introspection.extractors.base_extractor import BaseExtractor
from core.sql_model.trigger import Trigger

logger = logging.getLogger(__name__)


def _to_bool(value: Any) -> Optional[bool]:
    """Convert value to boolean, handling string representations."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().upper()
    if text in {"TRUE", "T", "YES", "Y", "1"}:
        return True
    if text in {"FALSE", "F", "NO", "N", "0"}:
        return False
    return None


class TriggerExtractor(BaseExtractor):
    """
    Extractor for triggers.

    This extractor handles trigger metadata extraction using vendor-specific queries
    for comprehensive metadata coverage.
    """

    def get_triggers(self, schema: str, table: Optional[str] = None) -> List[Trigger]:
        """
        Get triggers in a schema (optionally filtered by table).

        Args:
            schema: Schema name
            table: Optional table name to filter triggers

        Returns:
            List of Trigger objects
        """
        if not self.vendor_queries or not self.vendor_queries.supports_triggers():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_triggers_query(schema, table)
            if not sql:
                self.log.debug("Trigger introspection not supported for this dialect")
                return []

            self.log.debug(f"Executing get_triggers query for schema: {schema}, table: {table}")
            results = self.provider.query_executor.execute_query(self.connection, sql, params)

            self.log.debug(f"Query returned {len(results)} trigger(s)")

            triggers: Dict[tuple[str, str], Trigger] = {}
            for row in results:
                # Handle DB2 returning original column names instead of aliases
                trigger_name = (
                    get_row_value(row, "trigger_name") or row.get("TRIGNAME") or row.get("trigname")
                )
                table_name = (
                    get_row_value(row, "table_name") or row.get("TABNAME") or row.get("tabname")
                )
                if not trigger_name or not table_name:
                    self.log.debug(f"Skipping trigger row with missing name/table: {row}")
                    continue

                key = (trigger_name, table_name)
                trigger = triggers.get(key)

                if not trigger:
                    # Track trigger capture status
                    trigger_status = None
                    if self.result_tracker:
                        trigger_status = self.result_tracker._track_object_status(
                            "trigger", trigger_name, schema
                        )

                    enabled_token = get_row_value(row, "tgenabled")
                    enabled = True
                    if enabled_token is not None:
                        enabled = str(enabled_token).upper() != "D"

                    trigger = Trigger(
                        name=trigger_name,
                        table_name=table_name,
                        schema=schema,
                        timing=get_row_value(row, "action_timing"),
                        events=[],
                        orientation=get_row_value(row, "action_orientation"),
                        definition=get_row_value(row, "trigger_definition")
                        or get_row_value(row, "action_statement"),
                        dialect=self.dialect,
                        enabled=enabled,
                        function_schema=get_row_value(row, "function_schema"),
                        function_name=get_row_value(row, "function_name"),
                        function_arguments=get_row_value(row, "function_arguments"),
                        when_clause=get_row_value(row, "when_clause"),
                        is_constraint_trigger=_to_bool(get_row_value(row, "is_constraint_trigger")),
                        constraint_deferrable=_to_bool(get_row_value(row, "tgdeferrable")),
                        constraint_initially_deferred=_to_bool(
                            get_row_value(row, "tginitdeferred")
                        ),
                    )

                    # Dialect-specific trigger attributes (MySQL DEFINER, ...)
                    # routed through the per-plugin quirks hook so the
                    # extractor stays dialect-agnostic.
                    from db.provider_registry import ProviderRegistry

                    quirks = ProviderRegistry.get_quirks(self.dialect or "")
                    quirks.enrich_trigger_from_row(trigger, row, trigger_status)

                    # Track property capture
                    if trigger_status:
                        trigger_status.add_property_status(
                            "definition", trigger.definition is not None
                        )
                        trigger_status.add_property_status(
                            "events", len(trigger.events) > 0 if trigger.events else False
                        )
                        trigger_status.add_property_status("enabled", enabled is not None)

                    triggers[key] = trigger

                # Parse events (may be comma or space separated, Oracle returns "INSERT OR UPDATE")
                event_str = get_row_value(row, "event_manipulation") or ""
                raw_event_tokens = [
                    token.strip() for token in re.split(r"[,\s]+", event_str) if token.strip()
                ]
                new_events = [
                    token.upper()
                    for token in raw_event_tokens
                    if token.upper() not in {"OR", "AND"}
                ]
                existing = {evt.upper(): idx for idx, evt in enumerate(trigger.events or [])}
                for evt in new_events:
                    if evt not in existing:
                        trigger.events.append(evt)

            trigger_list = list(triggers.values())
            table_filter = f" on table {table}" if table else ""
            self.log.debug(f"Found {len(trigger_list)} triggers in schema {schema}{table_filter}")

            return trigger_list

        except Exception as e:
            logger.warning(f"Error getting triggers for schema {schema}: {e}")
            self.log.warning(f"Could not get triggers for schema {schema}: {e}")
            if self.result_tracker:
                self.result_tracker._track_error(
                    f"Error getting triggers: {e}",
                    object_type="schema",
                    object_name=schema,
                    property_name="triggers",
                    exception=e,
                )
            return []
