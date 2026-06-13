"""Dialect-agnostic ``Procedure`` / ``Parameter`` SQL objects — stored-routine DDL."""

from typing import Any, Dict, List, Optional

from core.sql_model.base import SqlObject, SqlObjectType

_NS_MYSQL = "mysql"  # lint: allow-dialect-string: plugin namespace key for dialect_options
_NS_POSTGRES = "postgresql"  # lint: allow-dialect-string: plugin namespace key for dialect_options


def _quirks_for(dialect: Optional[str]) -> Any:
    """Resolve quirks for *dialect* via the registry.

    Story 26-5: replaces inline ``if dialect in {...}`` dispatch in the
    procedure / parameter DDL paths. Returns a ``BaseQuirks`` fallback
    when the dialect is unknown so callers can read the default flags
    without guarding.
    """
    from db.base_quirks import BaseQuirks
    from db.provider_registry import ProviderRegistry

    canonical = ProviderRegistry.canonical_dialect_name(dialect or "")
    if canonical:
        return ProviderRegistry.get_quirks(canonical)
    return BaseQuirks()


class Parameter:
    """Represents a stored procedure parameter."""

    def __init__(
        self,
        name: str,
        data_type: str,
        direction: str = "IN",
        default_value: Optional[str] = None,
        dialect: Optional[str] = None,
        volatility: Optional[str] = None,
        security_definer: Optional[bool] = None,
    ):
        """Initialize a procedure parameter.

        Args:
            name: Parameter name
            data_type: Parameter data type
            direction: Parameter direction (IN, OUT, INOUT)
            default_value: Default value for the parameter
            dialect: SQL dialect (optional)
        """
        self.name = name
        self.data_type = data_type
        self.direction = direction.upper()  # IN, OUT, INOUT
        self.default_value = default_value
        self.dialect = dialect.lower() if dialect else None

    def __str__(self) -> str:
        """String representation of the parameter."""
        # Story 26-5: parameter direction keyword + default support both
        # come from plugin Quirks (``proc_param_inout_keyword`` and
        # ``proc_param_supports_default``).
        quirks = _quirks_for(self.dialect)

        if self.direction == "INOUT":
            direction_str = quirks.proc_param_inout_keyword
        else:
            direction_str = self.direction if self.direction != "IN" else ""

        result = ""
        if direction_str:
            result += f"{direction_str} "
        result += f"{self.name} {self.data_type}"

        if self.default_value is not None and quirks.proc_param_supports_default:
            result += f" = {self.default_value}"

        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert parameter to dictionary."""
        return {
            "name": self.name,
            "data_type": self.data_type,
            "direction": self.direction,
            "default_value": self.default_value,
            "dialect": self.dialect,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Parameter":
        """Create parameter from dictionary."""
        return cls(
            name=data["name"],
            data_type=data["data_type"],
            direction=data.get("direction", "IN"),
            default_value=data.get("default_value"),
            dialect=data.get("dialect"),
        )


class Procedure(SqlObject):
    """Represents a stored procedure or function."""

    def __init__(
        self,
        name: str,
        schema: Optional[str] = None,
        parameters: Optional[List[Parameter]] = None,
        body: Optional[str] = None,
        language: str = "SQL",
        dialect: Optional[str] = None,
        is_function: bool = False,
        return_type: Optional[str] = None,
        comment: Optional[str] = None,
        definition: Optional[str] = None,
        volatility: Optional[str] = None,
        security_definer: Optional[bool] = None,
        definer: Optional[str] = None,
        data_access: Optional[str] = None,
    ):
        """Initialize a stored procedure or function.

        Args:
            name: Procedure/function name
            schema: Schema name
            parameters: List of procedure/function parameters
            body: Procedure/function body
            language: Procedure language (SQL, PLSQL, PLPGSQL, TSQL, etc.)
            dialect: SQL dialect
            is_function: Whether this is a function (vs procedure)
            return_type: Return type for functions
            comment: Procedure/function comment/description
            definition: Full procedure/function definition SQL
            volatility: Volatility classification (IMMUTABLE, STABLE, VOLATILE)
            security_definer: Whether the procedure/function runs as SECURITY DEFINER
            definer: User who defined the routine (MySQL: user@host)
            data_access: Data access classification (MySQL: NO SQL, CONTAINS SQL, READS SQL DATA, MODIFIES SQL DATA)
        """
        object_type = SqlObjectType.FUNCTION if is_function else SqlObjectType.PROCEDURE
        super().__init__(name, object_type, schema, dialect)
        self.parameters = parameters or []

        # Ensure parameters inherit the dialect (use self.dialect — already normalized)
        for param in self.parameters:
            if not param.dialect:
                param.dialect = self.dialect

        self.body = body
        self.language = language
        self.is_function = is_function
        self.return_type = return_type
        self.comment = comment
        self.definition = definition
        self.volatility = volatility
        # ``dialect_options`` is initialized by ``SqlObject.__init__``; the
        # property setters below route into it under their plugin namespace.
        self.security_definer = security_definer
        self.definer = definer
        self.data_access = data_access

        if self.is_function and self.parameters:
            first_param = self.parameters[0]
            name_lower = first_param.name.lower() if first_param.name else ""
            if name_lower.startswith("param_0") or name_lower.startswith("return_value"):
                inferred_type = first_param.data_type
                if inferred_type:
                    self.return_type = inferred_type
                self.parameters = self.parameters[1:]

    @property
    def security_definer(self) -> Optional[bool]:
        """PostgreSQL ``SECURITY DEFINER`` flag."""
        return self.get_dialect_option(_NS_POSTGRES, "security_definer")

    @security_definer.setter
    def security_definer(self, value: Optional[bool]) -> None:
        """Set PostgreSQL ``SECURITY DEFINER`` flag."""
        self._set_plugin_option(_NS_POSTGRES, "security_definer", value)

    @property
    def definer(self) -> Optional[str]:
        """MySQL ``DEFINER = user@host``."""
        value = self.get_dialect_option(_NS_MYSQL, "definer")
        return value if value is None or isinstance(value, str) else str(value)

    @definer.setter
    def definer(self, value: Optional[str]) -> None:
        """Set MySQL ``DEFINER = user@host``."""
        self._set_plugin_option(_NS_MYSQL, "definer", value)

    @property
    def data_access(self) -> Optional[str]:
        """MySQL ``DATA ACCESS`` characteristic (``READS SQL DATA`` / …)."""
        value = self.get_dialect_option(_NS_MYSQL, "data_access")
        return value if value is None or isinstance(value, str) else str(value)

    @data_access.setter
    def data_access(self, value: Optional[str]) -> None:
        """Set MySQL ``DATA ACCESS`` characteristic (``READS SQL DATA`` / …)."""
        self._set_plugin_option(_NS_MYSQL, "data_access", value)

    @property
    def create_statement(self) -> str:
        """Generate CREATE PROCEDURE or CREATE FUNCTION statement using database-specific generators.

        Returns:
            Dialect-specific CREATE PROCEDURE/FUNCTION statement
        """
        # Use the appropriate SQL generator for the dialect
        from core.sql_generator.generator_factory import (
            SqlGeneratorFactory,
        )

        try:
            # Match Table/View: factory needs a registered dialect; plain SqlGenerator
            # has no generate_create_statement, so "" would always fall back to basic DDL.
            generator = SqlGeneratorFactory.create(
                self.dialect or "postgresql"  # lint: allow-dialect-string: factory default fallback
            )
            # Check if generator has the new method
            if hasattr(generator, "generate_create_statement"):
                result = generator.generate_create_statement(self)
                return str(result)
            else:
                # Fallback for old generators that don't have the method yet
                return self._generate_basic_create_statement()
        except (ValueError, ImportError, AttributeError):
            # Fallback to basic CREATE PROCEDURE/FUNCTION if generator not available
            return self._generate_basic_create_statement()

    def _generate_basic_create_statement(self) -> str:
        """Generate a basic CREATE PROCEDURE/FUNCTION statement as fallback."""
        if self.definition:
            return self.definition

        # Skip generating SQL for system functions/operators that don't have valid definitions
        # These are typically introspected system functions (e.g., comparison operators, type casts)
        # that shouldn't be exported as CREATE FUNCTION statements
        if self.is_function and not self.body and not self.definition:
            # Check if this looks like a system function (operator or type name)
            system_function_names = {
                "<",
                "<=",
                "<>",
                "=",
                ">",
                ">=",
                "VARCHAR",
                "INTEGER",
                "DECIMAL",
                "TIMESTAMP",
            }
            if self.name in system_function_names or (
                self.return_type and isinstance(self.return_type, int)
            ):
                # This is a system function - return empty string to skip it
                return ""

        # Story 26-5: dialect dispatch goes through plugin Quirks.
        quirks = _quirks_for(self.dialect)

        # Format schema and procedure/function name properly
        schema_name = self.format_identifier(self.schema) if self.schema else ""
        proc_name = self.format_identifier(self.name)
        schema_prefix = f"{schema_name}." if schema_name else ""

        create_keyword = "CREATE OR REPLACE" if quirks.proc_supports_create_or_replace else "CREATE"
        object_keyword = "FUNCTION" if self.is_function else "PROCEDURE"

        stmt = f"{create_keyword} {object_keyword} {schema_prefix}{proc_name}"

        if self.parameters:
            params_str = ", ".join(str(param) for param in self.parameters)
            stmt += f"({params_str})"
        else:
            stmt += "()"

        if self.is_function and self.return_type:
            stmt += f" {quirks.proc_function_returns_keyword} {self.return_type}"

        if self.language != "SQL" and quirks.proc_supports_language_clause:
            stmt += f"\nLANGUAGE {self.language.lower()}"

        if self.body:
            stmt += self._render_body(quirks.proc_body_wrap_style)

        return stmt

    def _render_body(self, style: str) -> str:
        """Render procedure body for the given wrap *style*.

        Styles correspond to ``BaseQuirks.proc_body_wrap_style`` values
        — opaque internal vocabulary, not dialect names.
        """
        if style == "begin_end":
            return f"\nAS\nBEGIN\n{self.body}\nEND"
        if style == "dollar_quotes":
            return f"\nAS $$\n{self.body}\n$$"
        if style == "mysql_characteristics":
            return self._render_mysql_body()
        # ``plain`` is the default shape (also used by Oracle).
        return f"\nAS\n{self.body}"

    def _render_mysql_body(self) -> str:
        """MySQL body wrap: characteristics block + BEGIN/END."""
        characteristics: List[str] = []
        if self.volatility:
            if self.volatility.upper() == "IMMUTABLE":
                characteristics.append("DETERMINISTIC")
            else:
                characteristics.append("NOT DETERMINISTIC")
        elif self.is_function:
            characteristics.append("NOT DETERMINISTIC")
        if self.security_definer is not None:
            characteristics.append(
                "SQL SECURITY DEFINER" if self.security_definer else "SQL SECURITY INVOKER"
            )
        if self.data_access:
            characteristics.append(self.data_access.upper())
        if self.comment:
            escaped_comment = self.comment.replace("'", "''")
            characteristics.append(f"COMMENT '{escaped_comment}'")

        prefix = "\n    " + "\n    ".join(characteristics) if characteristics else ""
        body_text = (self.body or "").strip()
        if body_text.upper().startswith("BEGIN"):
            return f"{prefix}\n{body_text}"
        return f"{prefix}\nBEGIN\n{self.body}\nEND"

    @property
    def drop_statement(self) -> str:
        """Generate DROP PROCEDURE or DROP FUNCTION statement.

        Returns:
            SQL DROP PROCEDURE/FUNCTION statement
        """
        schema_prefix = self.format_identifier(self.schema) + "." if self.schema else ""
        proc_name = self.format_identifier(self.name)
        object_keyword = "FUNCTION" if self.is_function else "PROCEDURE"

        # Story 26-5: ``IF EXISTS`` support comes from plugin Quirks.
        if _quirks_for(self.dialect).proc_drop_supports_if_exists:
            return f"DROP {object_keyword} IF EXISTS {schema_prefix}{proc_name}"
        return f"DROP {object_keyword} {schema_prefix}{proc_name}"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Procedure":
        """Create procedure/function from dictionary representation.

        Args:
            data: Dictionary with procedure/function attributes

        Returns:
            Procedure object
        """
        # Create parameters with the same dialect as the procedure
        parameters = []
        if "parameters" in data:
            dialect = data.get("dialect")
            parameters = [
                Parameter.from_dict({**param_data, "dialect": dialect})
                for param_data in data["parameters"]
            ]

        return cls(
            name=data["name"],
            schema=data.get("schema"),
            parameters=parameters,
            body=data.get("body"),
            language=data.get("language", "SQL"),
            dialect=data.get("dialect"),
            is_function=data.get("is_function", False),
            return_type=data.get("return_type"),
            comment=data.get("comment"),
            definition=data.get("definition"),
            volatility=data.get("volatility"),
            security_definer=data.get("security_definer"),
            definer=data.get("definer"),
            data_access=data.get("data_access"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert procedure/function to dictionary representation.

        Returns:
            Dictionary with procedure/function attributes
        """
        return {
            "name": self.name,
            "schema": self.schema,
            "object_type": self.object_type.value,
            "dialect": self.dialect,
            "parameters": [param.to_dict() for param in self.parameters],
            "body": self.body,
            "language": self.language,
            "is_function": self.is_function,
            "return_type": self.return_type,
            "comment": self.comment,
            "definition": self.definition,
            "volatility": self.volatility,
            "security_definer": self.security_definer,
            "definer": self.definer,
            "data_access": self.data_access,
        }
