# DBLift Documentation

<p align="center">
  <img src="../logo/dblift_logo.png" width="600" alt="Dblift Logo">
</p>

**Manage your database changes with confidence**

DBLift helps you track and apply database changes systematically. Think of it as version control for your database schema - every change is tracked, can be rolled back, and works consistently across different environments.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/License-Apache--2.0-blue)
[![Tests](https://github.com/cmodiano/dblift-oss/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/cmodiano/dblift-oss/actions/workflows/unit-tests.yml)
[![Code Quality](https://github.com/cmodiano/dblift-oss/actions/workflows/code-quality.yml/badge.svg)](https://github.com/cmodiano/dblift-oss/actions/workflows/code-quality.yml)

---

## Quick Start

Get up and running in minutes:

1. **[Install DBLift](user-guide/getting-started.md#installation)** - Download and set up
2. **[Create Your First Migration](user-guide/getting-started.md#your-first-migration)** - Learn the basics
3. **[Apply Migrations](user-guide/commands.md#applying-changes-to-your-database)** - Deploy your changes
4. **[Configure CI/CD](user-guide/ci-cd.md)** - Run DBLift in automation

## Documentation Sections

### 👤 User Guide

Everything you need to use DBLift effectively:

- **[Getting Started](user-guide/getting-started.md)** - Installation and your first migration
- **[Configuration](user-guide/configuration.md)** - Database setup and configuration options
- **[Commands](user-guide/commands.md)** - All available commands and their usage
- **[Best Practices](user-guide/best-practices.md)** - Tips for effective database migrations
- **[Troubleshooting](user-guide/troubleshooting.md)** - Solutions to common problems

### 🔌 API Reference

Complete API documentation generated from code:

- **[API Client](api-reference/api.md)** - `DBLiftClient` and high-level operations
- **[CLI Commands](api-reference/cli.md)** - Command-line interface reference
- **[Core Modules](api-reference/core.md)** - Migration engine, SQL parsing, and more
- **[Database Providers](api-reference/db.md)** - Database-specific implementations

### 🏗️ Architecture

Technical deep-dive for developers:

- **[Overview](architecture/overview.md)** - System architecture and design principles
- **[Migration Engine](architecture/migration-engine.md)** - How migrations are executed
- **[Database Providers](architecture/database-providers.md)** - Provider system architecture
- **[SQL Parsing](architecture/sql-parsing.md)** - SQL parsing and analysis
- **[Configuration](architecture/configuration.md)** - Configuration system details

### 💻 Development

Contributing to DBLift:

- **[Setup](development/setup.md)** - Development environment setup
- **[Testing](development/testing.md)** - Testing guidelines and practices
- **[Contributing](development/contributing.md)** - How to contribute
- **[Adding Database Support](development/adding-database-support.md)** - Extending DBLift

### 📖 Examples

Real-world examples and tutorials:

- **[Basic Migrations](examples/basic-migrations.md)** - Common migration patterns
- **[Advanced Scenarios](examples/advanced-scenarios.md)** - Complex use cases

## Supported Databases

DBLift supports the following databases:

- **PostgreSQL** - Native SQLAlchemy support
- **MySQL** - Native SQLAlchemy support
- **SQL Server** - Native SQLAlchemy support
- **Oracle** - Native SQLAlchemy support
- **DB2** - Native SQLAlchemy support
- **SQLite** - Native Python support
- **Azure Cosmos DB** - Azure SDK integration

## Key Features

- ✅ **Version Control for Databases** - Track every schema change
- ✅ **Rollback Support** - Undo migrations when needed
- ✅ **Multi-Database Support** - Works with 7+ database types
- ✅ **Baseline Support** - Work with existing databases
- ✅ **Schema Comparison** - Compare database states
- ✅ **SQL Validation** - Validate SQL before applying
- ✅ **Tagged Migrations** - Organize migrations by feature
- ✅ **Dry-Run Mode** - Preview changes before applying
- ✅ **CI/CD Friendly** - Run checks and migrations in automation

## Need Help?

- 📖 Check the [User Guide](user-guide/getting-started.md) for common tasks
- 🔍 Search the documentation using the search bar above
- 🐛 Found a bug? [Open an issue](https://github.com/cmodiano/dblift/issues)
- 💬 Have questions? Check the [Troubleshooting](user-guide/troubleshooting.md) guide

---

**Ready to get started?** Jump to the [Getting Started Guide](user-guide/getting-started.md)!
