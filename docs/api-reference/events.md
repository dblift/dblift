# Events

The event system delivers typed [`Event`][api.events.Event] dataclass
instances to listener callbacks for IDE / tooling integration. Subscribe to
specific events via [`EventEmitter.on`][api.events.EventEmitter.on] (or
[`subscribe`][api.events.EventEmitter.subscribe]) and access fields by
attribute — `event.script`, `event.dialect`, `event.result`. Reserved
fields (`event_type`, `timestamp`) are populated by the emitter; every
other field defaults to `None` and is set only when the emit site provides
it.

## EventType

::: dblift.api.events.EventType
    options:
      show_root_heading: true
      show_source: false
      show_signature_annotations: true
      members: true

## Event

::: dblift.api.events.Event
    options:
      show_root_heading: true
      show_source: true
      show_signature_annotations: true
      separate_signature: true

## EventEmitter

::: dblift.api.events.EventEmitter
    options:
      show_root_heading: true
      show_source: false
      show_signature_annotations: true
      separate_signature: true
      members:
        - "on"
        - "off"
        - "subscribe"
        - "unsubscribe"
        - "emit"
        - "clear"
        - "get_history"
        - "clear_history"
        - "start_batch"
        - "stop_batch"
        - "flush_batch"

## See also

- [API Reference](api.md) — `DBLiftClient` public surface
- [Result Objects](api.md#result-objects) — typed result dataclasses returned by client operations
