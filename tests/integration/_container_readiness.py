"""Docker-container readiness helpers for the integration test suite.

Extracted from ``tests/integration/conftest.py`` in PR-B6. ``conftest.py``
re-imports every symbol from this module so existing test code keeps
working through the conftest namespace.

Module-level constants stay tied to the runtime environment (OS, CPU
architecture, Docker provider). They are computed once at import time
and reused by ``wait_for_readiness`` and ``_apply_mysql_docker_run_options``.
"""

import os
import platform
import subprocess
import time

# Detect operating system and CPU architecture
IS_MACOS: bool = platform.system().lower() == "darwin"
IS_ARM_ARCHITECTURE: bool = platform.processor() == "arm" or "arm" in platform.machine().lower()


def is_using_colima() -> bool:
    """Check if we're using Colima as Docker provider."""
    try:
        # Check DOCKER_HOST environment variable (Colima sets this)
        docker_host = os.environ.get("DOCKER_HOST", "")
        if "colima" in docker_host:
            return True

        # Try to check Docker context which would indicate Colima
        result = subprocess.run(
            ["docker", "context", "inspect"], capture_output=True, text=True, check=False
        )
        return "colima" in result.stdout.lower()
    except Exception:
        return False


USING_COLIMA: bool = is_using_colima()
if USING_COLIMA:
    print("Detected Colima as Docker provider")


# MySQL: must match tests/integration/docker-compose.yml (auth + native-driver-friendly settings)
MYSQL_DOCKER_COMMAND = (
    "mysqld --log-bin-trust-function-creators=1 "
    "--default-authentication-plugin=mysql_native_password "
    "--skip-name-resolve --bind-address=0.0.0.0"
)


def _apply_mysql_docker_run_options(run_kwargs: dict) -> None:
    """Options for programmatic Docker runs; parity with compose `mysql` service."""
    run_kwargs["command"] = MYSQL_DOCKER_COMMAND
    if IS_MACOS and IS_ARM_ARCHITECTURE and USING_COLIMA:
        run_kwargs.setdefault("platform", "linux/amd64")
        run_kwargs.setdefault("mem_limit", "1g")


def wait_for_readiness(service, container):
    """Wait for database container to be ready for connections."""
    print(f"[{service.upper()}] Waiting for container to be ready...")
    # Adjust timeout for specific databases that need more time
    if service == "mysql" and IS_MACOS and IS_ARM_ARCHITECTURE:
        max_retries = 30  # 5 minutes total - MySQL on ARM emulation needs more time
        retry_interval = 10  # seconds - longer interval to reduce log spam
    elif service == "oracle":
        max_retries = 60  # 5 minutes total - Oracle can take a long time to initialize
        retry_interval = 5  # seconds
    elif service == "cosmosdb":
        max_retries = 40  # 3.3 minutes total - CosmosDB Emulator needs time to start all services
        retry_interval = 5  # seconds
    elif service == "db2" and not IS_MACOS:
        # Community DB2 image matches compose start_period (~300s); ibmcom image can be slow too
        max_retries = 70
        retry_interval = 5  # seconds — up to ~350s
    else:
        max_retries = 20  # ~100s for remaining DBs (sqlserver, postgresql, mysql on Linux, etc.)
        retry_interval = 5  # seconds

    def log_progress(elapsed_time):
        if elapsed_time % 15 == 0:  # Log every 15 seconds
            print(f"[{service.upper()}] Still waiting... {elapsed_time}s elapsed")

    # Check if container is actually running first
    try:
        container.reload()
        if container.status != "running":
            raise RuntimeError(
                f"Container {container.name} is not running (status: {container.status})"
            )
    except Exception as e:
        raise RuntimeError(f"Failed to check container status: {str(e)}")

    for attempt in range(max_retries):
        elapsed_time = attempt * retry_interval
        log_progress(elapsed_time)

        try:
            # Check container is still running
            container.reload()
            if container.status != "running":
                raise RuntimeError(f"Container stopped unexpectedly (status: {container.status})")

            if service == "oracle":
                logs = container.logs().decode(errors="ignore")
                if "DATABASE IS READY TO USE!" in logs:
                    print(f"[{service.upper()}] Database is ready!")
                    time.sleep(2)  # Reduced wait time
                    return
            elif service == "sqlserver":
                logs = container.logs().decode(errors="ignore")
                if "Recovery is complete" in logs or "The database is ready." in logs:
                    print(f"[{service.upper()}] Database is ready!")
                    time.sleep(2)  # Reduced wait time
                    return
            elif service == "postgresql":
                logs = container.logs().decode(errors="ignore")
                if "database system is ready to accept connections" in logs:
                    print(f"[{service.upper()}] Database is ready!")
                    time.sleep(2)  # Reduced wait time
                    return
            elif service == "mysql":
                logs = container.logs().decode(errors="ignore")
                if "ready for connections" in logs:
                    print(f"[{service.upper()}] Database is ready!")
                    # On macOS with ARM architecture, MySQL needs a bit more time
                    if IS_MACOS and IS_ARM_ARCHITECTURE:
                        print(f"[{service.upper()}] Giving MySQL extra time on ARM macOS...")
                        time.sleep(5)  # Extra time for MySQL on ARM
                    else:
                        time.sleep(2)  # Standard wait time
                    return
            elif service == "db2" and not IS_MACOS:
                logs = container.logs().decode(errors="ignore")
                if (
                    "(*) All databases are now active" in logs
                    or "Success: all databases are now active" in logs
                    or "DATABASE IS READY" in logs.upper()
                    or ("DB2INSTANCE" in logs and "setup has completed" in logs.lower())
                ):
                    print(f"[{service.upper()}] Database is ready!")
                    time.sleep(3)  # DB2 still needs a bit more time
                    return
            elif service == "cosmosdb":
                logs = container.logs().decode(errors="ignore")
                # Check for multiple patterns that indicate readiness
                # Pattern 1: "Started" and "Cosmos DB Emulator" (older format)
                # Pattern 2: "Gateway=OK" (newer format - gateway is ready)
                # Pattern 3: All services showing OK (PostgreSQL, Gateway, Explorer)
                if (
                    ("Started" in logs and "Cosmos DB Emulator" in logs)
                    or "Gateway=OK" in logs
                    or ("PostgreSQL=OK" in logs and "Gateway=OK" in logs and "Explorer=OK" in logs)
                ):
                    print(f"[{service.upper()}] CosmosDB Emulator is ready!")
                    time.sleep(5)  # CosmosDB needs extra time for backend services to initialize
                    return
            elif service == "mongodb":
                # Prefer an in-container ping; fall back to log scrape for
                # standalone mongo:7, which is ready within a few seconds.
                try:
                    exit_code, _ = container.exec_run(
                        ["mongosh", "--quiet", "--eval", "db.adminCommand('ping')"]
                    )
                    if exit_code == 0:
                        print(f"[{service.upper()}] Database is ready!")
                        time.sleep(1)
                        return
                except Exception as exec_err:
                    print(f"[{service.upper()}] mongosh ping unavailable: {exec_err}")
                logs = container.logs().decode(errors="ignore")
                if "Waiting for connections" in logs:
                    print(f"[{service.upper()}] Database is ready!")
                    time.sleep(1)
                    return
        except Exception as e:
            print(f"[{service.upper()}] Error checking readiness: {str(e)}")
            # Continue trying rather than failing immediately
            continue

        if attempt < max_retries - 1:  # Don't sleep on the last attempt
            time.sleep(retry_interval)

    # If we get here, container failed to become ready
    try:
        container.reload()
        logs = container.logs().decode(errors="ignore")
        print(f"\n[{service.upper()}] Container status: {container.status}")
        print(f"[{service.upper()}] Last 20 lines of logs:\n" + "\n".join(logs.splitlines()[-20:]))
    except Exception as e:
        print(f"[{service.upper()}] Could not retrieve logs: {str(e)}")

    raise TimeoutError(
        f"{service.upper()} container did not become ready within {max_retries * retry_interval} seconds"
    )
