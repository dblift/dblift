"""
Migration UI module.

This module contains the user interface components for displaying migration
information, progress, and results split into focused components:
- migration_ui.py: Main orchestrator and public API
- data_collector.py: Migration data collection and analysis
- table_renderer.py: Table rendering and display
"""

from .migration_ui import MigrationUI

__all__ = ["MigrationUI"]
