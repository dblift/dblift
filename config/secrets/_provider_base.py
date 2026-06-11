"""Secrets provider base stub for the public package.

Secret-manager provider base classes (vault, AWS, Azure, GCP) are not bundled
here. This stub provides the minimum interface to keep the config layer
importable.
"""

from __future__ import annotations


class SecretsResolutionError(Exception):
    """Raised when a secret URI cannot be resolved.

    Secret URIs are unsupported here, so this error is never raised in
    practice, but the class must exist for code that catches it.
    """
