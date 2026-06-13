#!/usr/bin/env python3
"""
Test script to verify DB2 remote connection.

Usage:
    source scripts/setup_db2_remote.sh
    python3 scripts/test_db2_connection.py
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DbliftConfig
from config.database_config import DatabaseConfig
from core.logger import ConsoleLog
from db.provider_registry import ProviderRegistry


def test_db2_connection():
    """Test connection to remote DB2 instance."""
    host = os.environ.get("DBLIFT_DB2_HOST", "192.168.1.20")
    port = int(os.environ.get("DBLIFT_DB2_PORT", "50000"))
    username = os.environ.get("DBLIFT_DB2_USERNAME", "db2inst1")
    password = os.environ.get("DBLIFT_DB2_PASSWORD", "testdb21234")
    database = os.environ.get("DBLIFT_DB2_DATABASE", "testdb")
    schema = os.environ.get("DBLIFT_DB2_SCHEMA", "DB2INST1")

    print(f"Testing DB2 connection:")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Database: {database}")
    print(f"  Schema: {schema}")
    print(f"  Username: {username}")
    print()

    # Build SQLAlchemy URL
    sqlalchemy_url = f"ibm_db_sa://{username}:{password}@{host}:{port}/{database}"

    db_config = DatabaseConfig(
        type="db2",
        url=sqlalchemy_url,
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        schema=schema,
    )

    config = DbliftConfig(database=db_config)
    log = ConsoleLog("db2_connection_test", enable_debug=True)

    try:
        provider = ProviderRegistry.create_provider(config, log)
        print("Creating connection...")
        connection = provider.create_connection()

        if connection:
            print("✅ Connection successful!")

            # Test a simple query
            print("Testing query execution...")
            result = provider.execute_query("SELECT 1 FROM SYSIBM.SYSDUMMY1")
            print(f"✅ Query executed successfully: {result}")

            provider.close()
            print("✅ Connection closed successfully")
            return True
        else:
            print("❌ Connection failed: No connection object returned")
            return False

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_db2_connection()
    sys.exit(0 if success else 1)
