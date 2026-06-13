#!/bin/bash
# Setup script for remote MySQL testing.
#
# Reads connection parameters from the shell environment. Set them in a
# local, gitignored file (e.g. ~/.dblift-mysql.env) and `source` it
# before this script, or export them directly.
#
# Required:
#   DBLIFT_MYSQL_PASSWORD
#
# Optional (defaults shown):
#   DBLIFT_MYSQL_HOST=127.0.0.1
#   DBLIFT_MYSQL_PORT=3306
#   DBLIFT_MYSQL_USERNAME=root
#   DBLIFT_MYSQL_DATABASE=MYSQL_DATABASE
#
# Usage:
#   source ~/.dblift-mysql.env     # your private config
#   source scripts/setup_mysql_remote.sh
#   python3 -m pytest tests/integration/validation/test_mysql*.py -v

set -u

# Required: fail loudly if not set (no default, no silent fallback).
: "${DBLIFT_MYSQL_PASSWORD:?DBLIFT_MYSQL_PASSWORD is required — set it in a local env file (not committed)}"

# Non-sensitive defaults. Override by exporting before sourcing.
export DBLIFT_MYSQL_HOST="${DBLIFT_MYSQL_HOST:-127.0.0.1}"
export DBLIFT_MYSQL_PORT="${DBLIFT_MYSQL_PORT:-3306}"
export DBLIFT_MYSQL_USERNAME="${DBLIFT_MYSQL_USERNAME:-root}"
export DBLIFT_MYSQL_DATABASE="${DBLIFT_MYSQL_DATABASE:-MYSQL_DATABASE}"
export DBLIFT_MYSQL_PASSWORD

echo "=========================================="
echo "MySQL Remote Configuration"
echo "=========================================="
echo "  Host: $DBLIFT_MYSQL_HOST"
echo "  Port: $DBLIFT_MYSQL_PORT"
echo "  Username: $DBLIFT_MYSQL_USERNAME"
echo "  Database: $DBLIFT_MYSQL_DATABASE"
echo ""
echo "Environment variables have been set."
echo ""
echo "IMPORTANT: Before running tests, ensure:"
echo "  1. MySQL is accessible from this machine"
echo "  2. Firewall allows connections on port 3306"
echo "  3. MySQL user has remote access permissions"
echo ""
echo "Test the connection first:"
echo "  python3 scripts/test_mysql_connection.py"
echo ""
echo "Then run MySQL tests:"
echo "  python3 -m pytest tests/integration/validation/test_mysql*.py -v"
echo ""
echo "See scripts/MYSQL_REMOTE_SETUP.md for troubleshooting"
echo ""
echo "To unset these variables:"
echo "  unset DBLIFT_MYSQL_HOST DBLIFT_MYSQL_PORT DBLIFT_MYSQL_USERNAME DBLIFT_MYSQL_PASSWORD DBLIFT_MYSQL_DATABASE"
echo "=========================================="

