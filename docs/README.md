# DBLift Documentation

This directory contains the source files for the DBLift documentation site.

## Structure

```
docs/
├── index.md                    # Homepage
├── user-guide/                 # User documentation
│   ├── getting-started.md
│   ├── configuration.md
│   ├── commands.md
│   ├── nosql-python-migrations.md
│   ├── best-practices.md
│   ├── ci-cd.md
│   ├── async.md
│   ├── django.md
│   ├── opentelemetry.md
│   └── troubleshooting.md
├── api-reference/              # API documentation (auto-generated from docstrings)
│   ├── api.md
│   ├── cli.md
│   ├── core.md
│   ├── db.md
│   └── events.md
├── developer-guide/             # Provider/plugin developer guides
│   ├── creating-a-provider.md
│   └── plugin-entry-points.md
├── operations/recovery/         # Failure-mode recovery runbooks
└── examples/                    # Code examples
    ├── basic-migrations.md
    ├── python-migrations.md
    ├── advanced-scenarios.md
    ├── sqlalchemy-integration.md
    ├── fastapi-lifespan.md
    ├── flask-integration.md
    └── django-external-db.md
```

## Building Documentation

### Prerequisites

Install documentation dependencies:

```bash
pip install -r requirements-docs.txt
```

### Local Development

Serve documentation locally for preview:

```bash
mkdocs serve
```

This starts a local server at `http://127.0.0.1:8000` that auto-reloads on file changes.

### Build Static Site

Build the documentation site:

```bash
mkdocs build
```

This creates a `site/` directory with the static HTML files.

### Build with Strict Mode

Build with strict mode to catch errors:

```bash
mkdocs build --strict
```

## Documentation Standards

### Markdown Format

- Use standard Markdown syntax
- Use MkDocs Material extensions (admonitions, code blocks, etc.)
- Follow consistent heading hierarchy

### Code Examples

Use syntax highlighting:

````markdown
```python
from api.client import DBLiftClient
client = DBLiftClient(...)
```
````

### Admonitions

Use admonitions for important notes:

````markdown
!!! tip "Tip"
    This is a helpful tip.

!!! warning "Warning"
    This is a warning.

!!! danger "Danger"
    This is a critical warning.
````

### Links

- Use relative links within documentation
- Link to other sections using `[text](../path/to/file.md)`
- External links should be absolute URLs

## API Documentation

API documentation is auto-generated from Python docstrings using `mkdocstrings`.

To improve API docs:
1. Add/improve docstrings in Python code
2. Use Google-style docstrings (recommended)
3. Include type hints for better documentation
4. Add examples in docstrings

## Validation

Documentation references are checked when:
- Pull requests change files in `docs/`
- Pull requests change top-level Markdown files
- The workflow is triggered manually

See `.github/workflows/docs.yml` for workflow configuration.

## Contributing

When adding or updating documentation:

1. **User Guide**: Update when adding user-facing features
2. **Developer Guide**: Update when changing provider/plugin extension points
3. **API Reference**: Improve docstrings in code (auto-generated)
4. **Examples**: Add examples for new features or patterns
5. **Operations**: Add a recovery runbook for new failure modes

## Resources

- [MkDocs Documentation](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [mkdocstrings](https://mkdocstrings.github.io/)
- [Google Python Style Guide - Docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
