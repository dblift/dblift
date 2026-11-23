#!/usr/bin/env bash
# Run from x86-64 Linux without Python. Use a disposable database for the override.
set -euo pipefail

archive="${1:?usage: standalone-linux.sh ARCHIVE VERSION}"
[[ "$archive" = /* ]] || archive="$PWD/$archive"
version="${2:?expected version}"
if [[ ! -f "$archive" ]]; then
    echo "Standalone release archive is missing: $archive" >&2
    exit 1
fi

workspace="$(mktemp -d)"
trap 'rm -rf "$workspace"' EXIT
mkdir "$workspace/extract" "$workspace/project"
tar -xzf "$archive" -C "$workspace/extract"
cli="$workspace/extract/dblift"
test -x "$cli"
test -s "$workspace/extract/LICENSE"
test -s "$workspace/extract/licenses/Python-LICENSE.txt"

cd "$workspace/project"
export HOME="$workspace/home"
mkdir "$HOME" migrations
export DBLIFT_DB_URL="${DBLIFT_STANDALONE_SMOKE_DB_URL:-sqlite:///smoke.db}"
printf '%s\n' 'CREATE TABLE standalone_example (id INTEGER PRIMARY KEY);' > migrations/V1__create_example.sql
printf '%s\n' 'DROP TABLE standalone_example;' > migrations/U1__drop_example.sql

"$cli" --version | grep -F "$version"
"$cli" db check-connection
"$cli" validate-sql --files migrations/V1__create_example.sql --dialect "${DBLIFT_STANDALONE_SMOKE_DIALECT:-sqlite}"
"$cli" migrate --dry-run --show-sql 2>&1 | tee preview.txt
grep -Fi 'CREATE TABLE standalone_example' preview.txt
"$cli" migrate
"$cli" info
"$cli" validate
"$cli" undo
