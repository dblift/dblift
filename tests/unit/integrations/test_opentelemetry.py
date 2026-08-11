"""OTel span instrumentation driven off the dblift event bus."""

from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from sqlalchemy import create_engine

from api import DBLiftClient
from integrations.opentelemetry import instrument


@pytest.fixture()
def exporter() -> InMemorySpanExporter:
    provider = TracerProvider()
    exp = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    trace._TRACER_PROVIDER_SET_ONCE = trace.Once()
    trace._TRACER_PROVIDER = None
    trace.set_tracer_provider(provider)
    return exp


def _client(tmp_path: Path) -> DBLiftClient:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path/'db.sqlite'}")
    return DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))


def test_migrate_emits_parent_and_child_spans(tmp_path, exporter):
    client = _client(tmp_path)
    instrument(client)
    client.migrate()

    spans = {s.name for s in exporter.get_finished_spans()}
    assert "dblift.migrate" in spans
    assert "dblift.script" in spans


def test_uninstrument_stops_spans(tmp_path, exporter):
    client = _client(tmp_path)
    handle = instrument(client)
    handle.uninstrument()
    client.migrate()

    assert exporter.get_finished_spans() == ()


def test_child_span_has_script_attributes(tmp_path, exporter):
    client = _client(tmp_path)
    instrument(client)
    client.migrate()

    child = next(s for s in exporter.get_finished_spans() if s.name == "dblift.script")
    assert child.attributes.get("dblift.script") == "V1_0_0__t.sql"
    assert child.status.status_code.name == "OK"


def test_undo_produces_undo_spans(tmp_path, exporter):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    (migrations / "U1_0_0__t.sql").write_text("DROP TABLE t;")
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path/'db.sqlite'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    client.migrate()
    instrument(client)
    client.undo()

    names = {s.name for s in exporter.get_finished_spans()}
    assert "dblift.undo" in names
    assert "dblift.script" in names


def test_clean_produces_clean_span(tmp_path, exporter):
    client = _client(tmp_path)
    client.migrate()
    instrument(client)
    client.clean(clean_enabled=True)

    names = {s.name for s in exporter.get_finished_spans()}
    assert "dblift.clean" in names


def test_clean_soft_failure_marks_span_error(tmp_path, exporter):
    """Issue #848: clean() returning success=False without raising (here,
    clean disabled by config since clean_enabled isn't passed) must still
    mark the span ERROR, not OK."""
    client = _client(tmp_path)
    client.migrate()
    instrument(client)
    result = client.clean()

    assert result.success is False
    span = next(s for s in exporter.get_finished_spans() if s.name == "dblift.clean")
    assert span.status.status_code.name == "ERROR"


def test_baseline_produces_baseline_span(tmp_path, exporter):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path/'db.sqlite'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    instrument(client)
    client.baseline("1.0.0")

    names = {s.name for s in exporter.get_finished_spans()}
    assert "dblift.baseline" in names


def test_repair_produces_repair_span(tmp_path, exporter):
    client = _client(tmp_path)
    client.migrate()
    instrument(client)
    client.repair()

    names = {s.name for s in exporter.get_finished_spans()}
    assert "dblift.repair" in names


def test_callback_events_recorded_as_span_events_not_new_spans(tmp_path, exporter):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    (migrations / "beforeMigrate__setup.sql").write_text("SELECT 1;")

    engine = create_engine(f"sqlite:///{tmp_path/'db.sqlite'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    instrument(client)
    client.migrate()

    spans = exporter.get_finished_spans()
    names = {s.name for s in spans}
    # Callbacks must not get their own span.
    assert "callback.started" not in names

    migrate_span = next(s for s in spans if s.name == "dblift.migrate")
    event_names = [e.name for e in migrate_span.events]
    assert "callback.before_migrate" in event_names
    assert "callback.started" in event_names
    assert "callback.completed" in event_names
    started = next(e for e in migrate_span.events if e.name == "callback.started")
    assert started.attributes.get("dblift.name") == "beforeMigrate__setup.sql"


def test_clean_object_removed_recorded_on_clean_span(tmp_path, exporter):
    client = _client(tmp_path)
    client.migrate()
    instrument(client)
    client.clean(clean_enabled=True)

    clean_span = next(s for s in exporter.get_finished_spans() if s.name == "dblift.clean")
    removed = [e for e in clean_span.events if e.name == "clean.object.removed"]
    assert removed
    assert removed[0].attributes.get("dblift.type") == "table"
    assert removed[0].attributes.get("dblift.name")


def test_undo_rollback_marker_carries_script_name(tmp_path, exporter):
    """Regression: undo.script.rolled_back is emitted with a ``script`` field,
    not ``name`` — the marker attrs must read both so the span event carries
    the rolled-back script instead of being empty."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    (migrations / "U1_0_0__t.sql").write_text("DROP TABLE t;")

    engine = create_engine(f"sqlite:///{tmp_path/'db.sqlite'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    client.migrate()
    instrument(client)
    client.undo()

    undo_span = next(s for s in exporter.get_finished_spans() if s.name == "dblift.undo")
    rolled_back = [e for e in undo_span.events if e.name == "undo.script.rolled_back"]
    assert rolled_back
    assert rolled_back[0].attributes.get("dblift.script") == "U1_0_0__t.sql"
