"""Load the versioned theme table into theme_groups / group_memberships.

The whole table is validated against the DB before anything is written; any
located error aborts the sync.  Re-running the same table is a no-op.  A member
leaves a theme only through an explicit ``valid_to`` in the table: rows are
closed, never deleted, and a theme or open member missing from the table is an
error rather than an undated close.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT
from app.db import SessionLocal
from app.models import GroupMembership, Instrument, ThemeGroup
from app.theme_table import (
    THEME_DISPLAY_CATEGORY,
    THEME_GROUP_TYPE,
    THEME_TABLE_PATH,
    ThemeTableError,
    definition_version,
    load_theme_table,
    member_period,
    membership_source,
    split_instrument,
    theme_group_id,
)

THEME_MEMBER_TYPES = frozenset({"stock", "ipo"})


def _table_source(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        relative = path
    return f"theme_table:{relative.as_posix()}"


def _version_key(value: str | None) -> tuple[int, ...] | None:
    """``themes_v1:2026.10.17.2`` -> (2026, 10, 17, 2); None when not comparable."""

    version = (value or "").rpartition(":")[2]
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None


def _group_fields(theme: dict[str, Any], version: str) -> dict[str, Any]:
    """ThemeGroup content written by a sync, excluding the file path fields."""

    return {
        "name": theme["name"],
        "group_type": THEME_GROUP_TYPE,
        "definition_version": version,
        "active": True,
        "display_name_zh": theme["name"],
        "display_description_zh": theme["description"],
        "display_category": THEME_DISPLAY_CATEGORY,
        "name_status": "verified",
    }


def _plan(db: Session, table: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    changes: list[str] = []
    plans: list[dict[str, Any]] = []
    version = definition_version(table)
    instrument_rows = db.scalars(
        select(Instrument).where(Instrument.exchange.in_(("TWSE", "TPEx")))
    ).all()
    instruments = {(item.exchange, item.symbol): item for item in instrument_rows}
    labels = {item.id: f"{item.exchange}:{item.symbol}" for item in instrument_rows}
    table_group_ids = {theme_group_id(theme["id"]) for theme in table["themes"]}
    db_versions: set[str] = set()
    for group in db.scalars(
        select(ThemeGroup).where(ThemeGroup.group_type == THEME_GROUP_TYPE)
    ).all():
        db_versions.add(group.definition_version)
        if group.id not in table_group_ids:
            errors.append(
                f"theme_groups({group.id}): theme missing from table; keep it with valid_to instead of deleting"
            )
    current_version = max(
        db_versions, key=lambda value: _version_key(value) or (), default=None
    )
    new_key, current_key = _version_key(version), _version_key(current_version)
    if current_key is not None and new_key is not None and new_key < current_key:
        errors.append(
            f"$.version: {version} is lower than DB definition_version {current_version}"
        )

    for theme_index, theme in enumerate(table["themes"]):
        location = f"themes[{theme_index}]({theme['id']})"
        group_id = theme_group_id(theme["id"])
        group = db.get(ThemeGroup, group_id)
        if group is not None and group.group_type != THEME_GROUP_TYPE:
            errors.append(
                f"{location}.id: {group_id} already exists as group_type={group.group_type}"
            )
            continue
        existing = (
            db.scalars(
                select(GroupMembership).where(GroupMembership.group_id == group_id)
            ).all()
            if group
            else []
        )
        if group is not None and any(
            getattr(group, key) != value
            for key, value in _group_fields(theme, version).items()
            if key != "definition_version"
        ):
            changes.append(location)
        by_instrument: dict[int, list[GroupMembership]] = {}
        for row in existing:
            by_instrument.setdefault(row.instrument_id, []).append(row)
        members: list[dict[str, Any]] = []
        for member_index, member in enumerate(theme["members"]):
            member_location = (
                f"{location}.members[{member_index}]({member['instrument']})"
            )
            instrument = instruments.get(split_instrument(member["instrument"]))
            if instrument is None:
                errors.append(f"{member_location}: unknown instrument")
                continue
            if instrument.instrument_type not in THEME_MEMBER_TYPES:
                errors.append(
                    f"{member_location}: instrument_type={instrument.instrument_type} is not a stock"
                )
                continue
            start, end = member_period(theme, member)
            source = membership_source(table, member)
            rows = by_instrument.get(instrument.id, [])
            current = [row for row in rows if row.valid_from == start]
            if not current or (
                current[0].valid_to,
                current[0].source,
                current[0].role,
            ) != (end, source, "member"):
                changes.append(member_location)
            for row in rows:
                if row.valid_from == start:
                    continue
                if row.valid_to is None:
                    changes.append(member_location)
                if row.valid_from > start:
                    errors.append(
                        f"{member_location}: existing period from {row.valid_from.isoformat()} starts after table valid_from"
                    )
                elif row.valid_to is not None and row.valid_to >= start:
                    errors.append(
                        f"{member_location}: existing period {row.valid_from.isoformat()}~{row.valid_to.isoformat()} overlaps"
                    )
            members.append(
                {
                    "instrument": instrument,
                    "valid_from": start,
                    "valid_to": end,
                    "source": source,
                    "rows": by_instrument.pop(instrument.id, []),
                }
            )
        for instrument_id, rows in by_instrument.items():
            if any(row.valid_to is None for row in rows):
                errors.append(
                    f"{location}: {labels.get(instrument_id, f'instrument_id={instrument_id}')} has an open membership but is missing from the table; set valid_to"
                )
        plans.append(
            {"theme": theme, "group_id": group_id, "group": group, "members": members}
        )
    if current_version == version and changes:
        # Content edits must ship as a new table version.
        errors.extend(
            f"{location}: content differs from DB but $.version equals DB definition_version {version}; bump $.version"
            for location in dict.fromkeys(changes)
        )
    return plans, errors


def apply_theme_table(
    db: Session, table: dict[str, Any], *, path: Path | None = None
) -> dict[str, Any]:
    """Validate against the DB, then write groups and membership periods (no commit)."""

    plans, errors = _plan(db, table)
    if errors:
        raise ThemeTableError(errors)
    source = _table_source(path or THEME_TABLE_PATH)
    version = definition_version(table)
    counts = {
        "groups_created": 0,
        "groups_updated": 0,
        "memberships_created": 0,
        "memberships_updated": 0,
        "memberships_closed": 0,
    }
    for plan in plans:
        theme = plan["theme"]
        group = plan["group"]
        fields = {
            **_group_fields(theme, version),
            "source": source,
            "name_source": source,
        }
        if group is None:
            db.add(ThemeGroup(id=plan["group_id"], **fields))
            db.flush()
            counts["groups_created"] += 1
        elif any(getattr(group, key) != value for key, value in fields.items()):
            for key, value in fields.items():
                setattr(group, key, value)
            counts["groups_updated"] += 1
        for member in plan["members"]:
            start, end = member["valid_from"], member["valid_to"]
            current = None
            for row in member["rows"]:
                if row.valid_from == start:
                    current = row
                elif row.valid_to is None:
                    # Re-listed with a later start: close the earlier open period.
                    row.valid_to = start - timedelta(days=1)
                    counts["memberships_closed"] += 1
            if current is None:
                db.add(
                    GroupMembership(
                        group_id=plan["group_id"],
                        instrument_id=member["instrument"].id,
                        valid_from=start,
                        valid_to=end,
                        role="member",
                        confidence=1.0,
                        source=member["source"],
                    )
                )
                counts["memberships_created"] += 1
                continue
            if current.valid_to is None and end is not None:
                counts["memberships_closed"] += 1
            elif (current.valid_to, current.source, current.role) != (
                end,
                member["source"],
                "member",
            ):
                counts["memberships_updated"] += 1
            current.valid_to = end
            current.source = member["source"]
            current.role = "member"
    db.flush()
    return {
        "status": "success",
        "table": table["table"],
        "version": table["version"],
        "definition_version": version,
        "themes": len(plans),
        "members": sum(len(plan["members"]) for plan in plans),
        **counts,
    }


def sync_themes(path: Path | str | None = None) -> dict[str, Any]:
    """CLI entry: load, validate and write the theme table in one transaction."""

    target = Path(path) if path is not None else THEME_TABLE_PATH
    try:
        table = load_theme_table(target)
    except ThemeTableError as error:
        return {"status": "failed", "file": str(target), "errors": error.errors}
    with SessionLocal() as db:
        try:
            result = apply_theme_table(db, table, path=target)
        except ThemeTableError as error:
            db.rollback()
            return {"status": "failed", "file": str(target), "errors": error.errors}
        db.commit()
    return {"file": str(target), **result}
