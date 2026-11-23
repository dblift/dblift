"""Freeze the exact supplied DBLift release wheel into a native CLI archive."""

import argparse
import gzip
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
from email import message_from_bytes
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

TARGETS = {
    "linux-x86_64": ("Linux", "x86_64", ".tar.gz"),
    "macos-arm64": ("Darwin", "arm64", ".tar.gz"),
    "windows-x86_64": ("Windows", "x86_64", ".zip"),
}
DEBIAN_LIBRARIES = (
    "libbz2-1.0",
    "libffi8",
    "liblzma5",
    "libsqlite3-0",
    "libssl3",
    "libuuid1",
    "zlib1g",
)
SCRIPT_DIR = Path(__file__).resolve().parent


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def read_release_wheel(wheel_dir):
    wheels = sorted(wheel_dir.glob("*.whl"))
    if len(wheels) != 1 or not wheels[0].name.startswith("dblift-"):
        raise ValueError(f"Expected exactly one DBLift release wheel in {wheel_dir}")
    wheel = wheels[0]
    with ZipFile(wheel) as package:
        metadata_files = [
            name
            for name in package.namelist()
            if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError(f"Invalid release wheel metadata: {wheel.name}")
        metadata = message_from_bytes(package.read(metadata_files[0]))
        version = metadata["Version"]
        if metadata["Name"] != "dblift" or not version:
            raise ValueError(f"Invalid DBLift release wheel identity: {wheel.name}")
        if wheel.name != f"dblift-{version}-py3-none-any.whl":
            raise ValueError(f"Release wheel name and metadata do not match: {wheel.name}")
        license_path = metadata_files[0].replace("/METADATA", "/licenses/LICENSE")
        license_text = package.read(license_path)
    return wheel, version, license_text


def check_build_host(target):
    system, machine, _ = TARGETS[target]
    host = {"amd64": "x86_64", "aarch64": "arm64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    if (platform.system(), host) != (system, machine):
        raise ValueError(
            f"{target} must be built on {system} {machine}; got {platform.system()} {host}"
        )
    if sys.version_info[:2] != (3, 11):
        raise ValueError("Standalone builds require Python 3.11")
    if (
        target == "linux-x86_64"
        and "VERSION_CODENAME=bookworm"
        not in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    ):
        raise ValueError("Linux standalone builds require Debian 12 (Bookworm)")


def build_runtime(workspace, wheel, wheel_sha, target):
    runtime = venv.EnvBuilder(with_pip=True)
    runtime.create(workspace / "env")
    python = Path(runtime.ensure_directories(workspace / "env").env_exe)
    lock = (SCRIPT_DIR / f"standalone-{target}.requirements.txt").read_text(encoding="utf-8")
    requirements = workspace / "requirements.txt"
    requirements.write_text(
        f"{lock.rstrip()}\ndblift[cli,postgresql] @ {wheel.as_uri()} --hash=sha256:{wheel_sha}\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            python,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--require-hashes",
            "-r",
            requirements,
        ],
        cwd=workspace,
        check=True,
    )
    subprocess.run([python, "-I", "-m", "pip", "check"], cwd=workspace, check=True)
    return python


def freeze(python, workspace, target):
    entry = workspace / "cli_entry.py"
    entry.write_text(
        'from dblift.cli.main import main\n\nif __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    options = [
        "--clean",
        "--noconfirm",
        "--onedir",
        "--name=dblift",
        "--copy-metadata=dblift",
        "--copy-metadata=psycopg",
        "--copy-metadata=psycopg-binary",
        "--collect-data=dblift",
        "--collect-submodules=dblift.db",
        "--collect-submodules=dblift.cli",
        "--collect-submodules=sqlglot.dialects",
        "--collect-all=psycopg",
        "--collect-all=psycopg_binary",
    ]
    if target == "macos-arm64":
        options.append("--target-architecture=arm64")
    subprocess.run([python, "-I", "-m", "PyInstaller", *options, entry], cwd=workspace, check=True)
    return workspace / "dist" / "dblift"


# Run under the build virtual environment so notices come from its wheel files.
COLLECT_WHEEL_NOTICES = """
import shutil
import sys
import sysconfig
from importlib.metadata import distributions
from pathlib import Path

notices = Path(sys.argv[1])
python_license = next(
    (candidate for candidate in (
        Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE.txt",
    ) if candidate.is_file()),
    None,
)
if python_license is None:
    raise SystemExit("The CPython installation has no LICENSE.txt")
shutil.copyfile(python_license, notices / "Python-LICENSE.txt")
for dist in distributions():
    name = dist.metadata["Name"]
    for entry in dist.files or ():
        if entry.is_absolute() or ".." in entry.parts:
            continue
        is_notice = entry.name.startswith(("LICENSE", "COPYING", "NOTICE"))
        if "licenses" in entry.parts[1:-1] or is_notice:
            source = dist.locate_file(entry)
            if source.is_file() and source.suffix not in {".py", ".pyc"}:
                target = notices / name / entry
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
"""


def write_notices(python, bundle, target):
    notices = bundle / "licenses"
    notices.mkdir()
    subprocess.run([python, "-I", "-c", COLLECT_WHEEL_NOTICES, notices], cwd=bundle, check=True)
    if target == "linux-x86_64":
        debian = notices / "Debian"
        debian.mkdir()
        for package in DEBIAN_LIBRARIES:
            shutil.copyfile(
                Path("/usr/share/doc") / package / "copyright", debian / f"{package}.txt"
            )
        packages = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${binary:Package} ${Version}\n", *DEBIAN_LIBRARIES],
            text=True,
        )
        (debian / "packages.txt").write_text(packages, encoding="utf-8")

    native_files = sorted(
        p
        for p in (bundle / "_internal").rglob("*")
        if p.is_file()
        and not p.is_symlink()
        and (
            ".so" in p.suffixes
            or p.suffix.lower() in {".dll", ".dylib", ".pyd"}
            or any(
                Path(part).suffix == ".framework" and Path(part).stem == p.name
                for part in p.relative_to(bundle).parts[:-1]
            )
        )
    )
    inventory = "".join(f"{sha256(p)}  {p.relative_to(bundle).as_posix()}\n" for p in native_files)
    (notices / "native-library-sha256.txt").write_text(inventory, encoding="utf-8")


def stable_tar_entry(entry):
    entry.uid = entry.gid = entry.mtime = 0
    entry.uname = entry.gname = ""
    return entry


def make_archive(bundle, archive):
    if archive.suffix == ".zip":
        with ZipFile(archive, "w", compression=ZIP_DEFLATED, strict_timestamps=False) as zip_file:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    zip_file.write(path, path.relative_to(bundle))
        return
    with (
        archive.open("wb") as file,
        gzip.GzipFile(filename="", mode="wb", fileobj=file, mtime=0) as gz_file,
    ):
        with tarfile.open(fileobj=gz_file, mode="w") as tar:
            for path in sorted(bundle.iterdir()):
                tar.add(path, arcname=path.name, filter=stable_tar_entry)


def build(wheel_dir, output_dir, target):
    wheel, version, license_text = read_release_wheel(wheel_dir)
    check_build_host(target)
    wheel_sha = sha256(wheel)
    executable_name = "dblift.exe" if target == "windows-x86_64" else "dblift"
    archive_name = f"dblift-{version}-{target}{TARGETS[target][2]}"
    with tempfile.TemporaryDirectory(prefix="dblift-standalone-") as folder:
        workspace = Path(folder)
        python = build_runtime(workspace, wheel, wheel_sha, target)
        bundle = freeze(python, workspace, target)
        executable = bundle / executable_name
        version_output = subprocess.check_output([executable, "--version"], text=True).strip()
        if version_output != f"dblift version {version}":
            raise ValueError(f"Executable version differs from its wheel: {version_output}")
        print(version_output, flush=True)
        (bundle / "LICENSE").write_bytes(license_text)
        write_notices(python, bundle, target)
        (bundle / "build-identity.json").write_text(
            json.dumps(
                {
                    "version": version,
                    "target": target,
                    "wheel": wheel.name,
                    "wheel_sha256": wheel_sha,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (bundle / "README.txt").write_text(
            f"DBLift {version} for {target}\n"
            f"Extract the archive and keep {executable_name} and _internal together.\n"
            f"Run ./{executable_name} --version. SQLite and PostgreSQL drivers are included.\n"
            "See licenses/ for runtime notices and the native library inventory.\n"
            "https://docs.dblift.com/getting-started/\n",
            encoding="utf-8",
        )
        archive = workspace / archive_name
        make_archive(bundle, archive)
        archive_sha = sha256(archive)
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(archive, output_dir / archive_name)
        (output_dir / f"{archive_name}.sha256").write_text(
            f"{archive_sha}  {archive_name}\n", encoding="utf-8"
        )
        print(f"{archive_sha}  {archive_name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", choices=TARGETS, required=True)
    args = parser.parse_args()
    try:
        build(args.wheel_dir.resolve(), args.output_dir.resolve(), args.target)
    except (BadZipFile, KeyError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
