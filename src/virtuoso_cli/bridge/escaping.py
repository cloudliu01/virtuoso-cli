"""SKILL string escaping."""


def escape_skill_string(value: str) -> str:
    """Escape user-controlled text before embedding it in a SKILL string."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
