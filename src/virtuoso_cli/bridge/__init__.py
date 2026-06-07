"""Bridge protocol client helpers."""

from virtuoso_cli.bridge.client import VirtuosoClient
from virtuoso_cli.bridge.escaping import escape_skill_string

__all__ = ["VirtuosoClient", "escape_skill_string"]
