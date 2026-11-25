# dblift OSS Scripts

This directory intentionally contains only the scripts used by the public
repository workflow.

## Local Quality Gate

```bash
./scripts/check_code_quality.sh
```

This runs the same formatting, import ordering, flake8 (line length and import
position included), mypy, AST-pattern and public-docstring checks used by CI,
plus the structural-debt ratchet and the per-function complexity ceiling
(`.complexity-ceiling.json`: existing hotspots are listed at their exact value
and may only shrink). All but the last two scan every file under `dblift/` at
zero tolerance. Run it from the repository root: a script whose
default root is missing exits non-zero instead of passing on an empty scan.

## Cutting a Release

```bash
python scripts/create_release.py --dry-run X.Y.Z
python scripts/create_release.py --push X.Y.Z
```

Rolls `## [Unreleased]` in `CHANGELOG.md` into a dated `## [X.Y.Z]` section,
bumps the version in `pyproject.toml`/`__init__.py`, commits, and tags
`vX.Y.Z`.

## Checking the Upgrade Path

```bash
scripts/check_upgrade_path.sh '<pip requirement for the old version>'
```

`check_upgrade_path.sh` — migrates a SQLite database with a published
release, continues with this tree, and checks the published release still
reads the history; run by `.github/workflows/upgrade-path.yml`.

## Building the standalone CLI

The standalone packages include the CLI, its Python runtime, SQLite and the
PostgreSQL driver. PyInstaller runs natively on the selected architecture with
CPython 3.11 and the dependency wheels pinned by SHA-256 in
`standalone-<target>.requirements.txt`.

| Target | Builder | Archive |
| --- | --- | --- |
| `linux-x86_64` | Debian 12 x86_64 with binutils and dpkg-deb | `dblift-<version>-linux-x86_64.tar.gz`, `dblift_<debian-version>_amd64.deb` |
| `macos-arm64` | Apple Silicon macOS | `dblift-<version>-macos-arm64.tar.gz` |
| `windows-x86_64` | Windows x64 | `dblift-<version>-windows-x86_64.zip` |

Put the one DBLift wheel to package in `wheel/`. The builder checks its name
and metadata, hashes the wheel, and installs it with the pinned dependencies
in a fresh virtual environment. Linux build example from the repository root:

```bash
mkdir -p output
docker run --rm --platform linux/amd64 \
  -v "$PWD:/src:ro" -v "$PWD/wheel:/wheel:ro" -v "$PWD/output:/out" \
  python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39 \
  bash -euc '
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends binutils
    python /src/scripts/build_standalone.py --wheel-dir /wheel --output-dir /out --target linux-x86_64
    python /src/tests/smoke/smoke_standalone.py --wheel-dir /wheel --archive-dir /out --target linux-x86_64
  '
```

On macOS or Windows, run the same two Python scripts with the corresponding
target and local directories. The smoke runner checks the archive SHA-256,
native library hashes and wheel identity before running the extracted CLI
against SQLite in a fresh project directory. The smoke test checks that the
bundled PostgreSQL binary driver attempts a connection to an unused loopback
port. It expects a refusal, and on Windows also accepts psycopg's connection
timeout. To exercise the migration against a disposable PostgreSQL database,
repeat with
`DBLIFT_STANDALONE_SMOKE_DB_URL` and
`DBLIFT_STANDALONE_SMOKE_DIALECT=postgresql`.

The Linux archive also has a separate runtime check that runs without Python.
Use the archive name and version from the build:

```bash
docker run --rm --platform linux/amd64 --network none \
  -v "$PWD:/src:ro" -v "$PWD/output:/out:ro" \
  debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc \
  bash -euc '
    if command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1; then
      echo "The smoke runtime must not contain python or python3." >&2
      exit 1
    fi
    cd /out
    archive="$1"
    sha256sum -c "$archive.sha256"
    bash /src/tests/smoke/standalone-linux.sh "$archive" "$2"
  ' _ '<archive filename>' '<wheel version>'
```

The Linux build also writes a Debian package and its SHA-256. To rehearse a
local installation, run these commands as root in a fresh Debian 12 amd64
container from the output directory (example for 5.2.0):

```bash
sha256sum -c dblift_5.2.0-1_amd64.deb.sha256
apt-get install ./dblift_5.2.0-1_amd64.deb
dblift --version
```

APT installs the frozen payload under `/usr/lib/dblift` and exposes its CLI on
`PATH`. The workflow runs a SQLite migration and undo through that installed
command with networking disabled, then purges the package.

Keep the root executable and the accompanying `_internal` directory together.
The archive includes the release wheel's license, Python and dependency
notices, and the native library inventory. Use the Python package for engines
outside the SQLite/PostgreSQL standalone scope.

The GitHub workflow builds and tests each native archive on its runner and
records the filename, version and SHA-256 in the job summary. The release path
uses the published wheel for that version. A manual rehearsal builds a local
wheel for the selected Git ref. The workflow does not upload the standalone
archives to Actions artifacts or Releases. Those are public distribution
surfaces, and notices and corresponding-source obligations for the exact
bundled native libraries, including libraries vendored in the PostgreSQL
driver wheel, remain to be reviewed.

The macOS build uses an ad-hoc signature for local execution. Before release,
qualify Gatekeeper with a downloaded, appropriately signed and notarized
archive. Also verify the Windows executable's signing and SmartScreen
behavior from a downloaded archive before offering it publicly.
