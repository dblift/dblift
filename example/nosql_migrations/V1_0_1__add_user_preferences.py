"""
Example CosmosDB Python migration for dblift — adding a preferences field.

Demonstrates upsert pattern for adding a new attribute to existing items.
"""

DEFAULT_PREFERENCES = {
    "theme": "light",
    "language": "en",
    "notifications": {"email": True, "push": False},
}


def migrate(context):
    """Add default preferences to all existing users that lack them."""
    db = context.database
    context.log.info("Adding preferences to existing users...")

    if context.dry_run:
        context.log.info("[DRY-RUN] Would patch user items with default preferences")
        return

    users = db.get_container_client("users")
    count = 0
    for item in users.query_items(
        "SELECT * FROM c WHERE NOT IS_DEFINED(c.preferences)", enable_cross_partition_query=True
    ):
        item["preferences"] = DEFAULT_PREFERENCES
        users.upsert_item(item)
        count += 1

    context.log.info(f"Updated {count} user(s) with default preferences")


def undo(context):
    """Remove preferences field from all users."""
    if context.dry_run:
        context.log.info("[DRY-RUN] Would remove preferences from all users")
        return

    db = context.database
    users = db.get_container_client("users")
    count = 0
    for item in users.query_items(
        "SELECT * FROM c WHERE IS_DEFINED(c.preferences)", enable_cross_partition_query=True
    ):
        item.pop("preferences", None)
        users.upsert_item(item)
        count += 1

    context.log.info(f"Removed preferences from {count} user(s)")
