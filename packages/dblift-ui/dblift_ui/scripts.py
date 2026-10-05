"""The script files of a project: the only code that reads or writes them."""

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# V<version>__<description>, U<version>__<description> or R__<description>, as .sql or .py.
# ASCII only and anchored at the very end (``\Z``, not ``$``, which accepts a trailing
# newline): a script name never holds a separator, ``..`` or anything else.
SCRIPT_NAME = re.compile(
    r"^(?:(?P<prefix>[VU])(?P<version>[0-9]+(?:[._][0-9]+)*)|(?P<repeatable>R))"
    r"__(?P<description>[A-Za-z0-9_]+)\.(?P<extension>sql|py)\Z"
)
MAX_BYTES = 1_000_000
_SKIPPED_FOLDERS = frozenset({"__pycache__", ".git", "node_modules"})
_LANGUAGES = {"sql": "sql", "python": "py"}

_PYTHON_TEMPLATE = '''"""{title}"""

from dblift.api import MigrationContext


def migrate(context: MigrationContext) -> None:
    context.execute("SELECT 1")  # replace with the change
'''


class ScriptError(Exception):
    """A request about a script that cannot be honoured; the message is for the user."""


class ScriptNotFound(ScriptError):
    """No script of that name in the project's migration directories."""


@dataclass(frozen=True)
class Script:
    name: str
    kind: str
    version: str
    description: str
    language: str
    directory: str
    has_undo: bool


# A script file as found: the path it was listed under, and the real file it is.
_Found = Tuple[Path, Path]


def _parse(name: Any) -> "re.Match[str]":
    match = SCRIPT_NAME.match(name) if isinstance(name, str) else None
    if match is None:
        raise ScriptError("not a script name")
    return match


def _version_key(version: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in re.split(r"[._]", version))


def _template(language: str, heading: str) -> str:
    if language == "sql":
        return f"-- {heading}\n"
    # Inside the docstring every backslash is escaped and no double quote is left,
    # so the description can neither end the string nor form an escape sequence.
    return _PYTHON_TEMPLATE.format(title=heading.replace("\\", "\\\\").replace('"', "'"))


class ScriptStore:
    def __init__(self, config_path: str) -> None:
        config = Path(config_path).resolve()
        self.root = config.parent
        try:
            data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ScriptError(f"cannot read the project's config: {exc}") from exc
        if not isinstance(data, dict):
            raise ScriptError("the project's config is not a mapping")
        self.directories = self._directories(data.get("migrations"))

    def _directories(self, migrations: Any) -> List[Tuple[Path, bool]]:
        section: Dict[str, Any] = migrations if isinstance(migrations, dict) else {}
        default = bool(section.get("recursive", True))
        entries = section.get("directories") or [section.get("directory") or "migrations"]
        if isinstance(entries, (str, dict)):
            entries = [entries]
        if not isinstance(entries, list):
            raise ScriptError("the project's config has an unreadable migrations directory list")
        found = []
        for entry in entries:
            if isinstance(entry, dict):
                path = entry.get("path") or entry.get("directory")
                recursive = bool(entry.get("recursive", default))
            else:
                path, recursive = entry, default
            if not path:
                continue
            folder = Path(str(path)).expanduser()
            found.append(
                ((folder if folder.is_absolute() else self.root / folder).resolve(), recursive)
            )
        if not found:
            raise ScriptError("the project's config declares no migrations directory")
        return found

    def _files(self) -> Dict[str, List[_Found]]:
        """Every script file, by name. A name seen twice keeps both."""
        index: Dict[str, List[_Found]] = {}
        for folder, recursive in self.directories:
            # os.walk does not descend into linked folders and lists only what it can read.
            for current, folders, names in os.walk(folder):
                if recursive:
                    folders[:] = [
                        f for f in folders if f not in _SKIPPED_FOLDERS and not f.startswith(".")
                    ]
                else:
                    folders.clear()
                for name in sorted(names):
                    if not SCRIPT_NAME.match(name):
                        continue
                    path = Path(current) / name
                    real = self._confined(path, folder)
                    if real is not None:
                        index.setdefault(name, []).append((path, real))
        return index

    @staticmethod
    def _confined(path: Path, folder: Path) -> Optional[Path]:
        """The real file behind *path* when it is a script file under *folder*, else None.

        Links are followed first, so a link pointing outside the folder, or to a file
        that is not itself named like a script (the config, a database), is refused.
        """
        try:
            real = path.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if folder in real.parents and real.is_file() and SCRIPT_NAME.match(real.name):
            return real
        return None

    @staticmethod
    def _find(name: str, files: Dict[str, List[_Found]]) -> _Found:
        """Script *name* as listed in *files*, once its name is checked."""
        _parse(name)
        found = files.get(name)
        if not found:
            raise ScriptNotFound(f"no script named {name}")
        if len(found) > 1:
            raise ScriptError(f"two files are named {name}; rename one of them")
        return found[0]

    def _locate(self, name: str) -> Path:
        """The real file of script *name*: a checked name, confined to a migrations directory."""
        return self._find(name, self._files())[1]

    def _describe(self, name: str, listed: Path, files: Dict[str, List[_Found]]) -> Script:
        match = _parse(name)
        prefix, version = match["prefix"], match["version"] or ""
        kind = "repeatable" if match["repeatable"] else ("versioned" if prefix == "V" else "undo")
        relative = os.path.relpath(listed.parent, self.root)
        return Script(
            name=name,
            kind=kind,
            version=version.replace("_", "."),
            description=match["description"],
            language="python" if match["extension"] == "py" else "sql",
            directory=Path(relative).as_posix(),
            has_undo=kind == "versioned" and f"U{name[1:]}" in files,
        )

    def list(self) -> List[Script]:
        files = self._files()
        scripts = [self._describe(name, found[0][0], files) for name, found in files.items()]
        versioned = sorted(
            (s for s in scripts if s.kind == "versioned"),
            key=lambda s: (_version_key(s.version), s.name),
        )
        repeatable = sorted((s for s in scripts if s.kind == "repeatable"), key=lambda s: s.name)
        return versioned + repeatable

    def describe(self, name: str) -> Script:
        files = self._files()
        listed, _ = self._find(name, files)
        return self._describe(name, listed, files)

    def read(self, name: str) -> str:
        path = self._locate(name)
        try:
            # O_NOFOLLOW: the checked file, not a link swapped in since.
            handle = open(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb")
        except OSError as exc:
            raise ScriptError(f"cannot open {name}: {exc.strerror or exc}") from exc
        with handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ScriptError(f"{name} is not a file")
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ScriptError(f"{name} is too large to open here")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ScriptError(f"{name} is not UTF-8 text") from exc

    def write(self, name: str, content: str) -> None:
        path = self._locate(name)
        try:
            data = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ScriptError("the content is not valid UTF-8 text") from exc
        if len(data) > MAX_BYTES:
            raise ScriptError("the content is too large to save here")
        try:
            self._replace(path, data)
        except OSError as exc:
            raise ScriptError(f"cannot save {name}: {exc.strerror or exc}") from exc

    @staticmethod
    def _replace(path: Path, data: bytes) -> None:
        """Atomically give the checked real file *path* new content, keeping its mode.

        The temporary file gets a fresh, exclusively created name beside the target, so
        nothing already there (a link especially) is ever written through.
        """
        mode = stat.S_IMODE(path.stat().st_mode)
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with open(descriptor, "wb") as handle:
                handle.write(data)
                os.fchmod(handle.fileno(), mode)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def create(self, kind: str, language: str, description: str) -> List[str]:
        if kind not in ("versioned", "repeatable"):
            raise ScriptError("kind must be versioned or repeatable")
        if language not in _LANGUAGES:
            raise ScriptError("language must be sql or python")
        # One line of printable text: it cannot leave the comment or docstring it goes in.
        printable = "".join(ch if ch.isprintable() else " " for ch in str(description))
        title = " ".join(printable.split())
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        if not slug:
            raise ScriptError("describe the change with a few words")
        extension = _LANGUAGES[language]
        existing = self._files()
        if kind == "repeatable":
            names = [f"R__{slug}.{extension}"]
            headings = [title]
        else:
            version = self._next_version(existing)
            names = [f"V{version}__{slug}.{extension}", f"U{version}__{slug}.{extension}"]
            headings = [title, f"Undo: {title}"]
        folder = self.directories[0][0]
        for name in names:
            if name in existing or os.path.lexists(folder / name):
                raise ScriptError(f"{name} already exists")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ScriptError(
                f"cannot create the migrations directory: {exc.strerror or exc}"
            ) from exc
        created: List[Path] = []
        try:
            for name, heading in zip(names, headings):
                # "x" creates the file exclusively: never over a file, never through a link.
                with open(folder / name, "xb") as handle:
                    created.append(folder / name)
                    handle.write(_template(language, heading).encode("utf-8"))
        except OSError as exc:
            for path in created:
                path.unlink(missing_ok=True)
            if isinstance(exc, FileExistsError):
                raise ScriptError(f"{name} already exists") from exc
            raise ScriptError(f"cannot create the script: {exc.strerror or exc}") from exc
        return names

    @staticmethod
    def _next_version(existing: Dict[str, List[_Found]]) -> str:
        versions = []
        for name in existing:
            match = SCRIPT_NAME.match(name)
            if match and match["prefix"] == "V":
                versions.append(_version_key(match["version"]))
        if not versions:
            return "1_0_0"
        latest = max(versions)
        return "_".join(str(part) for part in (*latest[:-1], latest[-1] + 1))
