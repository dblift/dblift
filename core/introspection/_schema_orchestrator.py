"""Whole-schema introspection orchestrator.

Extracted from :class:`core.introspection.schema_introspector.SchemaIntrospector`
to keep that class focused on per-kind ``get_X`` entry points and
extractor lifecycle. The orchestrator stitches together a complete
schema snapshot by calling each ``get_X`` in turn, enriching tables
with computed columns / identity / check constraints / partitions /
vendor properties, and rolling up object counts.

The function takes ``si: "SchemaIntrospector"`` as its first argument
(structural typing — anything that exposes the ``get_X`` methods and
``vendor_queries`` / ``log`` / ``enrich_columns_*`` /
``enrich_table_with_partition_scheme`` / ``get_check_constraints`` /
``get_indexes`` / ``get_table_partitions`` works). Kept as a module
function rather than a class so the SchemaIntrospector instance stays
the single source of state.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List


def introspect_schema(si: Any, schema: str, **kwargs: Any) -> Dict[str, Any]:
    """Introspect a schema end-to-end and return a structured snapshot dict.

    See :meth:`SchemaIntrospector.introspect_schema` for the documented
    return shape; the orchestrator delegates every per-kind lookup back
    to ``si`` so capability gating + vendor query dispatch + extractor
    lifecycle all live on the introspector instance.

    **Partial results.** The ``get_X`` extractors raise when they cannot
    *read* an object type, rather than returning ``[]`` and making an
    unreadable schema look like an empty one. Aborting the whole
    introspection on the first such failure would be worse for a caller
    than the old silence was — it throws away the tables, columns,
    indexes and partitions already collected. So every schema-level
    object-type lookup is run through :func:`_collect`: a failure records
    the object type and the reason, leaves that type at its initialised
    empty value, and lets the remaining types proceed.

    A failure is reported through three channels, deliberately:

    * ``result["failures"]`` — a list of
      ``{"object_type", "error", "exception_type"}`` dicts, empty when
      nothing failed. **This is the channel that matters**, because it is
      the only one a caller gets without opting into anything. A caller
      that reads ``result["view_count"] == 0`` and nothing else would be
      back to the original bug — an unreadable type indistinguishable
      from an absent one — so the failure had to land on the object
      callers already read, next to the counts it explains.
    * ``si.log.error`` — visible in logs without any caller change.
    * ``si._track_error`` — for callers that called
      ``enable_result_tracking()``, so ``IntrospectionResult.success``
      and the error count stay honest.

    Table discovery is deliberately *not* collected this way and still
    aborts: columns, indexes and partitions all hang off the table list,
    so a snapshot that failed to read tables has nothing partial to
    return.
    """
    include_views = kwargs.get("include_views", True)
    include_sequences = kwargs.get("include_sequences", True)
    include_triggers = kwargs.get("include_triggers", True)
    include_procedures = kwargs.get("include_procedures", True)
    include_functions = kwargs.get("include_functions", True)

    result: Dict[str, Any] = {
        "schema": schema,
        "tables": [],
        "views": [],
        "materialized_views": [],
        "sequences": [],
        "triggers": [],
        "events": [],
        "procedures": [],
        "functions": [],
        "packages": [],
        "synonyms": [],
        "user_defined_types": [],
        "extensions": [],
        "indexes": {},
        "partitions": {},
        "table_count": 0,
        "view_count": 0,
        "materialized_view_count": 0,
        "sequence_count": 0,
        "trigger_count": 0,
        "event_count": 0,
        "procedure_count": 0,
        "function_count": 0,
        "package_count": 0,
        "synonym_count": 0,
        "user_defined_type_count": 0,
        "extension_count": 0,
        "total_columns": 0,
        "total_indexes": 0,
        "total_partitions": 0,
        "failures": [],
    }
    failures: List[Dict[str, str]] = result["failures"]

    def _collect(object_type: str, fetch: Callable[[], Any], default: Any) -> Any:
        """Run one object-type lookup, keeping the snapshot on failure.

        Returns whatever *fetch* returned, or *default* if it raised. A
        raised failure is appended to ``result["failures"]``, logged at
        error level, and recorded on the result tracker when the caller
        enabled one — see this module's docstring for why all three.
        """
        try:
            return fetch()
        except Exception as exc:
            failures.append(
                {
                    "object_type": object_type,
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                }
            )
            si.log.error(
                f"Could not read {object_type} for schema {schema}: {exc} "
                f"— continuing without them"
            )
            track_error = getattr(si, "_track_error", None)
            if callable(track_error):
                track_error(
                    f"Skipped {object_type} for schema {schema} after a read failure: {exc}",
                    object_type="schema",
                    object_name=schema,
                    property_name=object_type,
                    exception=exc,
                )
            return default

    si.log.info(f"Starting enhanced schema introspection: {schema}")

    try:
        # Get all tables with structural metadata (PK, FK, UK, columns)
        tables = si.get_tables(schema, include_views=False)
        result["tables"] = tables
        result["table_count"] = len(tables)

        # Enhance each table with vendor-specific metadata
        for table in tables:
            total_cols: int = result["total_columns"]
            result["total_columns"] = total_cols + len(table.columns)

            # Enrich columns with computed/generated column metadata
            if si.vendor_queries and si.vendor_queries.supports_computed_columns():
                si.enrich_columns_with_computed(schema, table.name, table.columns)

            # Enrich columns with identity/auto-increment metadata
            if si.vendor_queries:
                si.enrich_columns_with_identity(schema, table.name, table.columns)

            # Add check constraints from vendor queries (if not already added via _get_constraints)
            # Note: get_tables() already calls _get_constraints() which includes check constraints,
            # so we need to deduplicate here to avoid adding them twice
            if si.vendor_queries and si.vendor_queries.supports_check_constraints():
                # Build a set of existing constraint names (case-insensitive) for deduplication
                existing_constraint_names = {
                    c.name.strip().upper() if c.name else None for c in table.constraints if c.name
                }
                # Get check constraints and only add those that don't already exist
                check_constraints = si.get_check_constraints(schema, table.name)
                if check_constraints:
                    for check_constraint in check_constraints:
                        check_name_normalized = (
                            check_constraint.name.strip().upper() if check_constraint.name else None
                        )
                        # Skip if constraint already exists (by name)
                        if (
                            check_name_normalized
                            and check_name_normalized in existing_constraint_names
                        ):
                            si.log.debug(
                                f"Skipping duplicate check constraint "
                                f"{schema}.{table.name}.{check_constraint.name} "
                                f"(already exists in table constraints)"
                            )
                            continue
                        # Add the constraint
                        table.constraints.append(check_constraint)
                        if check_name_normalized:
                            existing_constraint_names.add(check_name_normalized)

            # Enrich table with partition scheme (method and columns only, not individual partitions)
            if si.vendor_queries:  # get_partition_scheme_query guaranteed in ABC
                si.enrich_table_with_partition_scheme(schema, table.name, table)

            # Get indexes
            indexes = si.get_indexes(schema, table.name)
            result["indexes"][table.name] = indexes
            total_idx: int = result["total_indexes"]
            result["total_indexes"] = total_idx + len(indexes)

            # Get table partitions (if supported)
            if si.vendor_queries and si.vendor_queries.supports_partitions():
                partitions = si.get_table_partitions(schema, table.name)
                if partitions:
                    result["partitions"][table.name] = partitions
                    if hasattr(table, "export_partitions"):
                        table.export_partitions = partitions
                    total_parts: int = result["total_partitions"]
                    result["total_partitions"] = total_parts + len(partitions)

        # Every lookup below goes through _collect: one object type that
        # cannot be read is recorded and skipped, not fatal.

        # Get views with definitions
        if include_views:
            views = _collect("views", lambda: si.get_views(schema), [])
            result["views"] = views
            result["view_count"] = len(views)

            # Get materialized views (if supported)
            if si.vendor_queries and si.vendor_queries.supports_materialized_views():
                materialized_views = _collect(
                    "materialized_views", lambda: si.get_materialized_views(schema), []
                )
                result["materialized_views"] = materialized_views
                result["materialized_view_count"] = len(materialized_views)

        # Get sequences
        if include_sequences:
            sequences = _collect("sequences", lambda: si.get_sequences(schema), [])
            result["sequences"] = sequences
            result["sequence_count"] = len(sequences)

        # Get triggers
        if include_triggers:
            triggers = _collect("triggers", lambda: si.get_triggers(schema), [])
            result["triggers"] = triggers
            result["trigger_count"] = len(triggers)

        # Get events (MySQL only)
        events = _collect("events", lambda: si.get_events(schema), [])
        if events:
            result["events"] = events
            result["event_count"] = len(events)

        # Get procedures
        if include_procedures:
            procedures = _collect("procedures", lambda: si.get_procedures(schema), [])
            result["procedures"] = procedures
            result["procedure_count"] = len(procedures)

        # Get functions
        if include_functions:
            functions = _collect("functions", lambda: si.get_functions(schema), [])
            result["functions"] = functions
            result["function_count"] = len(functions)

        # Get packages/modules (Oracle, DB2)
        packages = []
        if si.vendor_queries:
            packages = _collect("packages", lambda: si.get_packages(schema), [])
        result["packages"] = packages
        result["package_count"] = len(packages)

        # Get synonyms (if supported)
        synonyms = _collect("synonyms", lambda: si.get_synonyms(schema), [])
        result["synonyms"] = synonyms
        result["synonym_count"] = len(synonyms)

        # Get user-defined types
        user_defined_types = _collect(
            "user_defined_types", lambda: si.get_user_defined_types(schema), []
        )
        result["user_defined_types"] = user_defined_types
        result["user_defined_type_count"] = len(user_defined_types)

        # Get extensions (PostgreSQL-specific, database-wide)
        extensions = _collect("extensions", lambda: si.get_extensions(), [])
        result["extensions"] = extensions
        result["extension_count"] = len(extensions)

        msg_parts = [
            f"{result['table_count']} tables",
            f"{result['view_count']} views",
            f"{result['sequence_count']} sequences",
            f"{result['trigger_count']} triggers",
            f"{result['event_count']} events",
            f"{result['procedure_count']} procedures",
            f"{result['function_count']} functions",
            f"{result.get('package_count', 0)} packages",
            f"{result['synonym_count']} synonyms",
            f"{result['user_defined_type_count']} user-defined types",
            f"{result['total_columns']} columns",
            f"{result['total_indexes']} indexes",
        ]
        if result["materialized_view_count"] > 0:
            msg_parts.append(f"{result['materialized_view_count']} materialized views")
        if result["total_partitions"] > 0:
            msg_parts.append(f"{result['total_partitions']} partitions")
        if result["extension_count"] > 0:
            msg_parts.append(f"{result['extension_count']} extensions")
        si.log.debug(f"Enhanced introspection complete: {', '.join(msg_parts)}")
        if failures:
            si.log.warning(
                f"Enhanced introspection for schema {schema} is incomplete — "
                f"could not read: {', '.join(f['object_type'] for f in failures)}"
            )

    except Exception as e:
        # Only the table phase reaches here; every object-type lookup is
        # collected by _collect above. A failure to read tables leaves
        # nothing partial worth returning, so it still aborts.
        si.log.error(f"Error in enhanced introspection for schema {schema}: {e}")
        raise

    return result
