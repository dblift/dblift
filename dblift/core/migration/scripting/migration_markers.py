"""Synthetic history rows (baseline and delete markers) built by the script manager."""

from typing import TYPE_CHECKING, List, Optional, Tuple

from dblift.core.migration.migration import Migration, MigrationType

if TYPE_CHECKING:
    from dblift.core.logger import Log


class MigrationMarkerMixin:
    """Marker rows for ``baseline`` and ``repair``; mixed into ``MigrationScriptManager``.

    A marker is a history row with no script file. Its checksum is computed here, from
    the marker's content, like every other script's.
    """

    if TYPE_CHECKING:
        logger: Log

        def calculate_checksum(self, content: str) -> int: ...  # noqa: E704

        def parse_filename(  # noqa: E704
            self, filename: str
        ) -> Tuple[MigrationType, Optional[str], str, List[str]]: ...

    def baseline_marker(
        self,
        version: Optional[str],
        description: str,
        *,
        script_name: Optional[str] = None,
        content: Optional[str] = None,
    ) -> Migration:
        """Build the synthetic history row that records a baseline.

        The row has no script file. ``script_name`` defaults to ``B{version}__{description}.sql``
        and ``content`` to a comment naming the version; the checksum is computed here, from
        that content, like every other script's.
        """
        marker_name = script_name or f"B{version}__{description}.sql"
        marker_content = (
            content if content is not None else f"-- Baseline migration for version {version}"
        )
        return Migration(
            script_name=marker_name,
            content=marker_content,
            version=version,
            description=description,
            type=MigrationType.BASELINE,
            logger=self.logger,
            _filename_metadata=self.parse_filename(marker_name),
            checksum=self.calculate_checksum(marker_content),
        )

    def delete_marker(
        self,
        script_name: str,
        version: Optional[str],
        description: str,
        original_type_name: Optional[str] = None,
    ) -> Migration:
        """Build the synthetic history row that records a script as deleted.

        ``description`` is the reason. With ``original_type_name`` the stored description reads
        ``[DELETE:{original_type_name}] {description}``, so the original type survives in the
        history row. The checksum is computed here, from the marker's content.
        """
        marker_description = (
            f"[DELETE:{original_type_name}] {description}"
            if original_type_name is not None
            else description
        )
        marker_content = f"-- Delete operation: {marker_description}"
        return Migration(
            script_name=script_name,
            content=marker_content,
            version=version,
            description=marker_description,
            type=MigrationType.DELETE,
            tags=[],
            logger=self.logger,
            _filename_metadata=self.parse_filename(script_name),
            checksum=self.calculate_checksum(marker_content),
        )
