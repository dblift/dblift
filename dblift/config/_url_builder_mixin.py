"""URL-building helpers mixed into :class:`BaseDatabaseConfig`.

Extracted from ``dblift.config.database_config`` during PR-H10 to keep the
facade module under its 500-line budget. The mixin only relies on the
public attributes exposed by ``BaseDatabaseConfig`` (``url``, ``host``,
``port``, ``database``, ``schema``, ``username``, ``password``,
``connection_timeout``, ``extra_params``, ``options``) so it can be
included into the base class without further coupling.
"""

from typing import List


class UrlBuilderMixin:
    """Generic native URL building shared by every dialect.

    Concrete subclasses can override :meth:`build_database_url`; the default
    implementation delegates SQLAlchemy URL construction to the owning plugin
    through the provider registry.
    """

    # The mixin reads these attributes, all of which are declared on the
    # ``BaseDatabaseConfig`` dataclass. They are listed here only for
    # documentation — actual storage happens on the dataclass.
    url: str
    host: "str | None"
    port: "int | None"
    database: "str | None"
    schema: str
    username: str
    password: str
    type: str
    connection_timeout: int
    extra_params: "dict[str, str]"
    options: "dict[str, object]"

    def build_database_url(self) -> str:
        """Build a native database URL."""
        if self.url:
            return self.url
        if not self.host:
            raise ValueError("Host is required when URL is not provided")
        from dblift.db.provider_registry import ProviderRegistry

        plugin_url = ProviderRegistry.build_sqlalchemy_url(self)
        if plugin_url:
            return plugin_url

        url_parts = [f"{self.type}://", self.host or "localhost"]

        if self.port:
            url_parts.append(f":{self.port}")

        if self.database:
            url_parts.append(f"/{self.database}")

        params: list[str] = []
        if self.schema:
            params.append(f"currentSchema={self.schema}")
        if self.connection_timeout:
            params.append(f"connect_timeout={self.connection_timeout}")
        if self.options:
            for key, value in self.options.items():
                params.append(f"{key}={value}")
        if self.extra_params:
            for key, value in self.extra_params.items():
                params.append(f"{key}={value}")

        if params:
            url_parts.append(f"?{'&'.join(params)}")

        return "".join(url_parts)

    def _build_standard_url(
        self,
        scheme: str,
        dialect_params: List[str],
        *,
        timeout_key: str = "connect_timeout",
        include_credentials: bool = True,
    ) -> str:
        """Build a standard URL: scheme[user:pass@]host[:port][/database][?params].

        Args:
            scheme: URL scheme including separator, e.g. ``"postgresql://"`` or
                ``"ibm_db_sa://"``.
            dialect_params: Dialect-specific query parameters (key=value strings),
                already built.
            timeout_key: Query parameter name for ``connection_timeout``.
            include_credentials: Include ``user:pass@`` in URL.
        """
        if self.url:
            return self.url

        parts = [scheme]

        if include_credentials and self.username:
            parts.append(self.username)
            if self.password:
                parts.append(f":{self.password}")
            parts.append("@")

        parts.append(self.host or "localhost")
        if self.port:
            parts.append(f":{self.port}")
        if self.database:
            parts.append(f"/{self.database}")

        params = list(dialect_params)
        if self.connection_timeout:
            params.append(f"{timeout_key}={self.connection_timeout}")
        if self.extra_params:
            for key, value in self.extra_params.items():
                params.append(f"{key}={value}")

        if params:
            parts.append("?" + "&".join(params))

        return "".join(parts)
