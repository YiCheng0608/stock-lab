"""Provenance of a chip row's two value groups (Issue #395).

A chip row holds values from two official files: institutional flow
(foreign/trust/dealer, TWSE T86 or TPEx 3insti) and margin (TWSE MI_MARGN or
TPEx margin balance).  The exchanges publish them at different times, so a row
can get its groups from different captures.  Each group keeps its own source,
raw payload, data date and collection time; the row-level ``source``,
``raw_payload_id``, ``data_as_of`` and ``collected_at`` are a summary of them
(``summarize``).

A row written before migration 0021 has no group columns; ``stored_groups``
reads its groups from the row-level fields (``legacy_groups``) until
``worker.chip_provenance`` fills them from the stored raw captures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .domain import OFFICIAL_INSTITUTIONAL_CHIP_SOURCES, OFFICIAL_MARGIN_CHIP_SOURCES

INSTITUTIONAL = "institutional"
MARGIN = "margin"
GROUPS = (INSTITUTIONAL, MARGIN)
GROUP_FIELDS: dict[str, tuple[str, ...]] = {
    INSTITUTIONAL: ("foreign_buy", "trust_buy", "dealer_buy"),
    MARGIN: ("margin_balance", "margin_change"),
}
INSTITUTIONAL_SOURCES = frozenset(OFFICIAL_INSTITUTIONAL_CHIP_SOURCES.values())
MARGIN_SOURCES = frozenset(OFFICIAL_MARGIN_CHIP_SOURCES.values())


@dataclass(frozen=True)
class GroupProvenance:
    source: str
    raw_payload_id: int | None
    data_as_of: datetime | None
    collected_at: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "raw_payload_id": self.raw_payload_id,
            "data_as_of": self.data_as_of,
            "collected_at": self.collected_at,
        }


Groups = dict[str, GroupProvenance | None]


def has_group_columns(row: Any) -> bool:
    return bool(row.institutional_source or row.margin_source)


def explicit_groups(row: Any) -> Groups:
    groups: Groups = {}
    for group in GROUPS:
        source = getattr(row, f"{group}_source")
        groups[group] = (
            GroupProvenance(
                source,
                getattr(row, f"{group}_raw_payload_id"),
                getattr(row, f"{group}_data_as_of"),
                getattr(row, f"{group}_collected_at"),
            )
            if source
            else None
        )
    return groups


def _holds(row: Any, group: str) -> bool:
    return any(getattr(row, name) is not None for name in GROUP_FIELDS[group])


def legacy_groups(row: Any) -> Groups:
    """The groups a row written before 0021 implies from its row-level fields.

    The row-level provenance describes the first ``+`` part of ``source``.  A
    margin part after it is known by name only: until #395 its raw payload was
    not recorded, so ``raw_payload_id`` is None.  A margin value whose source
    names no margin file (a 10/19-onward row filled by a later collect) has no
    known provenance here.  A single source that is neither official file
    (a fixture) covers every group whose values the row holds.
    """

    parts = [part for part in (row.source or "").split("+") if part]
    groups: Groups = {INSTITUTIONAL: None, MARGIN: None}
    if not parts:
        return groups
    row_level = GroupProvenance(
        parts[0], row.raw_payload_id, row.data_as_of, row.collected_at
    )
    if parts[0] in MARGIN_SOURCES:
        groups[MARGIN] = row_level
        return groups
    if parts[0] not in INSTITUTIONAL_SOURCES and len(parts) == 1:
        for group in GROUPS:
            if _holds(row, group):
                groups[group] = row_level
        if not any(groups.values()):
            groups[INSTITUTIONAL] = row_level
        return groups
    groups[INSTITUTIONAL] = row_level
    margin_part = next((part for part in parts[1:] if part in MARGIN_SOURCES), None)
    if margin_part is not None:
        groups[MARGIN] = GroupProvenance(
            margin_part, None, row.data_as_of, row.collected_at
        )
    return groups


def stored_groups(row: Any) -> Groups:
    """The row's group provenance; the legacy reading for a row without columns."""

    return explicit_groups(row) if has_group_columns(row) else legacy_groups(row)


def summarize(row: Any) -> None:
    """Set the row-level provenance from the group columns.

    ``source`` joins the group sources, institutional first; ``raw_payload_id``
    and ``data_as_of`` are the institutional group's when it has one, else the
    margin group's; ``collected_at`` is the later group collection time.  A row
    with neither group keeps its row-level fields.
    """

    groups = [group for group in explicit_groups(row).values() if group is not None]
    if not groups:
        return
    row.source = "+".join(group.source for group in groups)
    row.raw_payload_id = groups[0].raw_payload_id
    row.data_as_of = groups[0].data_as_of
    times = [group.collected_at for group in groups if group.collected_at is not None]
    if times:
        row.collected_at = max(times)


def write_groups(row: Any, groups: Groups) -> None:
    """Store every group (None clears one) and refresh the row-level summary."""

    for group in GROUPS:
        provenance = groups.get(group)
        setattr(row, f"{group}_source", provenance.source if provenance else None)
        setattr(
            row,
            f"{group}_raw_payload_id",
            provenance.raw_payload_id if provenance else None,
        )
        setattr(
            row, f"{group}_data_as_of", provenance.data_as_of if provenance else None
        )
        setattr(
            row,
            f"{group}_collected_at",
            provenance.collected_at if provenance else None,
        )
    summarize(row)
