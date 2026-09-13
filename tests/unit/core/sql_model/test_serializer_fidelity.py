"""Field-level serializer fidelity for every class in ``dblift.core.sql_model``.

A model file written by ``to_dict`` and read back by ``from_dict`` must be a
faithful copy of the object it came from. The per-class tests elsewhere in this
directory spot-check individual fields; nothing asserted that the serializer
covers the *constructor* — so a parameter added to ``__init__`` and never added
to ``to_dict`` is silently dropped on every round trip.

Two checks per constructor parameter, both name-agnostic so a key rename
(``is_nullable`` -> ``nullable``) needs no per-class table:

1. **Coverage by sentinel** — the instance is built with a unique string
   sentinel in every string/list/dict parameter; ``to_dict()`` is flattened to
   its leaf values and the sentinel must appear.
2. **Round trip by attribute** — ``cls.from_dict(instance.to_dict())`` must
   carry the same value on the attribute the parameter feeds, compared
   field-by-field for nested model objects (their ``__eq__`` is a deliberate
   partial comparison and would hide a dropped field).

Parameters that are *intentionally* not serialized go in
``INTENTIONALLY_NOT_SERIALIZED`` with a reason a reviewer can check.
Parameters that are dropped by accident are marked ``xfail(strict=True)`` in
``KNOWN_COVERAGE_GAPS`` / ``KNOWN_ROUND_TRIP_GAPS`` with the observed loss.
Strict, so removing a gap without removing its entry fails the suite.
"""

from __future__ import annotations

import enum
import importlib
import inspect
import json
import pkgutil
import sys
import typing
from typing import Any, Dict, FrozenSet, Iterator, List, NamedTuple, Optional, Tuple

import pytest

from dblift.core import sql_model as sql_model_package
from dblift.core.sql_model import Index, Parameter, Table
from dblift.core.sql_model._base_sql_constraint import ConstraintType
from dblift.core.sql_model.base import SqlColumn, SqlConstraint, SqlObjectType

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _discover_model_classes() -> List[type]:
    """Return every class in the package that carries a ``to_dict``/``from_dict`` pair.

    Discovery is by introspection so a class added to the package cannot be
    forgotten here.
    """
    found: Dict[str, type] = {}
    for module_info in pkgutil.iter_modules(sql_model_package.__path__):
        module = importlib.import_module(f"{sql_model_package.__name__}.{module_info.name}")
        for obj in vars(module).values():
            if not inspect.isclass(obj) or obj.__module__ != module.__name__:
                continue
            if hasattr(obj, "to_dict") and hasattr(obj, "from_dict"):
                found[obj.__qualname__] = obj
    return sorted(found.values(), key=lambda cls: cls.__name__)


MODEL_CLASSES: List[type] = _discover_model_classes()
MODEL_CLASSES_BY_NAME: Dict[str, type] = {cls.__name__: cls for cls in MODEL_CLASSES}

#: The classes this harness covers, frozen by name.
#:
#: Discovery protects against a class being *added* and forgotten. It does not
#: protect against one *disappearing*: delete ``Index.from_dict`` and ``Index``
#: drops silently out of ``MODEL_CLASSES``, taking all of its rows with it and
#: leaving a green suite that proves nothing about indexes. This set closes
#: that direction — every change to it is deliberate and reviewable.
#:
#: Twenty classes carry a ``to_dict``/``from_dict`` pair (``procedure.py``
#: holds two of them).
EXPECTED_MODEL_CLASS_NAMES: FrozenSet[str] = frozenset(
    {
        "DatabaseLink",
        "Event",
        "Extension",
        "ForeignDataWrapper",
        "ForeignServer",
        "Index",
        "LinkedServer",
        "Module",
        "Package",
        "Parameter",
        "Partition",
        "Procedure",
        "Sequence",
        "SqlColumn",
        "SqlConstraint",
        "Synonym",
        "Table",
        "Trigger",
        "UserDefinedType",
        "View",
    }
)


# ---------------------------------------------------------------------------
# Allowlist and known gaps
# ---------------------------------------------------------------------------

#: class -> parameter -> why the value is not expected to survive a round trip.
#: An entry here says "by design"; anything else that fails is a defect. It is
#: empty: no parameter measured so far is dropped on purpose. ``dialect`` was
#: the candidate — ``Table.from_dict`` re-injects the table's dialect into the
#: columns and constraints it rebuilds rather than reading a per-child key —
#: but the value that arrives is the same one that left, so the row is green
#: and needs no entry.
INTENTIONALLY_NOT_SERIALIZED: Dict[type, Dict[str, str]] = {}

#: class -> parameter -> the loss observed on the sentinel-coverage check.
KNOWN_COVERAGE_GAPS: Dict[type, Dict[str, str]] = {
    Index: {
        "definition": "Index.to_dict emits no 'definition' key, so the preserved vendor DDL "
        "never reaches the serialized form.",
    },
    Parameter: {
        "volatility": "Parameter.__init__ accepts 'volatility' and assigns it to no attribute, "
        "so to_dict has nothing to emit; the value is discarded at construction.",
    },
}

#: class -> parameter -> the loss observed on the round-trip check.
KNOWN_ROUND_TRIP_GAPS: Dict[type, Dict[str, str]] = {
    Index: {
        "definition": "Index.definition: '<Index.definition>' -> None. to_dict emits no "
        "'definition' key and from_dict reads none.",
    },
    Parameter: {
        "volatility": "Parameter.__init__ accepts 'volatility' and stores it on no attribute; "
        "the value is discarded at construction, before serialization is reached.",
        "security_definer": "Parameter.__init__ accepts 'security_definer' and stores it on no "
        "attribute; the value is discarded at construction, before serialization is reached.",
    },
    SqlColumn: {
        "constraints": "SqlColumn.constraints: [SqlConstraint] -> []. to_dict emits no "
        "'constraints' key and from_dict passes none to the constructor.",
    },
    Table: {
        "columns": "Table.columns[0].constraints: [SqlConstraint] -> []. Table.to_dict now "
        "delegates to SqlColumn.to_dict, so the two flags it used to drop survive; what is "
        "left is SqlColumn's own gap above, which no change to Table can close.",
    },
}

#: parameter name -> value. Three parameters are normalised or fall back on
#: load, so a sentinel in them is silently replaced and the row would go red
#: for a reason that is not fidelity. They get a valid, non-default value
#: instead: an unknown ``object_type`` becomes ``TABLE``, an unknown
#: ``constraint_type`` becomes ``UNKNOWN``, and ``dialect`` is lowercased.
VALID_NON_DEFAULT: Dict[str, Any] = {
    "object_type": SqlObjectType.VIEW,
    "constraint_type": ConstraintType.UNIQUE,
    "dialect": "postgresql",
}

#: (class, parameter) -> attribute name(s) the parameter feeds, where the
#: constructor renames it. Every other parameter is read off the attribute of
#: the same name, and a parameter that reaches neither is a finding.
ATTRIBUTE_ALIASES: Dict[Tuple[type, str], Tuple[str, ...]] = {
    (SqlColumn, "is_nullable"): ("nullable",),
    (SqlConstraint, "column_names"): ("column_names", "columns"),
}

#: How deep the builder nests model objects inside one another before it stops
#: populating model-valued parameters. Two is enough to reach a constraint
#: inside a column inside a table, and it terminates ``Partition.subpartitions``.
MAX_NESTING_DEPTH = 2


# ---------------------------------------------------------------------------
# Instance builder
# ---------------------------------------------------------------------------


class Built(NamedTuple):
    """An instance plus the sentinels that were planted in it."""

    instance: Any
    sentinels: Dict[str, str]


def _type_hints(cls: type) -> Dict[str, Any]:
    """Resolve ``__init__`` annotations, including the TYPE_CHECKING-only ones."""
    module_globals = vars(sys.modules[cls.__module__])
    namespace = {**module_globals, **MODEL_CLASSES_BY_NAME}
    return typing.get_type_hints(cls.__init__, globalns=namespace)


def _constructor_parameters(cls: type) -> List[str]:
    """Return the named constructor parameters of *cls*, in declaration order.

    ``*args`` / ``**kwargs`` are excluded: they name no field, and the values
    they collect (``Partition.metadata``) are not addressable per parameter.
    """
    signature = inspect.signature(cls.__init__)
    return [
        name
        for name, parameter in signature.parameters.items()
        if name != "self"
        and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]


def _unwrap_optional(annotation: Any) -> Any:
    """Return ``T`` for ``Optional[T]``, and the annotation itself otherwise."""
    if typing.get_origin(annotation) is typing.Union:
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _model_class(annotation: Any) -> Optional[type]:
    """Return the model class *annotation* refers to, if it is one."""
    if inspect.isclass(annotation) and annotation in MODEL_CLASSES:
        return annotation
    return None


def _build_value(
    cls: type,
    name: str,
    annotation: Any,
    default: Any,
    ordinal: int,
    depth: int,
) -> Tuple[Any, Optional[str]]:
    """Return the value to pass for one parameter, and its sentinel if it has one.

    ``None`` for the value means "leave the parameter out" — used for nested
    model objects once the nesting limit is reached.
    """
    if name in VALID_NON_DEFAULT:
        return VALID_NON_DEFAULT[name], None

    sentinel = f"<{cls.__name__}.{name}>"
    annotation = _unwrap_optional(annotation)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if annotation is str:
        return sentinel, sentinel
    if annotation is bool:
        return default is not True, None
    if annotation is int:
        return 4200 + ordinal, None

    if origin in (list, typing.List):
        item = _unwrap_optional(args[0]) if args else str
        nested = _model_class(item)
        if nested is not None:
            if depth >= MAX_NESTING_DEPTH:
                return None, None
            return [_build(nested, depth + 1).instance], None
        if item is bool:
            return [True], None
        if item is int:
            return [4200 + ordinal], None
        if typing.get_origin(item) in (dict, typing.Dict):
            return [{sentinel: sentinel}], sentinel
        return [sentinel], sentinel

    if origin in (dict, typing.Dict):
        value_type = _unwrap_optional(args[1]) if len(args) == 2 else str
        if value_type is bool:
            return {sentinel: True}, sentinel
        return {sentinel: sentinel}, sentinel

    nested = _model_class(annotation)
    if nested is not None:
        if depth >= MAX_NESTING_DEPTH:
            return None, None
        return _build(nested, depth + 1).instance, None

    raise AssertionError(
        f"{cls.__name__}.{name}: the builder has no value for annotation {annotation!r}. "
        "Teach it one rather than skipping the parameter."
    )


def _build(cls: type, depth: int = 0) -> Built:
    """Instantiate *cls* with a distinctive, valid non-default value everywhere."""
    hints = _type_hints(cls)
    signature = inspect.signature(cls.__init__)
    kwargs: Dict[str, Any] = {}
    sentinels: Dict[str, str] = {}
    for ordinal, name in enumerate(_constructor_parameters(cls)):
        annotation = hints.get(name, str)
        default = signature.parameters[name].default
        value, sentinel = _build_value(cls, name, annotation, default, ordinal, depth)
        if value is None:
            continue
        kwargs[name] = value
        if sentinel is not None:
            sentinels[name] = sentinel
    return Built(cls(**kwargs), sentinels)


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def _attribute_names(cls: type, param: str) -> Tuple[str, ...]:
    """Return the attribute name(s) *param* feeds on *cls*."""
    return ATTRIBUTE_ALIASES.get((cls, param), (param,))


def _leaf_strings(value: Any) -> Iterator[str]:
    """Yield every string reachable in *value*, dict keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, enum.Enum):
        yield str(value.value)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _leaf_strings(key)
            yield from _leaf_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _leaf_strings(item)


def _differences(expected: Any, actual: Any, path: str) -> List[str]:
    """Compare field-by-field, descending into model objects and containers.

    Model classes define a deliberately partial ``__eq__`` (``SqlColumn``
    compares name, type and collation only), so ``==`` on a nested object would
    report a faithful copy where fields were dropped.
    """
    if type(expected) in MODEL_CLASSES:
        if type(actual) is not type(expected):
            return [f"{path}: {type(expected).__name__} -> {type(actual).__name__}"]
        nested_cls = type(expected)
        allowed = INTENTIONALLY_NOT_SERIALIZED.get(nested_cls, {})
        found: List[str] = []
        for param in _constructor_parameters(nested_cls):
            if param in allowed:
                continue
            for attr in _attribute_names(nested_cls, param):
                if not hasattr(expected, attr):
                    continue
                found += _differences(
                    getattr(expected, attr), getattr(actual, attr, None), f"{path}.{attr}"
                )
        return found

    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(expected) != len(actual):
            return [f"{path}: {expected!r} -> {actual!r}"]
        found = []
        for index, item in enumerate(expected):
            found += _differences(item, actual[index], f"{path}[{index}]")
        return found

    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            return [f"{path}: {expected!r} -> {actual!r}"]
        found = []
        for key, item in expected.items():
            found += _differences(item, actual[key], f"{path}[{key!r}]")
        return found

    if expected != actual:
        return [f"{path}: {expected!r} -> {actual!r}"]
    return []


# ---------------------------------------------------------------------------
# Guards — run at import, before any row is built
# ---------------------------------------------------------------------------


def _check_no_model_class_vanished() -> None:
    """Fail the module if the discovered class set drifted from the frozen one."""
    discovered = {cls.__name__ for cls in MODEL_CLASSES}
    missing = sorted(EXPECTED_MODEL_CLASS_NAMES - discovered)
    unexpected = sorted(discovered - EXPECTED_MODEL_CLASS_NAMES)
    if missing:
        raise AssertionError(
            f"{missing} no longer carries a to_dict/from_dict pair, so the harness silently "
            "stopped covering it. Restore the pair, or drop the name from "
            "EXPECTED_MODEL_CLASS_NAMES in the same change that removes the serializer."
        )
    if unexpected:
        raise AssertionError(
            f"{unexpected} is newly serializable and uncovered. Add it to "
            "EXPECTED_MODEL_CLASS_NAMES once its rows are green or carry a reasoned xfail."
        )


def _check_gap_tables_name_live_parameters() -> None:
    """Fail the module if an allowlist or gap entry outlived what it described."""
    tables = {
        "INTENTIONALLY_NOT_SERIALIZED": INTENTIONALLY_NOT_SERIALIZED,
        "KNOWN_COVERAGE_GAPS": KNOWN_COVERAGE_GAPS,
        "KNOWN_ROUND_TRIP_GAPS": KNOWN_ROUND_TRIP_GAPS,
    }
    stale: List[str] = []
    for table_name, table in tables.items():
        for cls, params in table.items():
            if cls not in MODEL_CLASSES:
                stale.append(f"{table_name}[{cls.__name__}]: class is not under test")
                continue
            live = set(_constructor_parameters(cls))
            stale += [
                f"{table_name}[{cls.__name__}][{param!r}]: not a constructor parameter"
                for param in params
                if param not in live
            ]
    if stale:
        raise AssertionError(
            "Stale entries — an xfail or allowlist entry naming a parameter that no longer "
            "exists suppresses nothing and misleads the next reader: " + "; ".join(sorted(stale))
        )


_check_no_model_class_vanished()
_check_gap_tables_name_live_parameters()


# ---------------------------------------------------------------------------
# Parametrisation
# ---------------------------------------------------------------------------


def _rows(gaps: Dict[type, Dict[str, str]], sentinel_only: bool) -> List[Any]:
    """Build the (class, parameter) rows, xfail-marking the ones known red."""
    rows: List[Any] = []
    for cls in MODEL_CLASSES:
        allowed = INTENTIONALLY_NOT_SERIALIZED.get(cls, {})
        try:
            sentinels = _build(cls).sentinels
        except Exception:
            # Collection must not die on an unbuildable class; the failure is
            # reported by test_builder_instantiates_every_model_class instead.
            sentinels = {}
        for param in _constructor_parameters(cls):
            if param in allowed:
                continue
            if sentinel_only and param not in sentinels:
                continue
            marks = []
            reason = gaps.get(cls, {}).get(param)
            if reason is not None:
                marks.append(pytest.mark.xfail(strict=True, reason=reason))
            rows.append(pytest.param(cls, param, marks=marks, id=f"{cls.__name__}.{param}"))
    return rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_cls", MODEL_CLASSES, ids=lambda cls: cls.__name__)
def test_builder_instantiates_every_model_class(model_cls: type) -> None:
    """Every discovered class can be built with a non-default value everywhere.

    A class that cannot be is a finding, not a row to skip.
    """
    built = _build(model_cls)
    assert isinstance(built.instance, model_cls)


@pytest.mark.parametrize(("model_cls", "param"), _rows(KNOWN_COVERAGE_GAPS, sentinel_only=True))
def test_to_dict_covers_constructor_parameter(model_cls: type, param: str) -> None:
    """``to_dict()`` emits the value the constructor was given for *param*."""
    built = _build(model_cls)
    sentinel = built.sentinels[param]
    # Case-insensitively: three constructors uppercase the value on the way in,
    # and exactly these three rows go red without the folding (measured by
    # running this check case-sensitively) — ``Parameter.direction``,
    # ``Partition.partition_method`` and ``UserDefinedType.type_category``.
    # Case folding is not field loss; the round-trip check compares the stored
    # values as they are.
    leaves = {leaf.lower() for leaf in _leaf_strings(built.instance.to_dict())}
    assert any(sentinel.lower() in leaf for leaf in leaves), (
        f"{model_cls.__name__}.to_dict() does not emit {param!r} "
        f"(sentinel {sentinel!r} absent from the serialized form)."
    )


@pytest.mark.parametrize(("model_cls", "param"), _rows(KNOWN_ROUND_TRIP_GAPS, sentinel_only=False))
def test_round_trip_preserves_constructor_parameter(model_cls: type, param: str) -> None:
    """``from_dict(to_dict())`` carries *param* through unchanged."""
    instance = _build(model_cls).instance
    reachable = [attr for attr in _attribute_names(model_cls, param) if hasattr(instance, attr)]
    assert reachable, (
        f"{model_cls.__name__}.__init__ takes {param!r} and stores it on no attribute, so "
        "the value is discarded at construction. Add an ATTRIBUTE_ALIASES entry if the "
        "constructor renames it; otherwise the parameter is dead."
    )
    restored = model_cls.from_dict(instance.to_dict())  # type: ignore[attr-defined]
    differences: List[str] = []
    for attr in reachable:
        differences += _differences(
            getattr(instance, attr), getattr(restored, attr, None), f"{model_cls.__name__}.{attr}"
        )
    assert not differences, "; ".join(differences)


# ---------------------------------------------------------------------------
# File-format compatibility
# ---------------------------------------------------------------------------

#: A table dict exactly as ``Table.to_dict`` produced it before the constraint
#: serializer landed, captured by running it on OSS ``eab4b59`` against a table
#: carrying one column and one foreign key, then mapping the raw
#: ``ConstraintType`` enum to its ``.value`` the way the JSON writers do — so
#: this literal is the shape every model file already on disk carries, not an
#: invented one. Eight constraint keys; no ``is_primary_key`` / ``is_unique``
#: on the column.
PRE_FIDELITY_TABLE_DICT: Dict[str, Any] = {
    "name": "orders",
    "schema": "public",
    "object_type": "TABLE",
    "dialect": "postgresql",
    "columns": [
        {
            "name": "id",
            "data_type": "integer",
            "nullable": False,
            "default_value": None,
            "is_identity": False,
            "identity_generation": None,
            "identity_seed": None,
            "identity_increment": None,
            "is_computed": False,
            "computed_expression": None,
            "computed_stored": False,
            "comment": None,
            "ordinal_position": None,
            "collation": None,
            "explicit_properties": {},
        }
    ],
    "constraints": [
        {
            "name": "orders_customer_fk",
            "constraint_type": "FOREIGN KEY",
            "columns": ["customer_id"],
            "reference_table": "customers",
            "reference_schema": "public",
            "reference_columns": ["id"],
            "check_expression": None,
            "explicit_properties": {},
        }
    ],
    "temporary": False,
    "tablespace": None,
    "comment": None,
    "partition_method": None,
    "partition_columns": None,
    "partitions": [],
    "export_partitions": [],
    "derived_from": None,
    "raw_ddl": None,
    "metadata": {},
    "dialect_options": {},
    "explicit_properties": {},
}


def test_a_model_file_in_the_pre_fidelity_shape_still_loads() -> None:
    """Every model file already on disk carries the dict above; it must keep loading.

    The seven constraint attributes the old shape never wrote read as ``None``,
    and the two column flags it never wrote read as ``False`` — a missing new
    key is a default, never a load error.
    """
    table = Table.from_dict(PRE_FIDELITY_TABLE_DICT)

    (fk,) = table.constraints
    assert fk.constraint_type is ConstraintType.FOREIGN_KEY
    assert fk.name == "orders_customer_fk"
    assert fk.column_names == ["customer_id"]
    assert fk.reference_table == "customers"
    assert fk.reference_schema == "public"
    assert fk.reference_columns == ["id"]
    assert fk.dialect == "postgresql"
    assert fk.on_delete is None
    assert fk.on_update is None
    assert fk.is_enabled is None
    assert fk.is_validated is None
    assert fk.is_deferrable is None
    assert fk.initially_deferred is None
    assert fk.comment is None

    (column,) = table.columns
    assert column.name == "id"
    assert column.nullable is False
    assert column.is_primary_key is False
    assert column.is_unique is False
    # This column dict carries no dialect key at all, so the table's is used —
    # as it was before the serializers were delegated.
    assert column.dialect == "postgresql"


def test_to_dict_keeps_every_pre_fidelity_key_and_is_json_serializable() -> None:
    """The emitted dict stays a superset of the old one, and dumps on its own.

    Two claims, and the second is the one nothing else pins. The harness maps
    an ``Enum`` to its ``.value`` when it flattens a dict, so it is blind to
    ``constraint_type`` being emitted as the raw enum — which is what
    ``Table.to_dict`` did, leaving the dict un-``json.dumps``-able until some
    later writer converted it. Emitting the value makes the dict serializable
    where it is produced, and matches what every file on disk already carries.
    """
    table = Table.from_dict(PRE_FIDELITY_TABLE_DICT)
    emitted = table.to_dict()

    json.dumps(emitted)

    assert set(emitted) == set(PRE_FIDELITY_TABLE_DICT)
    (legacy_constraint,) = PRE_FIDELITY_TABLE_DICT["constraints"]
    (emitted_constraint,) = emitted["constraints"]
    assert set(emitted_constraint) >= set(legacy_constraint)
    assert emitted_constraint["constraint_type"] == "FOREIGN KEY"
    for key, value in legacy_constraint.items():
        assert emitted_constraint[key] == value, key

    (legacy_column,) = PRE_FIDELITY_TABLE_DICT["columns"]
    (emitted_column,) = emitted["columns"]
    assert set(emitted_column) >= set(legacy_column)


def test_a_child_that_carries_its_own_dialect_keeps_it_through_a_round_trip() -> None:
    """The table's dialect is a fallback for its children, never an override.

    ``Table.from_dict`` passes its own dialect down because a child dict
    written by an earlier version carries none — but ``dialect`` is a field
    this serializer now emits, so a child dict that *does* carry one must keep
    it, or the field fails the round trip it was just added to. Nothing else
    would notice: a child of the table's own dialect is overwritten with the
    value it already had.
    """
    table = Table(
        name="orders",
        schema="public",
        dialect="postgresql",
        columns=[SqlColumn(name="id", data_type="integer", dialect="mysql")],
        constraints=[
            SqlConstraint(
                constraint_type=ConstraintType.UNIQUE,
                name="orders_id_key",
                column_names=["id"],
                dialect="mysql",
            )
        ],
    )
    assert table.columns[0].dialect == "mysql", "Table.__init__ backfills only a falsy dialect"

    restored = Table.from_dict(table.to_dict())

    assert restored.dialect == "postgresql"
    assert restored.columns[0].dialect == "mysql"
    assert restored.constraints[0].dialect == "mysql"
