from __future__ import annotations

VALID_STORAGE_MODES = frozenset({
    "sqlite",
    "markdown",
    "remote",
    "sqlite_markdown",
    "all",
})


def resolve_storage_mode(mode: str) -> dict[str, bool]:
    """Map storage.mode to persistence destinations."""
    mode = (mode or "sqlite_markdown").lower().strip()
    if mode not in VALID_STORAGE_MODES:
        raise ValueError(
            f"Invalid storage.mode '{mode}'. "
            f"Choose: {', '.join(sorted(VALID_STORAGE_MODES))}"
        )
    return {
        "persist_sqlite": mode in ("sqlite", "sqlite_markdown", "all"),
        "use_markdown": mode in ("markdown", "sqlite_markdown", "all"),
        "use_remote": mode in ("remote", "all"),
    }


def describe_storage_mode(mode: str) -> str:
    flags = resolve_storage_mode(mode)
    parts = []
    if flags["persist_sqlite"]:
        parts.append("local SQLite file")
    if flags["use_markdown"]:
        parts.append("markdown reports")
    if flags["use_remote"]:
        parts.append("Postgres/MySQL remote")
    return f"{mode}: saves to " + ", ".join(parts)
