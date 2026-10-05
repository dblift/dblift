"""Throwaway databases in local containers, for the scratch test.

Three runtimes behind one interface (Docker, Podman, Apple ``container``) and a catalogue
of the engines whose whole scratch cycle has been run in one. Every command is an argument
list with a timeout, never a shell; nothing here reads a config or opens a database.
"""

import json
import os
import re
import secrets
import shutil
import string
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol, Sequence, Tuple

from dblift_ui.masking import redact

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}\Z")
RUNTIME_VARIABLE = "DBLIFT_UI_CONTAINER_RUNTIME"
PROBE_SECONDS = 5
PULL_SECONDS = 15 * 60
COMMAND_SECONDS = 120
QUERY_SECONDS = 30
READY_SECONDS = 15
POLL_SECONDS = 0.5
LOG_LINES = 20
SHOWN_LINES = 10
DATABASE = "scratch"
SCHEMA_REFUSED = "The schema name cannot be used in a scratch container."
_ALPHABET = string.ascii_letters + string.digits


class ContainerError(Exception):
    """A container could not be used; the message is for the user."""


class NameTaken(ContainerError):
    """A container of the requested name already exists; it is not ours to touch."""


def _run(
    argv: Sequence[str], timeout: float, stdin: str = ""
) -> "subprocess.CompletedProcess[bytes]":
    """*argv* run to its end, its output captured; ContainerError when it cannot be."""
    what = " ".join(argv[:2])
    feed: Dict[str, Any] = (
        {"input": stdin.encode("utf-8")} if stdin else {"stdin": subprocess.DEVNULL}
    )
    try:
        return subprocess.run(list(argv), capture_output=True, timeout=timeout, **feed)
    except subprocess.TimeoutExpired as exc:
        raise ContainerError(f"{what} took too long and was stopped") from exc
    except OSError as exc:
        raise ContainerError(f"{argv[0]} could not be started: {exc.strerror or exc}") from exc
    except ValueError as exc:  # an argument holding a NUL byte
        raise ContainerError(f"{argv[0]} cannot be given that value") from exc


def _output(done: "subprocess.CompletedProcess[bytes]") -> str:
    return (done.stdout + done.stderr).decode("utf-8", errors="replace")


def _last_line(text: str, fallback: str) -> str:
    lines = [line for line in redact(text).strip().splitlines() if line.strip()]
    return lines[-1] if lines else fallback


def _last_lines(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-SHOWN_LINES:])


class Runtime(Protocol):
    """A container tool on this machine."""

    name: str

    def available(self) -> bool: ...

    def has_image(self, image: str) -> bool: ...

    def pull(self, image: str) -> None: ...

    def start(self, name: str, spec: "EngineSpec", environment: Dict[str, str]) -> None: ...

    def address(self, name: str, port: int) -> Tuple[str, int]: ...

    def execute(
        self, name: str, argv: Sequence[str], timeout: float, stdin: str = ""
    ) -> Tuple[int, str]: ...

    def running(self, name: str) -> bool: ...

    def logs(self, name: str) -> str: ...

    def remove(self, name: str) -> None: ...

    def names(self, prefix: str) -> List[str]: ...


class _Tool:
    """What every runtime shares: its binary, how a command is run, how one is checked."""

    name = ""
    binary = ""
    probe: Tuple[str, ...] = ("version",)

    def _call(
        self, *args: str, timeout: float = COMMAND_SECONDS, stdin: str = ""
    ) -> "subprocess.CompletedProcess[bytes]":
        return _run([self.binary, *args], timeout, stdin)

    def _check(self, *args: str, timeout: float = COMMAND_SECONDS) -> str:
        """Stdout of a command that must succeed; ContainerError with its last line otherwise."""
        done = self._call(*args, timeout=timeout)
        if done.returncode != 0:
            raise ContainerError(_last_line(_output(done), f"{self.binary} {args[0]} failed"))
        return done.stdout.decode("utf-8", errors="replace")

    def _removal(self, name: str) -> List[Tuple[str, ...]]:
        raise NotImplementedError

    def available(self) -> bool:
        if shutil.which(self.binary) is None:
            return False
        try:
            return self._call(*self.probe, timeout=PROBE_SECONDS).returncode == 0
        except ContainerError:
            return False

    def execute(
        self, name: str, argv: Sequence[str], timeout: float, stdin: str = ""
    ) -> Tuple[int, str]:
        interactive = ["-i"] if stdin else []
        done = self._call("exec", *interactive, name, *argv, timeout=timeout, stdin=stdin)
        return done.returncode, _output(done)

    def remove(self, name: str) -> None:
        for args in self._removal(name):
            try:
                self._call(*args, timeout=QUERY_SECONDS)
            except ContainerError:
                continue


class Docker(_Tool):
    name = "Docker"
    binary = "docker"

    def has_image(self, image: str) -> bool:
        try:
            return self._call("image", "inspect", image, timeout=QUERY_SECONDS).returncode == 0
        except ContainerError:
            return False

    def pull(self, image: str) -> None:
        self._check("pull", image, timeout=PULL_SECONDS)

    def start(self, name: str, spec: "EngineSpec", environment: Dict[str, str]) -> None:
        # Never pulled here, and reachable from this machine only.
        args = ["run", "-d", "--pull", "never", "--name", name, "-p", f"127.0.0.1::{spec.port}"]
        if spec.memory:
            args += ["--memory", spec.memory]
        if spec.architecture:
            args += ["--platform", f"linux/{spec.architecture}"]
        for key, value in environment.items():
            args += ["-e", f"{key}={value}"]
        self._check(*args, spec.image)

    def address(self, name: str, port: int) -> Tuple[str, int]:
        for line in self._check("port", name, f"{port}/tcp", timeout=QUERY_SECONDS).splitlines():
            host, _, published = line.strip().rpartition(":")
            if host == "127.0.0.1" and published.isdigit():
                return host, int(published)
        raise ContainerError(f"The container {name} has no address on this machine.")

    def running(self, name: str) -> bool:
        try:
            done = self._call(
                "inspect", "--format", "{{.State.Running}}", name, timeout=QUERY_SECONDS
            )
        except ContainerError:
            return False
        return done.returncode == 0 and done.stdout.strip() == b"true"

    def logs(self, name: str) -> str:
        try:
            return _output(
                self._call("logs", "--tail", str(LOG_LINES), name, timeout=QUERY_SECONDS)
            )
        except ContainerError:
            return ""

    def _removal(self, name: str) -> List[Tuple[str, ...]]:
        return [("stop", "-t", "5", name), ("rm", "-f", name)]

    def names(self, prefix: str) -> List[str]:
        listed = self._check(
            "ps",
            "-a",
            "--filter",
            f"name={prefix}",
            "--format",
            "{{.Names}}",
            timeout=QUERY_SECONDS,
        )
        return [name for name in listed.split() if name.startswith(prefix)]


class Podman(Docker):
    """Podman takes Docker's command line."""

    name = "Podman"
    binary = "podman"


class AppleContainer(_Tool):
    name = "Apple container"
    binary = "container"
    probe = ("system", "status")

    def has_image(self, image: str) -> bool:
        try:
            done = self._call("image", "inspect", image, timeout=QUERY_SECONDS)
        except ContainerError:
            return False
        return done.returncode == 0

    def pull(self, image: str) -> None:
        self._check("image", "pull", image, timeout=PULL_SECONDS)

    def start(self, name: str, spec: "EngineSpec", environment: Dict[str, str]) -> None:
        # The container gets its own address: no port is published on this machine.
        args = ["run", "-d", "--name", name]
        if spec.memory:
            args += ["-m", spec.memory]
        if spec.architecture:
            args += ["--arch", spec.architecture]
        for key, value in environment.items():
            args += ["-e", f"{key}={value}"]
        self._check(*args, spec.image)

    def _status(self, name: str) -> Dict[str, Any]:
        text = self._check("inspect", name, timeout=QUERY_SECONDS)
        try:
            status = json.loads(text)[0]["status"]
        except (ValueError, LookupError, TypeError) as exc:
            raise ContainerError(f"The container {name} could not be inspected.") from exc
        if not isinstance(status, dict):
            raise ContainerError(f"The container {name} could not be inspected.")
        return status

    def address(self, name: str, port: int) -> Tuple[str, int]:
        try:
            host = str(self._status(name)["networks"][0]["ipv4Address"]).split("/")[0]
        except (LookupError, TypeError) as exc:
            raise ContainerError(f"The container {name} has no address.") from exc
        if not host:
            raise ContainerError(f"The container {name} has no address.")
        return host, port

    def running(self, name: str) -> bool:
        try:
            return self._status(name).get("state") == "running"
        except ContainerError:
            return False

    def logs(self, name: str) -> str:
        try:
            return _output(self._call("logs", "-n", str(LOG_LINES), name, timeout=QUERY_SECONDS))
        except ContainerError:
            return ""

    def _removal(self, name: str) -> List[Tuple[str, ...]]:
        return [("stop", name), ("delete", "--force", name)]

    def names(self, prefix: str) -> List[str]:
        text = self._check("list", "--all", "--format", "json", timeout=QUERY_SECONDS)
        try:
            found = [str(entry["configuration"]["id"]) for entry in json.loads(text)]
        except (ValueError, LookupError, TypeError) as exc:
            raise ContainerError("The containers could not be listed.") from exc
        return [name for name in found if name.startswith(prefix)]


RUNTIMES: Dict[str, Callable[[], Runtime]] = {
    "docker": Docker,
    "podman": Podman,
    "container": AppleContainer,
}


def _forced() -> str:
    return os.environ.get(RUNTIME_VARIABLE, "").strip().lower()


def turned_off() -> bool:
    """Whether containers are turned off for this interface (``DBLIFT_UI_CONTAINER_RUNTIME=none``)."""
    return _forced() == "none"


def detect() -> Optional[Runtime]:
    """The first runtime that answers: Docker, Podman, then Apple ``container``.

    ``DBLIFT_UI_CONTAINER_RUNTIME`` names the only one to try; ``none``, or a name that is
    not a runtime, finds nothing.
    """
    forced = _forced()
    if forced:
        makers = [RUNTIMES[forced]] if forced in RUNTIMES else []
    else:
        makers = list(RUNTIMES.values())
    for make in makers:
        runtime = make()
        if runtime.available():
            return runtime
    return None


def _schema(schema: str) -> str:
    """*schema* when it may go into a command: empty, or a plain identifier."""
    if schema and not IDENTIFIER.match(schema):
        raise ContainerError(SCHEMA_REFUSED)
    return schema


def _no_input(schema: str, password: str) -> str:
    _schema(schema)
    return ""


@dataclass(frozen=True)
class EngineSpec:
    """How to run one engine in a container, and reach it once it is ready."""

    engine: str
    image: str
    size_mb: int
    port: int
    memory: str
    architecture: str
    environment: Callable[[str], Dict[str, str]]
    ready: Callable[[str], List[str]]
    prepare: Callable[[str, str], Optional[List[str]]]
    url: Callable[[str, int], str]
    username: str
    driver: str
    deadline_seconds: int
    # What the prepare command reads on its standard input, if anything.
    prepare_input: Callable[[str, str], str] = _no_input


def _postgresql_prepare(schema: str, password: str) -> Optional[List[str]]:
    if not _schema(schema):
        return None
    return [
        "psql",
        "-h",
        "127.0.0.1",
        "-U",
        "postgres",
        "-d",
        DATABASE,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        f'CREATE SCHEMA IF NOT EXISTS "{schema}"',
    ]


def _mysql_family(client: str, variable: str) -> Dict[str, Any]:
    def login(password: str) -> List[str]:
        return [client, "--protocol=TCP", "-h", "127.0.0.1", "-u", "root", f"--password={password}"]

    def prepare(schema: str, password: str) -> Optional[List[str]]:
        if not _schema(schema):
            return None
        return [*login(password), "-e", f"CREATE DATABASE IF NOT EXISTS `{schema}`"]

    return {
        "environment": lambda password: {
            f"{variable}_ROOT_PASSWORD": password,
            f"{variable}_DATABASE": DATABASE,
        },
        "ready": lambda password: [*login(password), "-e", "SELECT 1"],
        "prepare": prepare,
    }


_SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"
_SQL_SERVER_LOGIN = "dblift"


def _sqlcmd(password: str) -> List[str]:
    return [_SQLCMD, "-C", "-S", "127.0.0.1", "-U", "sa", "-P", password]


def _sql_server_prepare(schema: str, password: str) -> List[str]:
    """A database, and a login that is not ``dbo`` so the schema is its default one."""
    _schema(schema)
    target = schema if schema and schema.lower() != "dbo" else "dbo"
    in_database = f"EXEC [{DATABASE}].sys.sp_executesql N'"
    statements = [
        f"CREATE DATABASE [{DATABASE}]",
        f"CREATE LOGIN [{_SQL_SERVER_LOGIN}] WITH PASSWORD = N'{password}', CHECK_POLICY = OFF",
    ]
    if target != "dbo":
        statements.append(f"{in_database}CREATE SCHEMA [{target}]'")
    statements.append(
        f"{in_database}CREATE USER [{_SQL_SERVER_LOGIN}] FOR LOGIN [{_SQL_SERVER_LOGIN}] "
        f"WITH DEFAULT_SCHEMA = [{target}]; "
        f"ALTER ROLE [db_owner] ADD MEMBER [{_SQL_SERVER_LOGIN}]'"
    )
    return [*_sqlcmd(password), "-b", "-Q", "; ".join(statements)]


def _oracle_connect(password: str) -> str:
    return f"system/{password}@//127.0.0.1:1521/FREEPDB1"


def _oracle_needs_user(schema: str) -> bool:
    return bool(_schema(schema)) and schema.lower() != "system"


def _oracle_prepare(schema: str, password: str) -> Optional[List[str]]:
    # The statements go on standard input, read after an explicit CONNECT.
    return ["sqlplus", "-s", "/nolog"] if _oracle_needs_user(schema) else None


def _oracle_input(schema: str, password: str) -> str:
    if not _oracle_needs_user(schema):
        return ""
    return (
        "WHENEVER SQLERROR EXIT FAILURE\n"
        f"CONNECT {_oracle_connect(password)}\n"
        f'CREATE USER {schema} IDENTIFIED BY "{password}" '
        "DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS;\n"
        f"GRANT DB_DEVELOPER_ROLE TO {schema};\n"
        "EXIT\n"
    )


_POSTGRESQL = EngineSpec(
    engine="PostgreSQL",
    image="postgres:16",
    size_mb=160,
    port=5432,
    memory="",
    architecture="",
    environment=lambda password: {"POSTGRES_PASSWORD": password, "POSTGRES_DB": DATABASE},
    ready=lambda password: ["pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", DATABASE],
    prepare=_postgresql_prepare,
    url=lambda host, port: f"postgresql://{host}:{port}/{DATABASE}",
    username="postgres",
    driver="psycopg",
    deadline_seconds=60,
)
_SQL_SERVER = EngineSpec(
    engine="SQL Server",
    image="mcr.microsoft.com/mssql/server:2022-latest",
    size_mb=620,
    port=1433,
    memory="4g",
    architecture="amd64",
    environment=lambda password: {"ACCEPT_EULA": "Y", "MSSQL_SA_PASSWORD": password},
    ready=lambda password: [*_sqlcmd(password), "-l", "5", "-b", "-Q", "SELECT 1"],
    prepare=_sql_server_prepare,
    url=lambda host, port: f"mssql://{host}:{port}/{DATABASE}",
    username=_SQL_SERVER_LOGIN,
    driver="pymssql",
    deadline_seconds=240,
)
# Only engines whose whole scratch cycle has been run in a container; a config may spell
# an engine more than one way.
CATALOGUE: Dict[str, EngineSpec] = {
    "postgresql": _POSTGRESQL,
    "postgres": _POSTGRESQL,
    "mysql": EngineSpec(
        engine="MySQL",
        image="mysql:8",
        size_mb=235,
        port=3306,
        memory="",
        architecture="",
        url=lambda host, port: f"mysql://{host}:{port}/{DATABASE}",
        username="root",
        driver="pymysql",
        deadline_seconds=120,
        **_mysql_family("mysql", "MYSQL"),
    ),
    "mariadb": EngineSpec(
        engine="MariaDB",
        image="mariadb:11",
        size_mb=105,
        port=3306,
        memory="",
        architecture="",
        url=lambda host, port: f"mariadb://{host}:{port}/{DATABASE}",
        username="root",
        driver="pymysql",
        deadline_seconds=120,
        **_mysql_family("mariadb", "MARIADB"),
    ),
    "sqlserver": _SQL_SERVER,
    "mssql": _SQL_SERVER,
    "oracle": EngineSpec(
        engine="Oracle",
        image="gvenzl/oracle-free:slim-faststart",
        size_mb=1200,
        port=1521,
        memory="4g",
        architecture="",
        environment=lambda password: {"ORACLE_PASSWORD": password},
        ready=lambda password: ["sqlplus", "-s", "-L", _oracle_connect(password)],
        prepare=_oracle_prepare,
        url=lambda host, port: f"oracle://{host}:{port}/?service_name=FREEPDB1",
        username="system",
        driver="oracledb",
        deadline_seconds=300,
        prepare_input=_oracle_input,
    ),
}


@dataclass(frozen=True)
class Database:
    url: str
    username: str
    password: str = field(repr=False)


def new_password() -> str:
    """A random password every engine accepts: letters and digits, starting with a letter."""
    while True:
        candidate = "".join(secrets.choice(_ALPHABET) for _ in range(32))
        if (
            candidate[0].isalpha()
            and any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)
            and any(c.isdigit() for c in candidate)
        ):
            return candidate


def _wait(runtime: Runtime, spec: EngineSpec, name: str, password: str) -> None:
    """Return once *spec*'s readiness command succeeds in the container."""
    deadline = time.monotonic() + spec.deadline_seconds
    probe = spec.ready(password)
    while True:
        remaining = deadline - time.monotonic()
        try:
            code, _ = runtime.execute(name, probe, min(READY_SECONDS, max(1.0, remaining)))
        except ContainerError:
            code = -1  # a probe that hangs is a server not ready yet
        if code == 0:
            return
        if not runtime.running(name):
            tail = _last_lines(runtime.logs(name))
            ending = f" Its last lines:\n{tail}" if tail else ""
            raise ContainerError(
                f"The {spec.engine} container stopped before it was ready.{ending}"
            )
        if time.monotonic() >= deadline:
            raise ContainerError(
                f"The {spec.engine} database was not ready within {spec.deadline_seconds} s."
            )
        time.sleep(POLL_SECONDS)


@contextmanager
def scratch_database(
    runtime: Runtime, spec: EngineSpec, name: str, schema: str
) -> Iterator[Database]:
    """A new database in container *name*, ready and holding *schema*; always removed after.

    Every error names what went wrong with the run's password masked.
    """
    password = new_password()
    # Built before anything starts: a schema that is not an identifier stops here.
    prepare = spec.prepare(schema, password)
    prepare_input = spec.prepare_input(schema, password)
    # A container of that name is someone else's: never started, stopped or removed here.
    if name in runtime.names(name):
        raise NameTaken(f"A container named {name} already exists; it is left alone.")
    try:
        try:
            runtime.start(name, spec, spec.environment(password))
            _wait(runtime, spec, name, password)
            if prepare is not None:
                code, output = runtime.execute(name, prepare, COMMAND_SECONDS, prepare_input)
                if code != 0:
                    raise ContainerError(
                        f"The schema {schema} could not be created: {_last_lines(output)}"
                    )
            host, port = runtime.address(name, spec.port)
        except ContainerError as exc:
            raise ContainerError(redact(str(exc).replace(password, "***"))) from None
        yield Database(spec.url(host, port), spec.username, password)
    finally:
        runtime.remove(name)
