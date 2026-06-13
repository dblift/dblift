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
├── api-reference/             # API documentation (auto-generated from docstrings)
│   ├── api.md
│   ├── cli.md
│   ├── core.md
│   └── db.md
├── architecture/              # Technical architecture docs
│   ├── overview.md
│   ├── migration-engine.md
│   ├── database-providers.md
│   ├── sql-parsing.md
│   ├── configuration.md
│   └── licensing.md
├── development/               # Developer guides
│   ├── setup.md
│   ├── testing.md
│   ├── contributing.md
│   └── adding-database-support.md
└── examples/                  # Code examples
    ├── basic-migrations.md
    └── advanced-scenarios.md
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

## Deployment

Documentation is automatically deployed to GitHub Pages when:
- Changes are pushed to `main` branch
- Files in `docs/` or `*.md` are modified
- `mkdocs.yml` is updated

See `.github/workflows/docs.yml` for deployment configuration.

## Contributing

When adding or updating documentation:

1. **User Guide**: Update when adding user-facing features
2. **Architecture**: Update when changing system design (including `licensing.md` for license changes)
3. **API Reference**: Improve docstrings in code (auto-generated)
4. **Examples**: Add examples for new features or patterns
5. **Development**: Update when changing development workflow

## Resources

- [MkDocs Documentation](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [mkdocstrings](https://mkdocstrings.github.io/)
- [Google Python Style Guide - Docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
