"""Store the TPEx emerging-market roster collect fetched (Issue #512).

The roster only names AI news candidates that are not listed or OTC
instruments (``app.api.news_ai_map``); nothing else reads it.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from app.models import EmergingIssuer

from .sources import EmergingIssuerRecord, emerging_issuer_warning


def store_emerging_issuers(
    db: Session,
    records: list[EmergingIssuerRecord],
    raw_id: Callable[[str | None], int | None],
    warnings: list[str],
) -> dict[str, int]:
    """collect's write step; a failure becomes a non-core warning and writes nothing.

    A row moves to the record's roster (name, 資料日期, raw) unless it already
    holds a newer roster, so re-collecting an older day never rolls a name back.
    Codes the roster leaves out keep their row and older ``as_of_date``.
    """

    if not records:
        return {}
    counts: dict[str, int] = {}
    try:
        with db.begin_nested():
            for record in records:
                identifier = raw_id(record.payload_sha256)
                if identifier is None:
                    raise ValueError(
                        f"no raw payload for the roster row {record.symbol}"
                    )
                row = db.get(EmergingIssuer, record.symbol)
                if row is None:
                    db.add(
                        EmergingIssuer(
                            symbol=record.symbol,
                            name=record.name,
                            market="emerging",
                            as_of_date=record.as_of_date,
                            raw_payload_id=identifier,
                        )
                    )
                    outcome = "inserted"
                elif row.as_of_date > record.as_of_date:
                    outcome = "older"
                elif (row.name, row.as_of_date) == (record.name, record.as_of_date):
                    outcome = "unchanged"
                else:
                    row.name = record.name
                    row.as_of_date = record.as_of_date
                    row.raw_payload_id = identifier
                    outcome = "updated"
                counts[outcome] = counts.get(outcome, 0) + 1
            db.flush()
    except Exception as exc:
        warnings.append(emerging_issuer_warning(exc))
        return {"failed": len(records)}
    return counts
