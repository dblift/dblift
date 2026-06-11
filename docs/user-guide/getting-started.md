# Getting Started

Welcome to DBLift! This guide will help you get up and running quickly.

## Installation

### Step 1: Download DBLift

Visit the [releases page](https://github.com/cmodiano/dblift/releases) and download the version for your operating system:

- **Windows**: `dblift-windows-x64.zip`
- **macOS (Intel)**: `dblift-macos-x64.tar.gz`
- **macOS (Apple Silicon)**: `dblift-macos-arm64.tar.gz`
- **Linux**: `dblift-linux-x64.tar.gz`

### Step 2: Extract the Files

- **Windows**: Right-click the downloaded file and select "Extract All"
- **macOS/Linux**: Open Terminal and run:
  ```bash
  tar xzf dblift-*.tar.gz
  ```

### Step 2b: macOS — Remove Quarantine Attribute (Apple Silicon and Intel)

macOS Gatekeeper blocks unsigned binaries by default. After extracting, run:

```bash
xattr -rd com.apple.quarantine /path/to/dblift-macos-arm64/
```

Replace `dblift-macos-arm64` with the actual folder name. Without this step, DBLift will fail with a "code signature not valid" error.

If you prefer the GUI: open **System Settings → Privacy & Security** and approve DBLift there.

### Step 3: Verify Installation

Open your terminal or command prompt and run:

```bash
# On Windows
C:\path\to\dblift\dblift.bat --version

# On macOS/Linux
/path/to/dblift/dblift --version
```

You should see the DBLift version number. You're ready to go!

## Your First Migration

Let's create your first database change in 4 simple steps:

### Step 1: Create a Project Folder

Create a folder for your database project and navigate to it:
```bash
mkdir my-database-project
cd my-database-project
```

### Step 2: Tell DBLift About Your Database

Create a file called `dblift.yaml` with your database connection details:

```yaml
database:
  url: "postgresql+psycopg://localhost:5432/mydb"
  schema: "public"
  username: "myuser"
  password: "mypassword"

migrations:
  directory: "./migrations"
```

!!! tip "Tip"
    Replace the values above with your actual database details. Supported databases: PostgreSQL, SQL Server, Oracle, MySQL, DB2, SQLite, Azure Cosmos DB.

### Step 3: Create Your First Migration File

Create a folder called `migrations` and add your first migration file:

```bash
mkdir migrations
```

Create a file: `migrations/V1_0_0__create_users_table.sql`

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE
);
```

!!! note "Migration File Naming"
    The `V1_0_0` is the version number, and everything after `__` (double underscore) is a description. This naming helps DBLift track which changes have been applied.

### Step 4: Apply Your Migration

Run this command:
```bash
dblift migrate
```

That's it! DBLift will create the `users` table in your database and remember that this migration has been applied.

## Understanding the Basics

### What are Migrations?

Migrations are SQL files that describe changes to your database. Each file represents one change (like creating a table, adding a column, or inserting data).

Think of migrations as a recipe book for your database:
- Each recipe (migration file) describes one change
- They're numbered in order
- DBLift keeps track of which recipes you've already followed
- You can always see what's been done and what's pending

### How Migration Files Work

Migration files follow a naming pattern that tells DBLift important information:

```
V1_0_0__create_users_table.sql
│││││││└─ Description (what this change does)
│││││││
││││││└─ Double underscore separator
│││││└─ Version number (1.0.0)
││││└─ Version type (V = versioned migration)
```

### Three Types of Migrations

1. **Versioned Migrations** (Start with `V`)
   - Run once, in order
   - Example: `V1_0_0__create_users_table.sql`
   - Use for: Creating tables, adding columns, schema changes

2. **Repeatable Migrations** (Start with `R`)
   - Re-run whenever the file changes
   - Example: `R__create_dashboard_view.sql`
   - Use for: Views, stored procedures, functions

3. **Undo Migrations** (Start with `U`)
   - Reverse a specific versioned migration
   - Example: `U1_0_0__drop_users_table.sql`
   - Use for: Rolling back changes when needed

## Next Steps

Now that you've created your first migration, check out:

- **[Configuration Guide](configuration.md)** - Learn about all configuration options
- **[Commands Reference](commands.md)** - Discover all available commands
- **[Best Practices](best-practices.md)** - Tips for effective migrations
