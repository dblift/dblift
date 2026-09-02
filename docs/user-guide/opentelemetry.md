# OpenTelemetry tracing

dblift can emit OpenTelemetry **spans** for its operations, driven off the event
bus. Install the extra and bring your own OTel SDK + exporter:

```bash
pip install "dblift[otel]"
```

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
trace.set_tracer_provider(TracerProvider())   # configure your exporter here

from dblift.api import DBLiftClient
from dblift.integrations.opentelemetry import instrument

client = DBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations")
instrument(client)          # opt-in, per client
client.migrate()            # emits dblift.migrate + dblift.script spans
```

Spans attach to the current OTel context, so inside a traced web request the
dblift spans nest under the request span automatically.

Spans produced: `dblift.migrate` / `dblift.undo` / `dblift.clean` /
`dblift.baseline` / `dblift.repair` (with `dblift.script` children for migrate and
undo), `dblift.validate`, `dblift.info`. Failures set the span status to ERROR.

dblift depends only on `opentelemetry-api`; the host application owns the SDK and
exporter configuration. Metrics are not emitted (traces only).
