import json
import subprocess

import pytest
from dblift_ui import containers

NAME = "dblift-ui-ab12cd34-0123"
SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"


def _spec(**changes):
    values = dict(
        engine="Fake",
        image="example/db:1",
        size_mb=10,
        port=5432,
        memory="",
        architecture="",
        environment=lambda password: {"PASSWORD": password},
        ready=lambda password: ["ready"],
        prepare=lambda schema, password: ["prepare", schema] if schema else None,
        url=lambda host, port: f"fake://{host}:{port}/scratch",
        username="admin",
        driver="sqlite3",
        deadline_seconds=10,
    )
    values.update(changes)
    return containers.EngineSpec(**values)


class Commands:
    """Stands in for subprocess.run: records each call and answers with ``answer(argv)``."""

    def __init__(self):
        self.calls = []
        self.answer = lambda argv: (0, "", "")

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        reply = self.answer(argv)
        if isinstance(reply, BaseException):
            raise reply
        code, out, err = reply
        return subprocess.CompletedProcess(argv, code, out.encode(), err.encode())

    @property
    def argvs(self):
        return [argv for argv, _ in self.calls]


@pytest.fixture
def commands(monkeypatch):
    spy = Commands()
    monkeypatch.setattr(containers.subprocess, "run", spy)
    monkeypatch.setattr(containers.shutil, "which", lambda name: f"/usr/bin/{name}")
    return spy


@pytest.fixture
def clock(monkeypatch):
    """A clock that only moves when the code sleeps."""
    now = [1000.0]
    monkeypatch.setattr(containers.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        containers.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds)
    )
    return now


RUNTIMES = [containers.Docker, containers.Podman, containers.AppleContainer]
BINARY = {
    containers.Docker: "docker",
    containers.Podman: "podman",
    containers.AppleContainer: "container",
}


# --- adapters -----------------------------------------------------------------------


@pytest.mark.parametrize("runtime", [containers.Docker, containers.Podman])
def test_docker_and_podman_start_publish_on_loopback_and_never_pull(commands, runtime):
    spec = _spec(memory="4g", architecture="amd64")

    runtime().start(NAME, spec, {"A": "1", "B": "two words"})

    binary = BINARY[runtime]
    assert commands.argvs == [
        [
            binary,
            "run",
            "-d",
            "--pull",
            "never",
            "--name",
            NAME,
            "-p",
            "127.0.0.1::5432",
            "--memory",
            "4g",
            "--platform",
            "linux/amd64",
            "-e",
            "A=1",
            "-e",
            "B=two words",
            "example/db:1",
        ]
    ]


def test_apple_container_start(commands):
    spec = _spec(memory="4g", architecture="amd64")

    containers.AppleContainer().start(NAME, spec, {"A": "1", "B": "two words"})

    assert commands.argvs == [
        [
            "container",
            "run",
            "-d",
            "--name",
            NAME,
            "-m",
            "4g",
            "--arch",
            "amd64",
            "-e",
            "A=1",
            "-e",
            "B=two words",
            "example/db:1",
        ]
    ]


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_a_spec_without_memory_or_architecture_adds_neither(commands, runtime):
    runtime().start(NAME, _spec(), {})

    argv = commands.argvs[0]
    assert not {"--memory", "-m", "--platform", "--arch"} & set(argv)
    assert argv[-1] == "example/db:1"


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_a_start_the_runtime_refuses_is_an_error(commands, runtime):
    commands.answer = lambda argv: (125, "", "first\nno such image\n")

    with pytest.raises(containers.ContainerError, match="no such image"):
        runtime().start(NAME, _spec(), {})


@pytest.mark.parametrize("runtime", [containers.Docker, containers.Podman])
def test_docker_address_is_the_loopback_port(commands, runtime):
    commands.answer = lambda argv: (0, "[::1]:49152\n127.0.0.1:49153\n", "")

    assert runtime().address(NAME, 5432) == ("127.0.0.1", 49153)
    assert commands.argvs == [[BINARY[runtime], "port", NAME, "5432/tcp"]]


def test_docker_address_without_a_loopback_line_is_an_error(commands):
    commands.answer = lambda argv: (0, "[::1]:49152\n", "")

    with pytest.raises(containers.ContainerError):
        containers.Docker().address(NAME, 5432)


def test_apple_container_address_is_the_containers_own(commands):
    inspected = [{"status": {"state": "running", "networks": [{"ipv4Address": "192.168.64.9/24"}]}}]
    commands.answer = lambda argv: (0, json.dumps(inspected), "")

    assert containers.AppleContainer().address(NAME, 5432) == ("192.168.64.9", 5432)
    assert commands.argvs == [["container", "inspect", NAME]]


@pytest.mark.parametrize("output", ["not json", "[]", '[{"status": {"networks": []}}]'])
def test_apple_container_address_unreadable_is_an_error(commands, output):
    commands.answer = lambda argv: (0, output, "")

    with pytest.raises(containers.ContainerError):
        containers.AppleContainer().address(NAME, 5432)


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_execute_runs_the_arguments_in_the_container(commands, runtime):
    commands.answer = lambda argv: (3, "out\n", "err\n")

    code, text = runtime().execute(NAME, ["psql", "-c", "SELECT 1"], timeout=7)

    assert (code, text) == (3, "out\nerr\n")
    assert commands.argvs == [[BINARY[runtime], "exec", NAME, "psql", "-c", "SELECT 1"]]
    kwargs = commands.calls[0][1]
    assert kwargs["timeout"] == 7 and kwargs["stdin"] is subprocess.DEVNULL


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_execute_with_input_keeps_standard_input_open(commands, runtime):
    runtime().execute(NAME, ["sqlplus", "-s", "/nolog"], timeout=7, stdin="EXIT\n")

    assert commands.argvs == [[BINARY[runtime], "exec", "-i", NAME, "sqlplus", "-s", "/nolog"]]
    assert commands.calls[0][1]["input"] == b"EXIT\n"


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_an_execute_that_runs_too_long_is_an_error(commands, runtime):
    commands.answer = lambda argv: subprocess.TimeoutExpired(argv, 7)

    with pytest.raises(containers.ContainerError, match="too long"):
        runtime().execute(NAME, ["true"], timeout=7)


def test_docker_remove_stops_then_deletes(commands):
    containers.Docker().remove(NAME)

    assert commands.argvs == [["docker", "stop", "-t", "5", NAME], ["docker", "rm", "-f", NAME]]


def test_apple_container_remove_stops_then_deletes(commands):
    containers.AppleContainer().remove(NAME)

    assert commands.argvs == [["container", "stop", NAME], ["container", "delete", "--force", NAME]]


@pytest.mark.parametrize("runtime", RUNTIMES)
@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired(["x"], 60),
        OSError(2, "No such file or directory"),
        (1, "", "Error: not found"),
    ],
)
def test_remove_never_raises_and_still_tries_to_delete(commands, runtime, failure):
    commands.answer = lambda argv: failure

    runtime().remove(NAME)

    assert len(commands.argvs) == 2


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_has_image(commands, runtime):
    expected = {
        containers.Docker: ["docker", "image", "inspect", "example/db:1"],
        containers.Podman: ["podman", "image", "inspect", "example/db:1"],
        containers.AppleContainer: ["container", "image", "inspect", "example/db:1"],
    }[runtime]

    assert runtime().has_image("example/db:1") is True
    commands.answer = lambda argv: (1, "", "no such image")
    assert runtime().has_image("example/db:1") is False
    commands.answer = lambda argv: subprocess.TimeoutExpired(argv, 30)
    assert runtime().has_image("example/db:1") is False
    assert commands.argvs == [expected] * 3


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_pull_has_a_long_timeout_and_reports_a_failure(commands, runtime):
    expected = {
        containers.Docker: ["docker", "pull", "example/db:1"],
        containers.Podman: ["podman", "pull", "example/db:1"],
        containers.AppleContainer: ["container", "image", "pull", "example/db:1"],
    }[runtime]

    runtime().pull("example/db:1")
    commands.answer = lambda argv: (1, "", "manifest unknown")
    with pytest.raises(containers.ContainerError, match="manifest unknown"):
        runtime().pull("example/db:1")

    assert commands.argvs == [expected] * 2
    assert commands.calls[0][1]["timeout"] == 15 * 60


@pytest.mark.parametrize("runtime", [containers.Docker, containers.Podman])
def test_docker_names_keep_only_the_prefix(commands, runtime):
    prefix = "dblift-ui-ab12cd34-"
    listed = f"{prefix}1\nother-{prefix}2\n{prefix}3\npr320_pg16\n"
    commands.answer = lambda argv: (0, listed, "")

    assert runtime().names(prefix) == [f"{prefix}1", f"{prefix}3"]
    assert commands.argvs == [
        [BINARY[runtime], "ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"]
    ]


def test_apple_container_names_keep_only_the_prefix(commands):
    prefix = "dblift-ui-ab12cd34-"
    listed = [
        {"configuration": {"id": f"{prefix}1"}},
        {"configuration": {"id": f"other-{prefix}2"}},
        {"configuration": {"id": "pr320_pg16"}},
    ]
    commands.answer = lambda argv: (0, json.dumps(listed), "")

    assert containers.AppleContainer().names(prefix) == [f"{prefix}1"]
    assert commands.argvs == [["container", "list", "--all", "--format", "json"]]


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_names_that_cannot_be_listed_is_an_error(commands, runtime):
    commands.answer = lambda argv: (1, "", "daemon down")

    with pytest.raises(containers.ContainerError):
        runtime().names("dblift-ui-")


def test_docker_running_and_logs(commands):
    commands.answer = lambda argv: (0, "true\n" if argv[1] == "inspect" else "a\nb\n", "")

    assert containers.Docker().running(NAME) is True
    assert containers.Docker().logs(NAME) == "a\nb\n"
    assert commands.argvs == [
        ["docker", "inspect", "--format", "{{.State.Running}}", NAME],
        ["docker", "logs", "--tail", "20", NAME],
    ]


def test_apple_container_running_and_logs(commands):
    stopped = [{"status": {"state": "stopped", "networks": []}}]
    commands.answer = lambda argv: (0, json.dumps(stopped) if argv[1] == "inspect" else "a\n", "")

    assert containers.AppleContainer().running(NAME) is False
    assert containers.AppleContainer().logs(NAME) == "a\n"
    assert commands.argvs == [
        ["container", "inspect", NAME],
        ["container", "logs", "-n", "20", NAME],
    ]


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_every_command_is_a_list_with_a_timeout_and_no_shell(commands, runtime):
    adapter = runtime()
    adapter.available()
    adapter.has_image("example/db:1")
    adapter.pull("example/db:1")
    adapter.start(NAME, _spec(), {"A": "1"})
    adapter.execute(NAME, ["true"], timeout=3)
    adapter.running(NAME)
    adapter.logs(NAME)
    adapter.remove(NAME)
    try:
        adapter.names("dblift-ui-")
        adapter.address(NAME, 5432)
    except containers.ContainerError:
        pass  # the empty answers are not parseable; only the calls matter here

    assert len(commands.calls) >= 10
    for argv, kwargs in commands.calls:
        assert isinstance(argv, list) and all(isinstance(part, str) for part in argv)
        assert kwargs.get("timeout")
        assert not kwargs.get("shell")


# --- detect -------------------------------------------------------------------------


@pytest.fixture
def unforced(monkeypatch):
    monkeypatch.delenv(containers.RUNTIME_VARIABLE, raising=False)


def test_detect_prefers_docker_then_podman_then_apple_container(commands, monkeypatch, unforced):
    assert isinstance(containers.detect(), containers.Docker)

    monkeypatch.setattr(containers.shutil, "which", lambda name: None if name == "docker" else name)
    assert isinstance(containers.detect(), containers.Podman)

    monkeypatch.setattr(
        containers.shutil, "which", lambda name: name if name == "container" else None
    )
    assert isinstance(containers.detect(), containers.AppleContainer)

    monkeypatch.setattr(containers.shutil, "which", lambda name: None)
    assert containers.detect() is None


def test_detect_asks_each_tool_whether_it_answers(commands, unforced):
    containers.detect()

    assert commands.argvs == [["docker", "version"]]
    assert commands.calls[0][1]["timeout"] == 5


def test_a_tool_on_the_path_that_does_not_answer_is_passed_over(commands, unforced):
    def answer(argv):
        if argv[0] == "docker":
            return subprocess.TimeoutExpired(argv, 5)
        if argv[0] == "podman":
            return (125, "", "Cannot connect to Podman")
        return (0, "running", "")

    commands.answer = answer

    assert isinstance(containers.detect(), containers.AppleContainer)
    assert commands.argvs == [
        ["docker", "version"],
        ["podman", "version"],
        ["container", "system", "status"],
    ]


@pytest.mark.parametrize(
    "value, kind",
    [
        ("podman", containers.Podman),
        ("container", containers.AppleContainer),
        ("DOCKER", containers.Docker),
    ],
)
def test_detect_can_be_forced(commands, monkeypatch, value, kind):
    monkeypatch.setenv(containers.RUNTIME_VARIABLE, value)

    assert isinstance(containers.detect(), kind)
    assert len(commands.calls) == 1


def test_a_forced_runtime_that_does_not_answer_is_not_replaced(commands, monkeypatch):
    monkeypatch.setenv(containers.RUNTIME_VARIABLE, "podman")
    commands.answer = lambda argv: (125, "", "down")

    assert containers.detect() is None
    assert commands.argvs == [["podman", "version"]]


@pytest.mark.parametrize("value", ["none", "None", "something-else"])
def test_none_or_an_unknown_name_finds_nothing_and_runs_nothing(commands, monkeypatch, value):
    monkeypatch.setenv(containers.RUNTIME_VARIABLE, value)

    assert containers.detect() is None
    assert commands.calls == []


def test_turned_off_only_for_none(monkeypatch):
    monkeypatch.setenv(containers.RUNTIME_VARIABLE, " NONE ")
    assert containers.turned_off() is True
    monkeypatch.setenv(containers.RUNTIME_VARIABLE, "docker")
    assert containers.turned_off() is False
    monkeypatch.delenv(containers.RUNTIME_VARIABLE)
    assert containers.turned_off() is False


# --- catalogue ----------------------------------------------------------------------

PW = "Pw0rdPw0rdPw0rdPw0rdPw0rd"


def test_the_catalogue_holds_the_verified_engines_and_their_spellings():
    assert set(containers.CATALOGUE) == {
        "postgresql",
        "postgres",
        "mysql",
        "mariadb",
        "sqlserver",
        "mssql",
        "oracle",
    }
    assert containers.CATALOGUE["postgres"] is containers.CATALOGUE["postgresql"]
    assert containers.CATALOGUE["mssql"] is containers.CATALOGUE["sqlserver"]


def _shape(spec):
    return (
        spec.engine,
        spec.image,
        spec.size_mb,
        spec.port,
        spec.memory,
        spec.architecture,
        spec.username,
        spec.driver,
        spec.deadline_seconds,
    )


def test_postgresql():
    spec = containers.CATALOGUE["postgresql"]

    assert _shape(spec) == (
        "PostgreSQL",
        "postgres:16",
        160,
        5432,
        "",
        "",
        "postgres",
        "psycopg",
        60,
    )
    assert spec.environment(PW) == {"POSTGRES_PASSWORD": PW, "POSTGRES_DB": "scratch"}
    assert spec.ready(PW) == ["pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "scratch"]
    assert spec.prepare("sales", PW) == [
        "psql",
        "-h",
        "127.0.0.1",
        "-U",
        "postgres",
        "-d",
        "scratch",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        'CREATE SCHEMA IF NOT EXISTS "sales"',
    ]
    assert spec.prepare_input("sales", PW) == ""
    assert spec.prepare("", PW) is None
    assert spec.url("192.168.64.9", 5432) == "postgresql://192.168.64.9:5432/scratch"


@pytest.mark.parametrize(
    "key, engine, image, size, client, variable",
    [
        ("mysql", "MySQL", "mysql:8", 235, "mysql", "MYSQL"),
        ("mariadb", "MariaDB", "mariadb:11", 105, "mariadb", "MARIADB"),
    ],
)
def test_mysql_and_mariadb(key, engine, image, size, client, variable):
    spec = containers.CATALOGUE[key]
    login = [client, "--protocol=TCP", "-h", "127.0.0.1", "-u", "root", f"--password={PW}"]

    assert _shape(spec) == (engine, image, size, 3306, "", "", "root", "pymysql", 120)
    assert spec.environment(PW) == {
        f"{variable}_ROOT_PASSWORD": PW,
        f"{variable}_DATABASE": "scratch",
    }
    assert spec.ready(PW) == [*login, "-e", "SELECT 1"]
    assert spec.prepare("sales", PW) == [*login, "-e", "CREATE DATABASE IF NOT EXISTS `sales`"]
    assert spec.prepare("", PW) is None
    assert spec.url("10.0.0.2", 3306) == f"{key}://10.0.0.2:3306/scratch"


def test_sql_server():
    spec = containers.CATALOGUE["sqlserver"]
    login = [SQLCMD, "-C", "-S", "127.0.0.1", "-U", "sa", "-P", PW]

    assert _shape(spec) == (
        "SQL Server",
        "mcr.microsoft.com/mssql/server:2022-latest",
        620,
        1433,
        "4g",
        "amd64",
        "dblift",
        "pymssql",
        240,
    )
    assert spec.environment(PW) == {"ACCEPT_EULA": "Y", "MSSQL_SA_PASSWORD": PW}
    assert spec.ready(PW) == [*login, "-l", "5", "-b", "-Q", "SELECT 1"]
    assert spec.prepare("sales", PW) == [
        *login,
        "-b",
        "-Q",
        "CREATE DATABASE [scratch]; "
        f"CREATE LOGIN [dblift] WITH PASSWORD = N'{PW}', CHECK_POLICY = OFF; "
        "EXEC [scratch].sys.sp_executesql N'CREATE SCHEMA [sales]'; "
        "EXEC [scratch].sys.sp_executesql N'CREATE USER [dblift] FOR LOGIN [dblift] "
        "WITH DEFAULT_SCHEMA = [sales]; ALTER ROLE [db_owner] ADD MEMBER [dblift]'",
    ]
    assert spec.url("10.0.0.3", 1433) == "mssql://10.0.0.3:1433/scratch"


@pytest.mark.parametrize("schema", ["", "dbo", "DBO"])
def test_sql_server_on_its_default_schema_creates_no_schema(schema):
    command = containers.CATALOGUE["sqlserver"].prepare(schema, PW)[-1]

    assert "CREATE SCHEMA" not in command
    assert "WITH DEFAULT_SCHEMA = [dbo]" in command


def test_oracle():
    spec = containers.CATALOGUE["oracle"]
    connect = f"system/{PW}@//127.0.0.1:1521/FREEPDB1"

    assert _shape(spec) == (
        "Oracle",
        "gvenzl/oracle-free:slim-faststart",
        1200,
        1521,
        "4g",
        "",
        "system",
        "oracledb",
        300,
    )
    assert spec.environment(PW) == {"ORACLE_PASSWORD": PW}
    assert spec.ready(PW) == ["sqlplus", "-s", "-L", connect]
    assert spec.prepare("sales", PW) == ["sqlplus", "-s", "/nolog"]
    assert spec.prepare_input("sales", PW) == (
        "WHENEVER SQLERROR EXIT FAILURE\n"
        f"CONNECT {connect}\n"
        f'CREATE USER sales IDENTIFIED BY "{PW}" DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS;\n'
        "GRANT DB_DEVELOPER_ROLE TO sales;\n"
        "EXIT\n"
    )
    assert spec.prepare("", PW) is None
    assert spec.prepare("SYSTEM", PW) is None
    assert spec.url("10.0.0.4", 1521) == "oracle://10.0.0.4:1521/?service_name=FREEPDB1"


@pytest.mark.parametrize("key", sorted(containers.CATALOGUE))
@pytest.mark.parametrize("schema", ["sales; DROP", "a b", 'x"y', "x" * 100, "1abc", "x'y", "x]y"])
def test_prepare_is_never_built_from_a_schema_that_is_not_an_identifier(key, schema):
    spec = containers.CATALOGUE[key]

    with pytest.raises(containers.ContainerError):
        spec.prepare(schema, PW)
    with pytest.raises(containers.ContainerError):
        spec.prepare_input(schema, PW)


@pytest.mark.parametrize("name", ["sales", "_x", "Sales_2024", "a$b", "x" * 63])
def test_plain_identifiers_are_accepted(name):
    assert containers.IDENTIFIER.match(name)


@pytest.mark.parametrize("name", ["", "x" * 64, "a-b", "a.b", "é", "a\n"])
def test_other_names_are_not_identifiers(name):
    assert not containers.IDENTIFIER.match(name)


# --- scratch_database ---------------------------------------------------------------


def _open(runtime, spec=None, schema="sales"):
    with containers.scratch_database(runtime, spec or _spec(), NAME, schema) as database:
        return database


def test_a_database_ready_after_three_polls_yields_its_address_and_credentials(fake_runtime, clock):
    runtime = fake_runtime()
    runtime.replies["ready"] = [(1, "starting"), (1, "starting"), (0, "")]

    database = _open(runtime)

    assert database.url == "fake://127.0.0.1:5432/scratch"
    assert database.username == "admin"
    assert runtime.started == [(NAME, "example/db:1", {"PASSWORD": database.password})]
    assert [argv for argv, _, _ in runtime.executed] == [
        ["ready"],
        ["ready"],
        ["ready"],
        ["prepare", "sales"],
    ]
    assert clock[0] == 1001.0  # two waits of half a second
    assert runtime.removed == [NAME]


def test_the_password_is_random_per_call_and_long(fake_runtime):
    first, second = _open(fake_runtime()), _open(fake_runtime())

    assert first.password != second.password
    assert len(first.password) >= 24 and len(second.password) >= 24
    assert first.password not in repr(first)


def test_the_prepare_command_receives_its_input(fake_runtime):
    runtime = fake_runtime()
    spec = _spec(prepare_input=lambda schema, password: f"CREATE {schema};\n")

    _open(runtime, spec)

    assert runtime.executed[-1][:2] == (["prepare", "sales"], "CREATE sales;\n")


def test_no_schema_means_no_preparation(fake_runtime):
    runtime = fake_runtime()

    _open(runtime, schema="")

    assert [argv for argv, _, _ in runtime.executed] == [["ready"]]


def test_a_database_never_ready_names_the_deadline_and_is_removed(fake_runtime, clock):
    runtime = fake_runtime()
    runtime.replies["ready"] = (1, "not yet")

    with pytest.raises(containers.ContainerError, match="not ready within 10 s"):
        _open(runtime)

    assert runtime.removed == [NAME]
    assert clock[0] >= 1010.0


def test_a_probe_that_hangs_counts_as_not_ready(fake_runtime, clock):
    runtime = fake_runtime()
    calls = []

    def execute(name, argv, timeout, stdin=""):
        calls.append(timeout)
        if len(calls) < 3:
            raise containers.ContainerError("container exec took too long and was stopped")
        return 0, ""

    runtime.execute = execute

    _open(runtime, schema="")

    assert len(calls) == 3 and all(0 < timeout <= 15 for timeout in calls)


def test_a_container_that_exits_reports_its_last_lines_without_the_password(fake_runtime, clock):
    runtime = fake_runtime()
    runtime.replies["ready"] = (1, "")

    def stop_with_output(name, spec, environment):
        password = environment["PASSWORD"]
        runtime.existing.append(name)
        runtime.stopped = True
        lines = [f"line {n}" for n in range(30)]
        runtime.output = "\n".join(lines + [f"FATAL: bad setting for {password}"]) + "\n"

    runtime.start = stop_with_output

    with pytest.raises(containers.ContainerError) as caught:
        _open(runtime)

    message = str(caught.value)
    assert "stopped before it was ready" in message
    assert "FATAL: bad setting for ***" in message
    assert "line 29" in message and "line 5\n" not in message
    assert runtime.removed == [NAME]


def test_a_failing_preparation_is_an_error_without_the_password(fake_runtime):
    runtime = fake_runtime()
    seen = []

    def execute(name, argv, timeout, stdin=""):
        if argv[0] == "prepare":
            password = runtime.started[0][2]["PASSWORD"]
            seen.append(password)
            return 1, f"ERROR: login with {password} refused\npostgresql://u:{password}@h/x"
        return 0, ""

    runtime.execute = execute

    with pytest.raises(containers.ContainerError) as caught:
        _open(runtime)

    assert "sales" in str(caught.value) and "refused" in str(caught.value)
    assert seen and seen[0] not in str(caught.value)
    assert runtime.removed == [NAME]


def test_a_start_that_fails_still_removes_whatever_was_created(fake_runtime):
    runtime = fake_runtime()

    def refuse(name, spec, environment):
        raise containers.ContainerError(f"refused, password {environment['PASSWORD']}")

    runtime.start = refuse

    with pytest.raises(containers.ContainerError) as caught:
        _open(runtime)

    assert "refused, password ***" in str(caught.value)
    assert runtime.removed == [NAME]


def test_an_exception_inside_the_block_still_removes_the_container_once(fake_runtime):
    runtime = fake_runtime()

    with pytest.raises(KeyError):
        with containers.scratch_database(runtime, _spec(), NAME, "sales"):
            raise KeyError("boom")

    assert runtime.removed == [NAME]


def test_a_bad_schema_is_refused_before_anything_starts(fake_runtime):
    runtime = fake_runtime()

    with pytest.raises(containers.ContainerError):
        _open(runtime, containers.CATALOGUE["postgresql"], schema="sales; DROP")

    assert runtime.started == [] and runtime.removed == []


def test_an_existing_container_of_that_name_is_left_alone(fake_runtime):
    runtime = fake_runtime()
    runtime.existing.append(NAME)

    with pytest.raises(containers.ContainerError, match="already exists"):
        _open(runtime)

    assert runtime.started == [] and runtime.removed == []
    assert runtime.existing == [NAME]
