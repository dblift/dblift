#!/bin/bash
# Setup script for remote DB2 connection
# Usage: source scripts/setup_db2_remote.sh

export DBLIFT_DB2_HOST="192.168.1.20"
export DBLIFT_DB2_PORT="50000"
export DBLIFT_DB2_USERNAME="db2inst1"
export DBLIFT_DB2_PASSWORD="testdb21234"
export DBLIFT_DB2_DATABASE="testdb"
export DBLIFT_DB2_SCHEMA="DB2INST1"  # Default schema for db2inst1 user

echo "DB2 remote connection configured:"
echo "  Host: $DBLIFT_DB2_HOST"
echo "  Port: $DBLIFT_DB2_PORT"
echo "  Database: $DBLIFT_DB2_DATABASE"
echo "  Schema: $DBLIFT_DB2_SCHEMA"
echo "  Username: $DBLIFT_DB2_USERNAME"

