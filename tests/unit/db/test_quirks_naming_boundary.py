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
*command* reference when it is written as one. A hyphenated catalog name
is unambiguous in any form, hyphen or underscore — no ordinary English
word carries an internal hyphen. Single-token names are ordinary English:
one of them occurs ~19 times in these files as a plain noun for a kind of
table, describing storage that has nothing to do with the command. Those
are therefore matched only in an invocation context (``dblift <name>``,
``<name> command``, or a backticked literal that is exactly the name).
Widening this to bare word matches would bury the signal under prose that
is not a leak.

This module names no catalog command itself, in prose or in data — that
is the rule it enforces, and a guard that had to spell out what it keeps
out would be the leak.

**What this guard does not see.** Its edge is worth knowing before you
read a green run as "the prose is clean":

* *Slash-style paths.* ``tests/integration/foo/bar.py`` is not a dotted
  reference and is never resolved, backticked or not. Three of the
  references this branch fixed were exactly that shape, found by reading
  rather than by the guard.
* *Spaced prose.* A hyphenated catalog name written as separate English
  words does not match; only the hyphen/underscore forms do.
* *Bare ``snake_case``.* A lone lower-case token is indistinguishable
  from ordinary prose, so only class-shaped and private names are
  resolved (see :func:`_is_checkable`).
* *Two-segment dotted names.* ``core.thing`` is below
  ``MODULE_PATH_MIN_SEGMENTS`` and is skipped, so a stale two-segment
  module path survives.

Identifier-shaped mentions of a hyphenated catalog command *are* caught
in prose (``<name>_hint`` matches, because the boundary look-around
rejects only alphanumerics); a real identifier in code is not scanned,
since :func:`_prose_tokens` reads only comments and string literals. On
Python 3.11 f-strings are caught too. Under PEP 701
(3.12+) f-string bodies arrive as ``FSTRING_MIDDLE`` rather than
``STRING``, which is why the token filter accepts both.
"""

from __future__ import annotations

import ast
import builtins
import functools
import hashlib
import re
import tokenize
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pytest

from dblift.core.premium_manifest import PREMIUM_COMMANDS

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The file this repository declares as the only place edition-gated
#: command names may appear. Excluded from check (2) by construction.
MANIFEST_FILE = REPO_ROOT / "dblift" / "core" / "premium_manifest.py"

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


def _command_key(name: str) -> str:
    """Opaque but stable identity for a catalog command.

    The frozen map has to record *which* command each count belongs to — a
    bare per-file total lets a departing mention of one command be replaced
    by a mention of another with the total, and the guard, unchanged. It
    cannot record it by name: not spelling a catalog command out is the rule
    this module enforces on the files it guards, and a guard that exempted
    itself would be the leak. A digest of the manifest name is stable across
    catalog reordering, distinct per command, and reveals nothing. Failure
    messages carry the real name, read from the manifest at run time, so a
    maintainer lowering a count is never left matching hex by hand.
    """
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Pre-existing violations of check (2), frozen at their current counts.
#
# One catalog command is named in comments and in ``lint_placeholder_url``
# values across nine plugin quirks files. That predates this guard and is
# part of a wider situation in the config layer (``config/dblift_config.py``
# consumes ``lint_placeholder_url``), so it is out of scope here and is NOT
# fixed by this module.
#
# The map is per-file, per-command *counts*, not line numbers: line-level
# entries churn on every unrelated edit above them, file-level entries would
# let a file quietly accumulate new mentions, and a file-level total would
# not notice one command being swapped for another. A count changes only
# when a mention is added or removed, which is exactly the event worth
# failing on. Numbers may only go down, and lowering one is part of the
# commit that removes the site. Inner keys come from ``_command_key``.
# ---------------------------------------------------------------------------
FROZEN_COMMAND_NAME_SITES: Dict[str, Dict[str, int]] = {
    "dblift/db/plugins/cosmosdb/quirks.py": {"3f18d50d7936": 1},
    "dblift/db/plugins/db2/quirks.py": {"3f18d50d7936": 2},
    "dblift/db/plugins/duckdb/quirks.py": {"3f18d50d7936": 1},
    "dblift/db/plugins/mongodb/quirks.py": {"3f18d50d7936": 1},
    "dblift/db/plugins/mysql/quirks.py": {"3f18d50d7936": 2},
    "dblift/db/plugins/oracle/quirks.py": {"3f18d50d7936": 1},
    "dblift/db/plugins/postgresql/quirks.py": {"3f18d50d7936": 2},
    "dblift/db/plugins/sqlite/quirks.py": {"3f18d50d7936": 1},
    "dblift/db/plugins/sqlserver/quirks.py": {"3f18d50d7936": 2},
}

#: Names this repository legitimately mentions but does not define, because
#: they belong to the standard library or a third-party package. Check (1)
#: resolves class-shaped tokens against a repository-only index, so without
#: this an ordinary external class name is reported as "no `X` in this
#: repository" — which reads as a bug in the guard rather than a problem in
#: the contributor's docstring, and is the fastest route to this file being
#: deleted. Every entry below is a name this repository already references;
#: the class-shaped check itself stays, because an absent in-repo class is
#: exactly that shape and is the case this guard exists for.
EXTERNAL_SYMBOLS: frozenset = frozenset(
    {
        # psycopg2.errors — ``db/plugins/postgresql/provider.py`` explains the
        # aborted-transaction cascade in terms of this error class.
        "InFailedSqlTransaction",
        # SQLAlchemy — the dialect-resolution path walked in
        # ``db/native_connection_manager.py``.
        "DialectKWArgs",
        "PluginLoader",
        # PEP 249 DBAPI exception, raised by ``sqlite3`` in
        # ``db/plugins/sqlite/provider.py``.
        "ProgrammingError",
    }
)


def guarded_files() -> List[Path]:
    """The quirks surface: the contract, its base class, every plugin."""
    files = [
        REPO_ROOT / "dblift" / "db" / "base_quirks.py",
        REPO_ROOT / "dblift" / "core" / "dialect_boundary.py",
    ]
    files.extend(sorted((REPO_ROOT / "dblift" / "db" / "plugins").glob("*/quirks.py")))
    return files


def _python_files() -> Iterable[Path]:
    # Filter the path *relative to the repository*: ``rglob`` yields absolute
    # paths, so testing ``path.parts`` also tests every ancestor the checkout
    # happens to live under. A worktree below a dot-directory — the
    # ``.worktrees/<name>`` layout this project already uses — would then
    # match on its own parent and index nothing at all.
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
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
    """Importable roots: the repository's top-level packages plus the
    subpackages of ``dblift``, so ``dblift.db.base_quirks.BaseQuirks`` in a
    docstring still reads as a module path."""
    return frozenset(
        entry.name
        for parent in (REPO_ROOT, REPO_ROOT / "dblift")
        for entry in parent.iterdir()
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


#: Token types carrying prose. ``FSTRING_MIDDLE`` exists only on Python 3.12+,
#: where PEP 701 stopped emitting f-strings as a single ``STRING`` token — on
#: 3.11 an f-string is a ``STRING`` and is already covered, so accepting both
#: keeps the same text visible on either interpreter rather than letting an
#: f-string become a hole on the newer one.
_STRING_LIKE_TOKENS: Tuple[int, ...] = tuple(
    tok_type
    for tok_type in (tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", None))
    if tok_type is not None
)
_PROSE_TOKENS: Tuple[int, ...] = (tokenize.COMMENT,) + _STRING_LIKE_TOKENS


def _prose_tokens(path: Path) -> List[Tuple[int, int, str]]:
    """``(line, token_type, text)`` for every comment and string literal."""
    out: List[Tuple[int, int, str]] = []
    with open(path, "rb") as handle:
        for tok in tokenize.tokenize(handle.readline):
            if tok.type in _PROSE_TOKENS:
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
    known = repo_names() | EXTERNAL_SYMBOLS

    if _is_module_path(ref):
        # Module path: consume as much as the filesystem provides, then the
        # rest must be names defined somewhere in the repository.
        current = REPO_ROOT
        if segments[0] != "dblift" and (REPO_ROOT / "dblift" / segments[0]).is_dir():
            current = REPO_ROOT / "dblift"
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
        if tok_type in _STRING_LIKE_TOKENS:
            # Skip only the spans the reST pass above already resolved, not
            # the whole literal. Testing the literal for a backtick anywhere
            # made a docstring's coverage depend on unrelated backticked text
            # elsewhere in the same string — one ``literal`` at the top hid
            # every bare dotted path below it.
            covered = [match.span() for match in CODE_REF.finditer(text)]
            for match in DOTTED_PATH.finditer(text):
                dotted = match.group(0)
                if not _is_module_path(dotted):
                    continue
                if any(start <= match.start() < end for start, end in covered):
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
            # spelled lowercase, while the capitalised product name in
            # front of an ordinary noun is prose, not a command.
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


def command_name_findings(path: Path) -> List[Tuple[str, str]]:
    """``(command name, formatted site)`` for every catalog command named."""
    findings: List[Tuple[str, str]] = []
    rel = path.relative_to(REPO_ROOT)
    for start_line, _tok_type, text in _prose_tokens(path):
        for name, pattern in _command_patterns():
            for match in pattern.finditer(text):
                line = start_line + text.count("\n", 0, match.start())
                findings.append(
                    (name, f"{rel}:{line}: names the '{name}' command as '{match.group(0)}'")
                )
    return findings


@pytest.mark.unit
class TestQuirksNamingBoundary:
    def test_the_repository_index_is_actually_populated(self) -> None:
        """Check (1) is only as good as the index it resolves against.

        Every judgement it makes is "is this name in ``repo_names()``", so an
        index that indexes nothing does not make the guard permissive — it
        makes it report every in-repo name as absent, which reads as a broken
        checkout rather than a broken guard. The failure this pins is a walk
        that filters the wrong path: ``rglob`` yields absolute paths, so any
        test of the *whole* path's parts also tests the directories the
        checkout happens to live under.
        """
        indexed = set(_python_files())
        assert len(indexed) >= 500, (
            f"only {len(indexed)} Python files indexed under {REPO_ROOT} — the "
            "file walk is excluding the repository itself"
        )
        missing_guarded = sorted(str(p) for p in guarded_files() if p not in indexed)
        assert not missing_guarded, f"guarded files absent from the index: {missing_guarded}"
        names = repo_names()
        absent = [n for n in ("BaseQuirks", "DialectQuirks", "ProviderRegistry") if n not in names]
        assert not absent, f"symbols this repository defines are missing from the index: {absent}"

    def test_guarded_file_set_is_the_whole_quirks_surface(self) -> None:
        """The guard must not silently stop covering a plugin."""
        files = guarded_files()
        assert all(path.is_file() for path in files), files
        plugin_dirs = {
            p.parent.name for p in (REPO_ROOT / "dblift" / "db" / "plugins").glob("*/quirks.py")
        }
        covered = {p.parent.name for p in files if p.name == "quirks.py"}
        assert plugin_dirs == covered

    def test_no_reference_to_a_symbol_absent_from_this_repository(self) -> None:
        findings: List[str] = []
        for path in guarded_files():
            findings.extend(absent_symbol_findings(path))
        assert not findings, (
            "Unresolvable code references in the quirks surface.\n"
            "These files are read by people who only have this repository, so a\n"
            "name they cite has to be findable here. Two ways to clear a finding:\n"
            "  - the name is not in this repository: describe the mechanism instead\n"
            "    of naming the symbol, or point at the nearest thing that IS here;\n"
            "  - the name belongs to a third-party or standard-library package: add\n"
            "    it to EXTERNAL_SYMBOLS in this file, with a comment naming the\n"
            "    package it comes from.\n\n" + "\n".join(findings)
        )

    def test_no_edition_gated_command_named_outside_the_manifest(self) -> None:
        allowed = FROZEN_COMMAND_NAME_SITES
        # {file: {command key: [site, ...]}} — keyed per command so that a
        # departing mention of one cannot be replaced by a mention of another
        # under an unchanged per-file total.
        found: Dict[str, Dict[str, List[str]]] = {}
        # Built from the manifest rather than from the sites actually found:
        # the stale branch below fires exactly when a command's last site is
        # gone, so a map populated from ``found`` has nothing to resolve with
        # and leaves the maintainer reading bare hex. ``.get(key, key)`` falls
        # back to the digest only for a key whose command left the catalog,
        # where no real name exists anywhere to print.
        names_by_key: Dict[str, str] = {_command_key(c.name): c.name for c in PREMIUM_COMMANDS}
        for path in guarded_files():
            rel = str(path.relative_to(REPO_ROOT))
            for name, line in command_name_findings(path):
                found.setdefault(rel, {}).setdefault(_command_key(name), []).append(line)

        unfrozen = [
            line
            for rel, by_key in found.items()
            for key, lines in by_key.items()
            if key not in allowed.get(rel, {})
            for line in lines
        ]
        assert (
            not unfrozen
        ), "Edition-gated command named outside core/premium_manifest.py:\n" + "\n".join(unfrozen)

        stale = sorted(
            f"{rel} ['{names_by_key.get(key, key)}' -> {key}]"
            for rel, by_key in allowed.items()
            for key in by_key
            if key not in found.get(rel, {})
        )
        assert not stale, f"Frozen allowlist entries with no remaining site (remove them): {stale}"

        drifted = {
            (rel, key): len(lines)
            for rel, by_key in found.items()
            for key, lines in by_key.items()
            if len(lines) != allowed[rel][key]
        }
        assert not drifted, (
            "Frozen allowlist counts changed — a new site is a leak, a removed one means "
            "lowering the number in the same commit:\n"
            + "\n".join(
                f"  {rel} ['{names_by_key.get(key, key)}' -> {key}]: {count} site(s), "
                f"frozen at {allowed[rel][key]}\n"
                + "\n".join(f"    {line}" for line in found[rel][key])
                for (rel, key), count in sorted(drifted.items())
            )
        )

    def test_the_manifest_itself_is_exempt(self) -> None:
        """Sanity: the one file allowed to name them still does."""
        assert MANIFEST_FILE not in guarded_files()
        assert command_name_findings(MANIFEST_FILE)
