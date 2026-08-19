"""Naming-boundary guard for the dialect-quirks surface.

``db/base_quirks.py``, ``core/dialect_boundary.py`` and every
``db/plugins/*/quirks.py`` are the public description of what a database
plugin may override. Their prose is read by people who only have *this*
repository, so it may only name things that exist here.

Two ways that breaks, both of which this module ratchets:

1. **A symbol that does not exist in this repository.** A docstring,
   comment or string literal that points at a class, method or module
   living somewhere else is unfollowable — the reader greps, finds
   nothing, and cannot tell whether the reference is stale or whether
   they are missing code. The check is structural: every code reference
   (a reST literal, a ``:class:``/``:meth:`` role, or a dotted module
   path in a string literal) must resolve to a name this repository
   actually defines. Nothing is hardcoded, so the guard cannot itself
   become a list of the names it is meant to keep out.

2. **A command that is not part of this edition.** ``core/premium_manifest``
   is the single declared place where this repository names those
   commands (see its module docstring); everywhere else must describe
   the mechanism instead of the caller. The command list is read from
   ``PREMIUM_COMMANDS`` so the guard tracks the catalog rather than a
   copy of it.

Matching for (2) is deliberately narrow: a command name is only a
*command* reference when it is written as one. Multi-word names
(``export-schema``) are unambiguous in any form, hyphen or underscore.
Single-word names are ordinary English — ``snapshot`` appears ~19 times
in these files meaning "a snapshot table" — so those are matched only in
an invocation context (``dblift <name>``, ``<name> command``, or a
backticked literal that is exactly the name). Widening this to bare word
matches would bury the signal under prose that is not a leak.
"""

from __future__ import annotations

import ast
import builtins
import functools
import re
import tokenize
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pytest

from core.premium_manifest import PREMIUM_COMMANDS

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The file this repository declares as the only place edition-gated
#: command names may appear. Excluded from check (2) by construction.
MANIFEST_FILE = REPO_ROOT / "core" / "premium_manifest.py"

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "node_modules",
    "venv",
    ".venv",
    "MagicMock",
}

# ---------------------------------------------------------------------------
# Pre-existing violations of check (2), frozen at their current counts.
#
# ``validate-sql`` is named in comments and in ``lint_placeholder_url``
# values across nine plugin quirks files. That predates this guard and is
# part of a wider situation in the config layer (``config/dblift_config.py``
# consumes ``lint_placeholder_url``), so it is out of scope here and is NOT
# fixed by this module.
#
# The map is per-file *counts*, not line numbers: line-level entries churn
# on every unrelated edit above them, file-level entries would let a file
# quietly accumulate new mentions. A count changes only when a mention is
# added or removed, which is exactly the event worth failing on. Numbers may
# only go down, and lowering one is part of the commit that removes the site.
# ---------------------------------------------------------------------------
FROZEN_COMMAND_NAME_SITES: Dict[str, int] = {
    "db/plugins/cosmosdb/quirks.py": 1,
    "db/plugins/db2/quirks.py": 2,
    "db/plugins/duckdb/quirks.py": 1,
    "db/plugins/mongodb/quirks.py": 1,
    "db/plugins/mysql/quirks.py": 2,
    "db/plugins/oracle/quirks.py": 1,
    "db/plugins/postgresql/quirks.py": 2,
    "db/plugins/sqlite/quirks.py": 1,
    "db/plugins/sqlserver/quirks.py": 2,
}


def guarded_files() -> List[Path]:
    """The quirks surface: the contract, its base class, every plugin."""
    files = [
        REPO_ROOT / "db" / "base_quirks.py",
        REPO_ROOT / "core" / "dialect_boundary.py",
    ]
    files.extend(sorted((REPO_ROOT / "db" / "plugins").glob("*/quirks.py")))
    return files


def _python_files() -> Iterable[Path]:
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.parts):
            continue
        yield path


@functools.lru_cache(maxsize=1)
def repo_names() -> frozenset:
    """Every name this repository defines, plus its module/package names.

    Definitions, assignment targets, imported aliases and parameter names —
    the question the guard asks is "does this identifier exist here at all",
    so the index is deliberately generous. A reference that misses this set
    misses by a wide margin.
    """
    names: Set[str] = set()
    for path in _python_files():
        rel = path.relative_to(REPO_ROOT)
        names.add(path.stem)
        names.update(rel.parts[:-1])
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
                names.add(node.attr)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.alias):
                names.update((node.asname or node.name).split("."))
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.update(node.module.split("."))
    names.update(dir(builtins))
    return frozenset(names)


@functools.lru_cache(maxsize=1)
def top_level_packages() -> frozenset:
    return frozenset(
        entry.name
        for entry in REPO_ROOT.iterdir()
        if entry.is_dir() and (entry / "__init__.py").exists() and entry.name not in SKIP_DIRS
    )


IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
CAMEL_CASE = re.compile(r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+\Z")
SNAKE_CASE = re.compile(r"[a-z_][a-z0-9_]*\Z")

#: A dotted path only reads as a *module* path at three segments or more.
#: ``db.drop_collection`` and ``db.createView`` in the MongoDB quirks are
#: driver calls on a database handle that collide with this repository's
#: ``db`` package; three segments cannot collide that way.
MODULE_PATH_MIN_SEGMENTS = 3

#: reST code references: ``literal``, `literal`, and :class:`Target` roles.
CODE_REF = re.compile(
    r":(?:class|meth|func|attr|mod|obj|data|exc):`~?([^`]+)`" r"|``([^`\s]+)``" r"|`([^`\s]+)`"
)

#: A dotted path inside a plain string literal, e.g. a logger name.
DOTTED_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")


def _prose_tokens(path: Path) -> List[Tuple[int, int, str]]:
    """``(line, token_type, text)`` for every comment and string literal."""
    out: List[Tuple[int, int, str]] = []
    with open(path, "rb") as handle:
        for tok in tokenize.tokenize(handle.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                out.append((tok.start[0], tok.type, tok.string))
    return out


def _is_module_path(ref: str) -> bool:
    """Whether ``ref`` reads as a dotted module path of this repository."""
    segments = ref.split(".")
    return (
        len(segments) >= MODULE_PATH_MIN_SEGMENTS
        and segments[0] in top_level_packages()
        and all(SNAKE_CASE.match(seg) for seg in segments)
    )


def _missing_segments(ref: str) -> List[str]:
    """Identifier segments of ``ref`` that this repository does not define."""
    segments = [seg for seg in ref.split(".") if IDENT.match(seg)]
    if not segments:
        return []
    known = repo_names()
    head = ref.split(".")[0]

    if _is_module_path(ref):
        # Module path: consume as much as the filesystem provides, then the
        # rest must be names defined somewhere in the repository.
        current = REPO_ROOT
        remaining = list(segments)
        while remaining:
            candidate = current / remaining[0]
            if candidate.is_dir() or candidate.with_suffix(".py").is_file():
                current = candidate
                remaining.pop(0)
                continue
            break
        return [seg for seg in remaining if seg not in known]

    return [seg for seg in segments if seg not in known]


def _is_checkable(ref: str) -> bool:
    """Whether ``ref`` is a code reference rather than SQL or prose.

    Bare single tokens are skipped unless they are class-shaped or
    private: ``dbo``, ``public``, ``FALSE`` and ``information_schema``
    are all legitimately backticked in these files and none of them is a
    Python symbol. Dotted references are checked only when they read as a
    module path of this repository or hang off a class-shaped name, which
    keeps SQL catalog paths (``USER_TABLES.TABLE_NAME``, ``syscat.tables``)
    out.
    """
    head = ref.split(".")[0]
    if "." in ref:
        return _is_module_path(ref) or bool(CAMEL_CASE.match(head))
    return bool(CAMEL_CASE.match(ref)) or (ref.startswith("_") and IDENT.match(ref) is not None)


def absent_symbol_findings(path: Path) -> List[str]:
    findings: List[str] = []
    rel = path.relative_to(REPO_ROOT)
    for start_line, tok_type, text in _prose_tokens(path):
        for match in CODE_REF.finditer(text):
            ref = (match.group(1) or match.group(2) or match.group(3)).strip()
            ref = ref.rstrip("()").strip(".,:;")
            if not ref or not _is_checkable(ref):
                continue
            line = start_line + text.count("\n", 0, match.start())
            for missing in _missing_segments(ref):
                findings.append(f"{rel}:{line}: `{ref}` -> no `{missing}` in this repository")
        if tok_type == tokenize.STRING and "`" not in text:
            for match in DOTTED_PATH.finditer(text):
                dotted = match.group(0)
                if not _is_module_path(dotted):
                    continue
                line = start_line + text.count("\n", 0, match.start())
                for missing in _missing_segments(dotted):
                    findings.append(
                        f"{rel}:{line}: string '{dotted}' -> no `{missing}` in this repository"
                    )
    return findings


def _command_patterns() -> List[Tuple[str, re.Pattern]]:
    """One pattern per catalog command; see the module docstring for width."""
    patterns: List[Tuple[str, re.Pattern]] = []
    for command in PREMIUM_COMMANDS:
        name = command.name
        if "-" in name:
            body = "[-_]".join(re.escape(part) for part in name.split("-"))
            patterns.append((name, re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.I)))
        else:
            escaped = re.escape(name)
            # ``dblift <name>`` is matched case-sensitively: the CLI is
            # spelled lowercase, while "DBLift snapshot table" in prose is
            # the product name in front of an ordinary noun, not a command.
            patterns.append(
                (
                    name,
                    re.compile(
                        rf"(?<![A-Za-z0-9_])(?:dblift\s+{escaped}(?![A-Za-z0-9_])"
                        rf"|{escaped}\s+command(?![A-Za-z0-9_])"
                        rf"|`{escaped}`|``{escaped}``)"
                    ),
                )
            )
    return patterns


def command_name_findings(path: Path) -> List[str]:
    findings: List[str] = []
    rel = path.relative_to(REPO_ROOT)
    for start_line, _tok_type, text in _prose_tokens(path):
        for name, pattern in _command_patterns():
            for match in pattern.finditer(text):
                line = start_line + text.count("\n", 0, match.start())
                findings.append(f"{rel}:{line}: names the '{name}' command as '{match.group(0)}'")
    return findings


@pytest.mark.unit
class TestQuirksNamingBoundary:
    def test_guarded_file_set_is_the_whole_quirks_surface(self) -> None:
        """The guard must not silently stop covering a plugin."""
        files = guarded_files()
        assert all(path.is_file() for path in files), files
        plugin_dirs = {p.parent.name for p in (REPO_ROOT / "db" / "plugins").glob("*/quirks.py")}
        covered = {p.parent.name for p in files if p.name == "quirks.py"}
        assert plugin_dirs == covered

    def test_no_reference_to_a_symbol_absent_from_this_repository(self) -> None:
        findings: List[str] = []
        for path in guarded_files():
            findings.extend(absent_symbol_findings(path))
        assert not findings, "Unresolvable code references:\n" + "\n".join(findings)

    def test_no_edition_gated_command_named_outside_the_manifest(self) -> None:
        allowed = dict(FROZEN_COMMAND_NAME_SITES)
        found: Dict[str, List[str]] = {}
        for path in guarded_files():
            findings = command_name_findings(path)
            if findings:
                found[str(path.relative_to(REPO_ROOT))] = findings

        unfrozen = [line for rel, lines in found.items() if rel not in allowed for line in lines]
        assert (
            not unfrozen
        ), "Edition-gated command named outside core/premium_manifest.py:\n" + "\n".join(unfrozen)

        stale = sorted(set(allowed) - set(found))
        assert not stale, f"Frozen allowlist entries with no remaining site (remove them): {stale}"

        drifted = {rel: len(lines) for rel, lines in found.items() if len(lines) != allowed[rel]}
        assert not drifted, (
            "Frozen allowlist counts changed — a new site is a leak, a removed one means "
            "lowering the number in the same commit:\n"
            + "\n".join(
                f"  {rel}: {count} site(s), frozen at {allowed[rel]}\n"
                + "\n".join(f"    {line}" for line in found[rel])
                for rel, count in sorted(drifted.items())
            )
        )

    def test_the_manifest_itself_is_exempt(self) -> None:
        """Sanity: the one file allowed to name them still does."""
        assert MANIFEST_FILE not in guarded_files()
        assert command_name_findings(MANIFEST_FILE)
