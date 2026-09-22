#!/usr/bin/env bash
# Upgrade-path check: a database migrated by an already-published dblift must
# keep working with the dblift built from this tree, and the published version
# must still read the history afterwards (so a rollback of the tool is safe).
#
# Usage: scripts/check_upgrade_path.sh '<pip requirement for the old version>'
#   scripts/check_upgrade_path.sh 'dblift<4.6.1'
#   scripts/check_upgrade_path.sh 'dblift==4.0.0'
# NEW_DBLIFT may point at the dblift executable under test (default: dblift on PATH).
set -euo pipefail

OLD_REQUIREMENT="$1"
NEW_DBLIFT="${NEW_DBLIFT:-dblift}"
PYTHON="${PYTHON:-python3}"
export DBLIFT_DISABLE_CLI_EXTENSIONS=1

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"
mkdir migrations
printf 'CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);\n' > migrations/V1__create_users.sql

"$PYTHON" -m venv old
old/bin/pip install --quiet "$OLD_REQUIREMENT"
ARGS=(--db-url sqlite:///upgrade.db --scripts migrations)

echo "== old ($OLD_REQUIREMENT): migrate V1"
old/bin/dblift "${ARGS[@]}" migrate > /dev/null

echo "== new: validate the history written by the old version"
"$NEW_DBLIFT" "${ARGS[@]}" validate > /dev/null

echo "== new: migrate V2 on top"
printf 'ALTER TABLE users ADD COLUMN email TEXT;\n' > migrations/V2__add_email.sql
"$NEW_DBLIFT" "${ARGS[@]}" migrate > /dev/null

summarize='import json,sys; print([(m["version"], m["status"]) for m in json.load(sys.stdin)["migrations"]])'
EXPECTED="[('1', 'SUCCESS'), ('2', 'SUCCESS')]"

NEW_VIEW="$("$NEW_DBLIFT" "${ARGS[@]}" info --format json | "$PYTHON" -c "$summarize")"
OLD_VIEW="$(old/bin/dblift "${ARGS[@]}" info --format json | "$PYTHON" -c "$summarize")"
echo "new sees: $NEW_VIEW"
echo "old sees: $OLD_VIEW"
[ "$NEW_VIEW" = "$EXPECTED" ] || { echo "FAIL: new version misreads the history"; exit 1; }
[ "$OLD_VIEW" = "$EXPECTED" ] || { echo "FAIL: old version cannot read history written by new"; exit 1; }
echo "OK: upgrade path $OLD_REQUIREMENT -> current"
