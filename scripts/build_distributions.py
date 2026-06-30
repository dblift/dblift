#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def get_platform_info() -> Tuple[str, str]:
    """Get current platform and architecture."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Map platform identifiers
    if system == "darwin":
        system = "darwin"
    elif system == "linux":
        system = "linux"
    elif system == "windows":
        system = "win32"
    else:
        raise ValueError(f"Unsupported platform: {system}")

    # Map architecture identifiers
    if machine == "x86_64" or machine == "amd64":
        machine = "x86_64"
    elif machine == "arm64" or machine == "aarch64":
        machine = "aarch64"
    else:
        raise ValueError(f"Unsupported architecture: {machine}")

    return system, machine


def normalize_cli_arch(machine: str) -> str:
    """Map `--arch` values to the same canonical names as get_platform_info().

    CI workflows often pass ``arm64`` while Python reports ``aarch64`` on Apple Silicon.
    """
    m = machine.lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "aarch64"
    raise ValueError(f"Unsupported architecture for --arch: {machine}")


def get_version(project_root: Path) -> str:
    """Get version from __init__.py."""
    init_file = project_root / "__init__.py"
    if init_file.exists():
        with open(init_file, "r") as f:
            for line in f:
                if line.startswith("__version__"):
                    # Extract version string from __version__ = "x.y.z"
                    # Split on '=' and get the part after it
                    if "=" in line:
                        parts = line.split("=", 1)
                        if len(parts) > 1:
                            value = parts[1].strip()
                            # Remove quotes if present
                            value = value.strip('"').strip("'")
                            return value
    return "0.0.0"  # Fallback version


def compile_cython_modules(project_root: Path) -> bool:
    """Compile critical-path modules to native extensions (.so / .pyd).

    Returns True on success, False on failure (build continues without compilation).
    """
    setup_cython = project_root / "setup_cython.py"
    if not setup_cython.exists():
        logging.warning("setup_cython.py not found — skipping Cython compilation")
        return False

    try:
        logging.info("Compiling critical-path modules with Cython...")
        subprocess.check_call(
            [sys.executable, str(setup_cython), "build_ext", "--inplace"],
            cwd=str(project_root),
        )
        logging.info("Cython compilation succeeded")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Cython compilation failed: {e}")
        return False


def _strip_compiled_sources(dist_dir: Path, project_root: Path) -> None:
    """Replace compiled .py files with their .so/.pyd counterparts in dist_dir.

    For every Cython-compiled module listed in setup_cython.py we:
    1. Find the corresponding .so or .pyd in the source tree (build_ext --inplace).
    2. Copy it into *dist_dir* at the same relative location.
    3. Remove the .py source from *dist_dir* (the .so replaces it).
    4. Remove any intermediate .c files from *dist_dir*.
    """
    # Import the single source of truth from setup_cython.py
    spec = importlib.util.spec_from_file_location("setup_cython", project_root / "setup_cython.py")
    setup_cython_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup_cython_mod)  # type: ignore[union-attr]
    cython_sources = setup_cython_mod._CYTHON_MODULES

    for rel_py in cython_sources:
        stem = Path(rel_py).stem
        parent = Path(rel_py).parent

        # Find the compiled extension in the source tree (e.g. cli/main.cpython-311-darwin.so)
        src_dir = project_root / parent
        so_files = list(src_dir.glob(f"{stem}.cpython-*.*"))
        so_files = [f for f in so_files if f.suffix in (".so", ".pyd")]

        if not so_files:
            logging.warning(f"No compiled extension found for {rel_py} — keeping .py")
            continue

        so_file = so_files[0]  # pick the one matching this Python version

        target_dir = dist_dir / parent
        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy .so/.pyd into dist
        shutil.copy2(so_file, target_dir / so_file.name)
        logging.info(f"Copied compiled module: {parent / so_file.name}")

        # Remove the .py source from dist (keep __init__.py for package imports)
        py_in_dist = dist_dir / rel_py
        if py_in_dist.exists():
            py_in_dist.unlink()
            logging.info(f"Removed source: {rel_py}")

        # Remove intermediate .c file if present
        c_in_dist = dist_dir / parent / f"{stem}.c"
        if c_in_dist.exists():
            c_in_dist.unlink()


def calculate_file_sha256(path: Path) -> str:
    """Return the SHA-256 checksum for a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_distribution_manifest(
    dist_dir: Path,
    *,
    project_root: Path,
    version: str,
    system: str,
    machine: str,
    artifact_type: str,
) -> Dict[str, Any]:
    """Build an auditable manifest for a prepared distribution directory."""
    files = []
    for path in sorted(dist_dir.rglob("*")):
        if not path.is_file() or path.name == "DISTRIBUTION-MANIFEST.json":
            continue
        rel_path = path.relative_to(dist_dir).as_posix()
        files.append(
            {
                "path": rel_path,
                "size_bytes": path.stat().st_size,
                "sha256": calculate_file_sha256(path),
            }
        )

    native_driver_dir = dist_dir / "native_drivers"
    return {
        "name": "dblift",
        "version": version,
        "platform": system,
        "architecture": machine,
        "artifact_type": artifact_type,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "build_python": platform.python_version(),
        "source_commit": os.environ.get("GITHUB_SHA"),
        "native_drivers": (
            sorted(path.name for path in native_driver_dir.iterdir())
            if native_driver_dir.exists()
            else []
        ),
        "files": files,
        "file_count": len(files),
        "release_workflow": ".github/workflows/build.yaml",
    }


def write_distribution_manifest(
    dist_dir: Path,
    *,
    project_root: Path,
    version: str,
    system: str,
    machine: str,
    artifact_type: str,
) -> Path:
    """Write DISTRIBUTION-MANIFEST.json into a prepared distribution directory."""
    manifest = build_distribution_manifest(
        dist_dir,
        project_root=project_root,
        version=version,
        system=system,
        machine=machine,
        artifact_type=artifact_type,
    )
    manifest_path = dist_dir / "DISTRIBUTION-MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest_path


def create_distribution(system: str, machine: str, output_dir: Path) -> None:
    """Create a distribution for the specified platform."""
    # Get project root directory
    project_root = Path(__file__).parent.parent

    # Compile Cython modules before copying (build_ext --inplace puts .so next to .py)
    cython_ok = compile_cython_modules(project_root)

    # Get version from package
    version = get_version(project_root)

    # Create distribution directory
    dist_name = f"dblift-{version}-{system}-{machine}"
    dist_dir = output_dir / dist_name
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir()

    # Copy Python package
    logging.info("Copying Python package...")
    package_source_dir = project_root
    # Copy packages directly to dist root (not in subdirectory) so launcher can import them
    # The launcher script expects cli, core, db, etc. at the same level

    # Files/directories to include
    required_packages = [
        "api",
        "config",
        "core",
        "db",
        "cli",
        "__init__.py",
    ]

    # Files/directories to always exclude
    exclude_patterns = [
        "__pycache__",
        "*.pyc",
        ".git*",
        "*.egg-info",
        "dist",
        "build",
        "venv",
        "htmlcov",
        "tests",
        "test_*.py",
        "*_test.py",
        "*.coverage",
        "coverage.*",
        "*.log",
        "logs/*",
        "reports/*",
        "*.tmp",
        "*.bak",
        ".pytest_cache",
        "*.ipynb",
        ".DS_Store",
        "conftest.py",  # Pytest configuration
        ".pytest_cache",  # Pytest cache
        ".mypy_cache",  # MyPy cache
        ".ruff_cache",  # Ruff cache
    ]

    # Copy only the required files directly to dist_dir (root level)
    for item_name in required_packages:
        item = package_source_dir / item_name
        if not item.exists():
            logging.warning(f"Required item not found: {item}")
            continue

        if item.is_dir():
            target = dist_dir / item.name
            logging.info(f"Copying directory {item} to {target}")
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(*exclude_patterns))
            # Verify the copy was successful
            if target.exists():
                file_count = sum(1 for path in target.rglob("*") if path.is_file())
                logging.info(f"Successfully copied {item_name}: {file_count} files")
            else:
                logging.error(f"Failed to copy {item_name}: target directory does not exist")
        else:
            target = dist_dir / item.name
            logging.info(f"Copying file {item} to {target}")
            shutil.copy2(item, target)
            if target.exists():
                logging.info(f"Successfully copied {item_name}")
            else:
                logging.error(f"Failed to copy {item_name}: target file does not exist")

    # Copy essential project files
    for file in ["README.md", "LICENSE"]:
        if (package_source_dir / file).exists():
            shutil.copy2(package_source_dir / file, dist_dir / file)

    # Replace compiled .py sources with native extensions in the distribution
    if cython_ok:
        _strip_compiled_sources(dist_dir, project_root)

    # Create launcher script
    if system == "win32":
        create_windows_launcher(dist_dir)
    else:
        # Instead of the basic Unix launcher, copy our enhanced wrapper script
        # Check if the wrapper script exists
        wrapper_script = project_root / "dblift"
        if wrapper_script.exists():
            # Copy the wrapper script to the distribution
            shutil.copy2(wrapper_script, dist_dir / "dblift")
            # Make it executable
            os.chmod(dist_dir / "dblift", 0o755)
            logging.info("Added enhanced help wrapper script to distribution")
        else:
            # Fall back to the basic launcher if wrapper doesn't exist
            create_unix_launcher(dist_dir)
            logging.warning("Enhanced help wrapper script not found, using basic launcher")

    write_distribution_manifest(
        dist_dir,
        project_root=project_root,
        version=version,
        system=system,
        machine=machine,
        artifact_type="archive",
    )

    # Create archive
    # First, verify what's in the distribution directory
    logging.info("Contents of distribution directory before archiving:")
    for item in sorted(dist_dir.rglob("*")):
        if item.is_file():
            logging.info(f"  File: {item.relative_to(dist_dir)}")
        elif item.is_dir():
            logging.info(f"  Directory: {item.relative_to(dist_dir)}/")

    if system == "win32":
        archive_name = f"{dist_name}.zip"
        logging.info(f"Creating ZIP archive: {archive_name}")
        with zipfile.ZipFile(output_dir / archive_name, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Walk through all files and directories to ensure everything is included
            for root, dirs, files in os.walk(dist_dir):
                # Add all files
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(dist_dir)
                    zipf.write(file_path, arcname)
                    logging.debug(f"Added to ZIP: {arcname}")
    else:
        archive_name = f"{dist_name}.tar.gz"
        logging.info(f"Creating TAR archive: {archive_name}")
        with tarfile.open(output_dir / archive_name, "w:gz") as tarf:
            # Walk through all files and add them with proper arcname
            # This ensures all files and directory structure are preserved
            for root, dirs, files in os.walk(dist_dir):
                for file in files:
                    file_path = Path(root) / file
                    # Create arcname with dist_name as prefix to match ZIP format
                    relative_path = file_path.relative_to(dist_dir)
                    arcname = str(Path(dist_name) / relative_path)
                    tarf.add(file_path, arcname=arcname)
                    logging.debug(f"Added to TAR: {arcname}")
            logging.info(f"Created TAR archive with all distribution files")

    # Clean up distribution directory
    shutil.rmtree(dist_dir)

    logging.info(f"Created distribution archive: {output_dir / archive_name}")


def create_windows_launcher(dist_dir: Path) -> None:
    """Create Windows batch launcher script."""
    launcher = dist_dir / "dblift.bat"
    with open(launcher, "w") as f:
        f.write("""@echo off
python -m dblift %*
""")


def create_unix_launcher(dist_dir: Path) -> None:
    """Create Unix shell launcher script."""
    # Create launcher in the distribution root directory
    launcher = dist_dir / "dblift"

    # Check if the path exists and is a directory
    if launcher.exists() and launcher.is_dir():
        # If it's a directory, create the launcher in that directory
        launcher = launcher / "dblift_launcher.sh"

    with open(launcher, "w") as f:
        f.write("""#!/bin/bash
python3 -m dblift "$@"
""")
    # Make launcher executable
    os.chmod(launcher, 0o755)


def check_pyinstaller():
    """Check if PyInstaller is available or install it."""
    if importlib.util.find_spec("PyInstaller") is None:
        logging.info("PyInstaller not found. Installing PyInstaller...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            logging.info("PyInstaller installed successfully.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to install PyInstaller: {e}")
            return False
    return True


def create_executable(project_root: Path, dist_dir: Path, system: str) -> bool:
    """Create a standalone executable using PyInstaller."""
    logging.info("Creating standalone executable with PyInstaller...")

    # Ensure PyInstaller is available
    if not check_pyinstaller():
        return False

    # Create the specfile content with custom bootstrap code
    # This will help with finding bundled Python resources
    spec_path = project_root / "Dblift.spec"

    # Create a bootstrap script that will be added to the executable
    bootstrap_script = project_root / "bootstrap.py"
    with open(bootstrap_script, "w") as f:
        f.write('''
import os
import sys
from pathlib import Path

def setup_bundled_resources():
    """Set up bundled Python resources before the main application."""
    # Get the path to the executable's directory
    if getattr(sys, 'frozen', False):
        # Running as a bundle (PyInstaller)
        base_dir = Path(sys._MEIPASS)
        
        # Add the base directory to the Python path
        # This ensures our modules are properly found
        if str(base_dir) not in sys.path:
            sys.path.insert(0, str(base_dir))
    else:
        # Running as a script
        base_dir = Path(__file__).parent
    
    os.environ['Dblift_BUNDLED_DIR'] = str(base_dir)
    return base_dir

# Run setup when this module is imported
setup_bundled_resources()
''')

    # PyInstaller options
    options = [
        "--name=Dblift",
        "--onefile",  # Create a single executable file
        "--clean",  # Clean PyInstaller cache
        "--noconfirm",  # Replace output directory without asking
        f"--distpath={dist_dir}",  # Output directory
        f"--specpath={project_root}",  # Spec file location
    ]

    # Continue with other options
    options.extend(
        [
            "--hidden-import=bootstrap",  # Import our bootstrap script
            "--hidden-import=cli.main",  # Ensure CLI entry point is included
            # Collect all db submodules - needed for:
            # - Dynamic plugin loading via importlib (db.plugins.*)
            # - Database-specific introspectors (db.plugins.<dialect>.introspection.*)
            # - All other db submodules that may be loaded dynamically
            "--collect-submodules=db",  # Include all db submodules
            # Collect the CLI + dynamically-loaded command/plugin packages so the
            # frozen binary exposes the full command surface (incl. the PRO/
            # ENTERPRISE `data`, `diff`, `plan`, `preflight`, … commands, which
            # are registered via runtime plugin discovery PyInstaller can't trace).
            "--collect-submodules=cli",
            "--collect-submodules=core",
            "--collect-submodules=config",
            "--collect-submodules=api",
            # Commands/handlers/providers are discovered at runtime via
            # importlib.metadata entry points (`dblift.commands`, …). A frozen
            # binary only sees them if the distribution *metadata* is bundled —
            # without this the standalone binary silently loses every PRO/
            # ENTERPRISE command (data/diff/plan/preflight/…) and provider.
            "--copy-metadata=dblift",
            "--copy-metadata=dblift-pro",
            "--copy-metadata=dblift-enterprise",
            # Database drivers are imported lazily per dialect, so PyInstaller's
            # static analysis misses the ones not reached from the entry import.
            # A standalone binary cannot pip-install drivers, so bundle every
            # supported one explicitly (PG/MySQL/SQLite are usually auto-found;
            # SQL Server and Oracle were not). `cryptography` is required by
            # oracledb's thin mode.
            "--hidden-import=pymssql",
            "--hidden-import=pymysql",
            "--hidden-import=psycopg2",
            "--hidden-import=psycopg",
            "--collect-all=oracledb",
            "--collect-all=cryptography",
            "--collect-all=azure",
            "--exclude-module=tests",  # Exclude tests from distribution
            "--exclude-module=pytest",  # Exclude pytest
            "--exclude-module=conftest",  # Exclude pytest configuration
        ]
    )

    # Add platform-specific options
    if system == "win32":
        options.append("--console")  # Console application on Windows
        exe_name = "Dblift.exe"
    else:
        options.append("--console")  # Console application on Unix
        exe_name = "Dblift"

    # Add bootstrap code to the entry point
    temp_entry = project_root / "temp_entry.py"
    with open(temp_entry, "w") as f:
        f.write(
            "import bootstrap  # noqa: F401 - sets up bundled resource paths\n"
            "from cli.main import main\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        )

    # Build the PyInstaller command
    cmd = [sys.executable, "-m", "PyInstaller"] + options + [str(temp_entry)]

    try:
        logging.info(f"Running command: {' '.join(cmd)}")
        subprocess.check_call(cmd, cwd=str(project_root))
        logging.info(f"Created executable: {dist_dir / exe_name}")

        # Clean up temporary files
        bootstrap_script.unlink(missing_ok=True)
        temp_entry.unlink(missing_ok=True)
        spec_path.unlink(missing_ok=True)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to create executable: {e}")

        # Clean up temporary files even on failure
        bootstrap_script.unlink(missing_ok=True)
        temp_entry.unlink(missing_ok=True)
        spec_path.unlink(missing_ok=True)
        return False


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Build Dblift distribution packages")
    parser.add_argument("--platform", help="Override target platform (darwin, linux, win32)")
    parser.add_argument("--arch", help="Override target architecture (x86_64, aarch64)")
    parser.add_argument(
        "--exe", action="store_true", help="Create standalone executable with PyInstaller"
    )
    parser.add_argument("--no-archive", action="store_true", help="Skip creating archive")

    return parser.parse_args()


def main():
    """Build platform-specific distributions."""
    args = parse_args()

    # Get project root directory
    project_root = Path(__file__).parent.parent
    output_dir = project_root / "dist"
    output_dir.mkdir(exist_ok=True)

    # Get current platform info or use override
    system = args.platform or get_platform_info()[0]
    machine = normalize_cli_arch(args.arch) if args.arch else get_platform_info()[1]

    logging.info(f"Building distribution for {system}-{machine}")

    if args.exe:
        # Create a standalone executable
        logging.info("Building standalone executable...")
        success = create_executable(project_root, output_dir, system)
        if success:
            logging.info("Standalone executable created successfully.")

            # If we're not creating an archive, we're done
            if args.no_archive:
                logging.info("\nBuild completed successfully!")
                return

            # Create archive with the executable and supporting files
            version = get_version(project_root)
            dist_name = f"dblift-{version}-{system}-{machine}"
            dist_dir = output_dir / dist_name

            if dist_dir.exists():
                shutil.rmtree(dist_dir)
            dist_dir.mkdir()

            # Copy the executable
            if system == "win32":
                exe_name = "Dblift.exe"
            else:
                exe_name = "Dblift"

            if (output_dir / exe_name).exists():
                shutil.copy2(output_dir / exe_name, dist_dir / exe_name)
                if system != "win32":
                    os.chmod(dist_dir / exe_name, 0o755)

                # For Windows, also create a batch file that launches the executable
                if system == "win32":
                    with open(dist_dir / "Dblift.bat", "w") as f:
                        f.write("""@echo off
REM Launcher for Dblift
"{exe_name}" %*
""")
                # For Unix, use our enhanced wrapper script or create a basic one
                else:
                    wrapper_script = project_root / "dblift"
                    if wrapper_script.exists():
                        # Copy and adapt our enhanced wrapper script
                        with open(dist_dir / "Dblift.sh", "w") as f:
                            # Read the original wrapper
                            with open(wrapper_script, "r") as original:
                                wrapper_content = original.read()

                            # Modify the wrapper to use the executable directly
                            modified_content = wrapper_content.replace(
                                'exec "$PYTHON" -c "import sys; sys.path.insert(0, \'$SCRIPT_DIR\'); from cli.main import main; main()" "$@"',
                                'exec "$SCRIPT_DIR/{exe_name}" "$@"',
                            )
                            f.write(modified_content)
                        os.chmod(dist_dir / "Dblift.sh", 0o755)
                    else:
                        # Create a basic wrapper if enhanced one doesn't exist
                        with open(dist_dir / "Dblift.sh", "w") as f:
                            f.write("""#!/bin/bash
# Launcher for Dblift
DIR="$( cd "$( dirname "${{BASH_SOURCE[0]}}" )" && pwd )"
"$DIR/{exe_name}" "$@"
""")
                        os.chmod(dist_dir / "Dblift.sh", 0o755)

            # Copy README and LICENSE
            for file in ["README.md", "LICENSE"]:
                if (project_root / file).exists():
                    shutil.copy2(project_root / file, dist_dir / file)

            write_distribution_manifest(
                dist_dir,
                project_root=project_root,
                version=version,
                system=system,
                machine=machine,
                artifact_type="executable",
            )

            # Create archive with -executable suffix to avoid overwriting regular distribution
            if system == "win32":
                archive_name = f"{dist_name}-executable.zip"
                logging.info(f"Creating ZIP archive: {archive_name}")
                with zipfile.ZipFile(output_dir / archive_name, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for root, _, files in os.walk(dist_dir):
                        for file in files:
                            file_path = Path(root) / file
                            arcname = file_path.relative_to(dist_dir)
                            zipf.write(file_path, arcname)
            else:
                archive_name = f"{dist_name}-executable.tar.gz"
                logging.info(f"Creating TAR archive: {archive_name}")
                with tarfile.open(output_dir / archive_name, "w:gz") as tarf:
                    # Explicitly add all files to ensure everything is included
                    for root, _, files in os.walk(dist_dir):
                        for file in files:
                            file_path = Path(root) / file
                            # Create arcname with dist_name as prefix to match ZIP format
                            relative_path = file_path.relative_to(dist_dir)
                            arcname = str(Path(dist_name) / relative_path)
                            tarf.add(file_path, arcname=arcname)

            # Clean up distribution directory
            shutil.rmtree(dist_dir)

            logging.info(f"Created distribution archive: {output_dir / archive_name}")
        else:
            logging.error("Failed to create standalone executable.")
    else:
        # Create regular distribution package
        create_distribution(system, machine, output_dir)

    logging.info("\nBuild completed successfully!")


if __name__ == "__main__":
    main()
