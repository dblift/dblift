"""
Example CosmosDB Python migration for dblift.

Shows how to create containers using the MigrationContext API.
The migrate() function receives a MigrationContext with:
    context.database  — azure.cosmos.DatabaseProxy
    context.client    — azure.cosmos.CosmosClient
    context.log       — dblift logger
    context.dry_run   — True when running with --dry-run
"""

from azure.cosmos.exceptions import CosmosResourceExistsError
from azure.cosmos.partition_key import PartitionKey


def migrate(context):
    """Create the 'users' container."""
    db = context.database
    context.log.info("Creating 'users' container...")

    if context.dry_run:
        context.log.info("[DRY-RUN] Would create 'users' container")
        return

    try:
        db.create_container(
            id="users",
            partition_key=PartitionKey(path="/id"),
        )
        context.log.info("Created 'users' container")
    except CosmosResourceExistsError:
        context.log.info("'users' container already exists — skipping")


def undo(context):
    """Drop the 'users' container."""
    if context.dry_run:
        context.log.info("[DRY-RUN] Would delete 'users' container")
        return

    context.database.delete_container("users")
    context.log.info("Deleted 'users' container")
