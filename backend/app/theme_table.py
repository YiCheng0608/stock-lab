"""Versioned, manually curated theme table (題材表).

The table is a repo data file (``backend/data/themes/themes_v1.json``).  Every
member carries public evidence, a relation, a relevance level and its own
effective period.  This module only parses and validates the file; the DB sync
lives in ``worker.themes``.  Validation is structural and never touches the
DB, so unknown instruments are reported by the sync step.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT

THEME_TABLE_PATH = PROJECT_ROOT / "backend" / "data" / "themes" / "themes_v1.json"
THEME_TABLE_SCHEMA_VERSION = "theme-table/v1"
THEME_GROUP_TYPE = "theme"
# Reserved for news/LLM theme suggestions awaiting human review: inactive,
# never scored or ranked, members use role="candidate".
THEME_CANDIDATE_GROUP_TYPE = "theme_candidate"
THEME_CANDIDATE_NAME_STATUS = "pending_verification"
THEME_GROUP_ID_PREFIX = "theme-"
THEME_DISPLAY_CATEGORY = "題材"
MEMBERSHIP_SOURCE_KIND = "theme_table"
MEMBERSHIP_SOURCE_KEYS = ("url", "relation", "relevance", "theme_version")
# GroupMembership.source is String(500); the compact evidence JSON must fit.
MEMBERSHIP_SOURCE_MAX_LENGTH = 500
# ThemeGroup.definition_version is String(30).
DEFINITION_VERSION_MAX_LENGTH = 30

RELATIONS = frozenset({"core_business", "product_line", "supply_chain"})
RELEVANCE_LEVELS = frozenset({"high", "medium", "low"})
EXCHANGES = frozenset({"TWSE", "TPEx"})

_THEME_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TABLE_NAME = re.compile(r"^[a-z0-9_]+$")
_VERSION = re.compile(r"^\d{4}\.\d{2}\.\d{2}(?:\.\d+)?$")
_INSTRUMENT = re.compile(r"^(TWSE|TPEx):([0-9A-Z]{4,6})$")


class ThemeTableError(ValueError):
    """Raised with every located problem; nothing is written on failure."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def theme_group_id(theme_id: str) -> str:
    return f"{THEME_GROUP_ID_PREFIX}{theme_id}"


def definition_version(table: dict[str, Any]) -> str:
    return f"{table['table']}:{table['version']}"


def membership_source(table: dict[str, Any], member: dict[str, Any]) -> str:
    """Compact JSON kept on GroupMembership.source.

    Fixed keys: ``kind``, ``url`` (the member's first evidence URL),
    ``relation``, ``relevance`` and ``theme_version``.  Further evidence,
    titles and quotes stay in the table file.
    """

    return json.dumps(
        {
            "kind": MEMBERSHIP_SOURCE_KIND,
            "url": member["evidence"][0]["url"],
            "relation": member["relation"],
            "relevance": member["relevance"],
            "theme_version": definition_version(table),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def parse_membership_source(source: str | None) -> dict[str, Any] | None:
    """Return the theme evidence of a membership, or None for other sources."""

    if not source or not source.startswith("{"):
        return None
    try:
        value = json.loads(source)
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("kind") != MEMBERSHIP_SOURCE_KIND:
        return None
    return {
        key: value.get(key) if isinstance(value.get(key), str) else None
        for key in MEMBERSHIP_SOURCE_KEYS
    }


def load_theme_table(path: Path | str | None = None) -> dict[str, Any]:
    """Read and validate a theme table file; raise ThemeTableError on any problem."""

    target = Path(path) if path is not None else THEME_TABLE_PATH
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as error:
        raise ThemeTableError(
            [f"{target}: cannot read file ({type(error).__name__})"]
        ) from error
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ThemeTableError([f"{target}: invalid JSON ({error})"]) from error
    errors = validate_theme_table(data)
    if errors:
        raise ThemeTableError(errors)
    return data


def _date(
    value: Any, location: str, errors: list[str], *, required: bool
) -> date | None:
    if value is None:
        if required:
            errors.append(f"{location}: required date missing")
        return None
    if not isinstance(value, str):
        errors.append(f"{location}: date must be a YYYY-MM-DD string")
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        errors.append(f"{location}: invalid date {value!r}")
        return None
    if parsed.isoformat() != value:
        errors.append(f"{location}: date must be YYYY-MM-DD")
        return None
    return parsed


def _text(value: Any, location: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{location}: non-empty text required")
        return None
    return value


def _validate_member(
    member: Any,
    location: str,
    theme_from: date | None,
    theme_to: date | None,
    errors: list[str],
) -> None:
    if not isinstance(member, dict):
        errors.append(f"{location}: member must be an object")
        return
    if member.get("relation") not in RELATIONS:
        errors.append(f"{location}.relation: must be one of {sorted(RELATIONS)}")
    if member.get("relevance") not in RELEVANCE_LEVELS:
        errors.append(
            f"{location}.relevance: must be one of {sorted(RELEVANCE_LEVELS)}"
        )
    if "name" in member and not isinstance(member["name"], str):
        errors.append(f"{location}.name: must be text")
    evidence = member.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append(
            f"{location}.evidence: at least one public evidence item required"
        )
    else:
        urls: set[str] = set()
        for index, item in enumerate(evidence):
            item_location = f"{location}.evidence[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{item_location}: evidence must be an object")
                continue
            url = item.get("url")
            if not isinstance(url, str) or not re.match(r"^https?://\S+$", url):
                errors.append(f"{item_location}.url: absolute http(s) URL required")
            elif url in urls:
                errors.append(f"{item_location}.url: duplicate evidence URL")
            else:
                urls.add(url)
            _text(item.get("title"), f"{item_location}.title", errors)
            _text(item.get("quote"), f"{item_location}.quote", errors)
    member_from = _date(
        member.get("valid_from"), f"{location}.valid_from", errors, required=False
    )
    member_to = _date(
        member.get("valid_to"), f"{location}.valid_to", errors, required=False
    )
    start = member_from or theme_from
    end = member_to or theme_to
    if member_from and theme_from and member_from < theme_from:
        errors.append(
            f"{location}.valid_from: earlier than theme valid_from {theme_from.isoformat()}"
        )
    if member_to and theme_to and member_to > theme_to:
        errors.append(
            f"{location}.valid_to: later than theme valid_to {theme_to.isoformat()}"
        )
    if start and end and end < start:
        errors.append(
            f"{location}: valid_to {end.isoformat()} is before valid_from {start.isoformat()}"
        )


def validate_theme_table(data: Any) -> list[str]:
    """Return located schema errors (empty when the table is valid)."""

    errors: list[str] = []
    if not isinstance(data, dict):
        return ["$: theme table must be a JSON object"]
    if data.get("schema_version") != THEME_TABLE_SCHEMA_VERSION:
        errors.append(f"$.schema_version: must be {THEME_TABLE_SCHEMA_VERSION!r}")
    table = data.get("table")
    if not isinstance(table, str) or not _TABLE_NAME.match(table):
        errors.append("$.table: lowercase table name required (e.g. themes_v1)")
    version = data.get("version")
    if not isinstance(version, str) or not _VERSION.match(version):
        errors.append("$.version: must be YYYY.MM.DD or YYYY.MM.DD.N")
    elif (
        isinstance(table, str)
        and len(f"{table}:{version}") > DEFINITION_VERSION_MAX_LENGTH
    ):
        errors.append(
            f"$.version: table:version exceeds {DEFINITION_VERSION_MAX_LENGTH} characters"
        )
    themes = data.get("themes")
    if not isinstance(themes, list) or not themes:
        errors.append("$.themes: at least one theme required")
        return errors

    theme_ids: set[str] = set()
    for theme_index, theme in enumerate(themes):
        location = f"themes[{theme_index}]"
        if not isinstance(theme, dict):
            errors.append(f"{location}: theme must be an object")
            continue
        theme_id = theme.get("id")
        if (
            not isinstance(theme_id, str)
            or not _THEME_ID.match(theme_id)
            or len(theme_group_id(theme_id)) > 80
        ):
            errors.append(f"{location}.id: lowercase kebab-case id required")
        else:
            location = f"themes[{theme_index}]({theme_id})"
            if theme_id in theme_ids:
                errors.append(f"{location}.id: duplicate theme id")
            theme_ids.add(theme_id)
        name = _text(theme.get("name"), f"{location}.name", errors)
        if name and "etf" in name.casefold():
            # The hot-group member filter treats any group name containing
            # "etf" as an ETF group.
            errors.append(f"{location}.name: must not contain 'ETF'")
        _text(theme.get("description"), f"{location}.description", errors)
        theme_from = _date(
            theme.get("valid_from"), f"{location}.valid_from", errors, required=True
        )
        theme_to = _date(
            theme.get("valid_to"), f"{location}.valid_to", errors, required=False
        )
        if theme_from and theme_to and theme_to < theme_from:
            errors.append(
                f"{location}: valid_to {theme_to.isoformat()} is before valid_from {theme_from.isoformat()}"
            )
        members = theme.get("members")
        if not isinstance(members, list) or not members:
            errors.append(f"{location}.members: at least one member required")
            continue
        seen: set[str] = set()
        for member_index, member in enumerate(members):
            errors_before = len(errors)
            instrument = member.get("instrument") if isinstance(member, dict) else None
            member_location = f"{location}.members[{member_index}]"
            if not isinstance(instrument, str) or not _INSTRUMENT.match(instrument):
                errors.append(
                    f"{member_location}.instrument: must be EXCHANGE:SYMBOL with exchange TWSE or TPEx"
                )
            else:
                member_location = f"{member_location}({instrument})"
                if instrument in seen:
                    errors.append(f"{member_location}: duplicate member in theme")
                seen.add(instrument)
            _validate_member(member, member_location, theme_from, theme_to, errors)
            if (
                len(errors) == errors_before
                and isinstance(table, str)
                and isinstance(version, str)
            ):
                encoded = membership_source(data, member)
                if len(encoded) > MEMBERSHIP_SOURCE_MAX_LENGTH:
                    errors.append(
                        f"{member_location}.evidence: stored evidence exceeds {MEMBERSHIP_SOURCE_MAX_LENGTH} characters"
                    )
    return errors


def member_period(
    theme: dict[str, Any], member: dict[str, Any]
) -> tuple[date, date | None]:
    """Effective membership period: member dates, bounded by the theme's dates."""

    start = date.fromisoformat(member.get("valid_from") or theme["valid_from"])
    end_value = member.get("valid_to") or theme.get("valid_to")
    return start, date.fromisoformat(end_value) if end_value else None


def split_instrument(value: str) -> tuple[str, str]:
    exchange, symbol = value.split(":", 1)
    return exchange, symbol
