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
│   ├── best-practices.md
│   └── troubleshooting.md
├── api-reference/              # API documentation (auto-generated from docstrings)
│   ├── api.md
│   ├── events.md
│   ├── cli.md
│   ├── core.md
│   └── db.md
├── architecture/               # Architecture docs
│   ├── overview.md
│   ├── migration-engine.md
│   ├── database-providers.md
│   ├── sql-parsing.md
│   └── configuration.md
├── operations/recovery/        # Recovery runbooks
├── examples/                   # Code examples
│   ├── basic-migrations.md
│   └── advanced-scenarios.md
└── fr/                         # French translations
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

```bash
mkdocs build
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

## Deployment

Documentation is automatically deployed to GitHub Pages on push to `main`.
See `.github/workflows/docs.yml` for the deployment configuration.

## Resources

- [MkDocs Documentation](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [mkdocstrings](https://mkdocstrings.github.io/)
