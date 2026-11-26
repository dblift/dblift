#!/usr/bin/env bash
# Run from x86-64 Linux without Python. Use a disposable database for the override.
set -euo pipefail

input="${1:?usage: standalone-linux.sh ARCHIVE|--installed VERSION}"
version="${2:?expected version}"
workspace="$(mktemp -d)"
trap 'rm -rf "$workspace"' EXIT
mkdir "$workspace/project"
if [[ "$input" == --installed ]]; then
    cli="$(command -v dblift)"
    test "$cli" = /usr/bin/dblift
    bundle=/usr/lib/dblift
else
    bundle="$workspace/extract"
    mkdir "$bundle"
    tar -xzf "$input" -C "$bundle"
    cli="$bundle/dblift"
fi
test -x "$cli"
test -s "$bundle/LICENSE"
test -s "$bundle/licenses/Python-LICENSE.txt"

cd "$workspace/project"
export HOME="$workspace/home"
mkdir "$HOME" migrations
export DBLIFT_DB_URL="${DBLIFT_STANDALONE_SMOKE_DB_URL:-sqlite:///smoke.db}"
printf '%s\n' 'CREATE TABLE standalone_example (id INTEGER PRIMARY KEY);' > migrations/V1__create_example.sql
printf '%s\n' 'DROP TABLE standalone_example;' > migrations/U1__drop_example.sql

"$cli" --version | grep -Fx "dblift version $version"
"$cli" db check-connection
"$cli" validate-sql --files migrations/V1__create_example.sql --dialect "${DBLIFT_STANDALONE_SMOKE_DIALECT:-sqlite}"
"$cli" migrate --dry-run --show-sql 2>&1 | tee preview.txt
grep -Fi 'CREATE TABLE standalone_example' preview.txt
"$cli" migrate
"$cli" info
"$cli" validate
"$cli" undo
