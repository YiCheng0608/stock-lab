"""A chip row records institutional and margin provenance separately (Issue #395).

The exchanges publish the institutional file (TWSE T86) at about 18:30 Taipei
and the margin file (MI_MARGN) later, so from 2026-10-19 the 18:30 collect
wrote rows with institutional values only and the 21:30 collect filled their
margin.  Before #395 those rows kept ``source=twse_t86`` and pointed only at
the T86 capture; the margin capture was recorded only in the run's
``value_fill_groups`` (and under the T86 raw id at that).
"""

import json
from datetime import datetime

from sqlalchemy import select

import worker.chip_provenance as chip_provenance
import worker.sources as sources
from app.api import chip_dict
import test_institutional_revisions as revisions
from app.models import IngestionRun, RawPayload
from test_institutional_revisions import (
    DAY,
    FIRST,
    INITIAL,
    LATER,
    REVISED,
    Fetcher,
    chip,
    collect_at,
    reopen,
)

# The #387 fixtures: an upgraded temporary DB and no network.
database = revisions.database
no_network = revisions.no_network

T86 = sources.TWSE_CHIP_ENDPOINT
MARGIN = sources.TWSE_MARGIN_HISTORY_ENDPOINT
DAY_AS_OF = datetime(DAY.year, DAY.month, DAY.day)
GROUP_COLUMNS = (
    "institutional_source",
    "institutional_raw_payload_id",
    "institutional_data_as_of",
    "institutional_collected_at",
    "margin_source",
    "margin_raw_payload_id",
    "margin_data_as_of",
    "margin_collected_at",
)


class Feeds(Fetcher):
    """1101's T86 and MI_MARGN rows, either of which can be absent."""

    def __init__(self, t86=INITIAL, *, has_t86=True, has_margin=True, **kwargs):
        super().__init__(t86, **kwargs)
        self.has_t86, self.has_margin = has_t86, has_margin

    def __call__(self, url, **kwargs):
        payload = super().__call__(url, **kwargs)
        if url.startswith(T86) and not self.has_t86:
            return dict(payload, data=[["2330", *INITIAL]])
        if url.startswith(MARGIN) and not self.has_margin:
            # Like the 18:30 MI_MARGN: the day's individual table is empty.
            table = payload["tables"][1]
            return dict(payload, tables=[payload["tables"][0], dict(table, data=[])])
        return payload


def capture(db, endpoint, when):
    return db.scalar(
        select(RawPayload).where(
            RawPayload.endpoint.like(f"{endpoint}%"), RawPayload.collected_at == when
        )
    )


def groups(row):
    return (
        (row.institutional_source, row.institutional_raw_payload_id),
        (row.margin_source, row.margin_raw_payload_id),
    )


# --- AC-1: new rows -----------------------------------------------------------


def test_both_files_in_one_collect_point_each_group_at_its_capture(
    database, monkeypatch
):
    result = collect_at(monkeypatch, FIRST, Feeds())
    assert result["status"] == "success", result
    with database() as db:
        row = chip(db)
        t86, margin = capture(db, T86, FIRST), capture(db, MARGIN, FIRST)
        assert t86.id != margin.id
        assert groups(row) == (("twse_t86", t86.id), ("twse_margin", margin.id))
        assert (row.institutional_data_as_of, row.margin_data_as_of) == (
            DAY_AS_OF,
            DAY_AS_OF,
        )
        assert row.institutional_collected_at and row.margin_collected_at
        assert (row.foreign_buy, row.margin_balance) == (-1733324, 11242)
        # The row-level fields summarize the groups, institutional first.
        assert (row.source, row.raw_payload_id, row.data_as_of) == (
            "twse_t86+twse_margin",
            t86.id,
            DAY_AS_OF,
        )


def test_institutional_only_leaves_the_margin_group_empty(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds(has_margin=False))
    with database() as db:
        row = chip(db)
        t86 = capture(db, T86, FIRST)
        assert groups(row) == (("twse_t86", t86.id), (None, None))
        assert (row.margin_data_as_of, row.margin_collected_at) == (None, None)
        assert (row.margin_balance, row.margin_change) == (None, None)
        assert (row.source, row.raw_payload_id) == ("twse_t86", t86.id)


def test_margin_only_leaves_the_institutional_group_empty(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds(has_t86=False))
    with database() as db:
        row = chip(db)
        margin = capture(db, MARGIN, FIRST)
        assert groups(row) == ((None, None), ("twse_margin", margin.id))
        assert (row.institutional_data_as_of, row.institutional_collected_at) == (
            None,
            None,
        )
        assert (row.foreign_buy, row.trust_buy, row.dealer_buy) == (None, None, None)
        assert (row.source, row.raw_payload_id) == ("twse_margin", margin.id)


def test_margin_published_after_the_institutional_file_gets_its_own_capture(
    database, monkeypatch
):
    # B2: 18:30 has T86 only, 21:30 has both.
    collect_at(monkeypatch, FIRST, Feeds(has_margin=False))
    reopen(database)
    second = collect_at(monkeypatch, LATER, Feeds())
    with database() as db:
        row = chip(db)
        first_t86 = capture(db, T86, FIRST)
        later_margin = capture(db, MARGIN, LATER)
        assert groups(row) == (
            ("twse_t86", first_t86.id),
            ("twse_margin", later_margin.id),
        )
        assert row.margin_collected_at > row.institutional_collected_at
        assert (row.source, row.raw_payload_id) == (
            "twse_t86+twse_margin",
            first_t86.id,
        )
        assert row.collected_at == row.margin_collected_at
        fills = db.get(IngestionRun, second["run_id"]).metadata_json[
            "value_fill_groups"
        ]
    # A group the row did not have is provenance, not a fill.
    assert not [g for g in fills if g["table"] == "chip_snapshots"]


def test_institutional_file_after_margin_gets_its_own_capture(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds(has_t86=False))
    reopen(database)
    collect_at(monkeypatch, LATER, Feeds())
    with database() as db:
        row = chip(db)
        assert groups(row) == (
            ("twse_t86", capture(db, T86, LATER).id),
            ("twse_margin", capture(db, MARGIN, FIRST).id),
        )
        assert (row.source, row.raw_payload_id) == (
            "twse_t86+twse_margin",
            capture(db, T86, LATER).id,
        )


def test_a_revision_moves_only_the_institutional_group(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds(INITIAL))
    reopen(database)
    second = collect_at(monkeypatch, LATER, Feeds(REVISED))
    assert second["value_revisions"] == 1
    with database() as db:
        row = chip(db)
        assert row.trust_buy == 1133032
        assert groups(row) == (
            ("twse_t86", capture(db, T86, LATER).id),
            ("twse_margin", capture(db, MARGIN, FIRST).id),
        )
        assert row.source == "twse_t86+twse_margin"


def test_filling_a_field_of_a_group_keeps_its_capture_and_records_the_fill(
    database, monkeypatch
):
    collect_at(monkeypatch, FIRST, Feeds())
    with database() as db:
        row = chip(db)
        row.margin_balance = None  # stands in for an earlier capture without it
        db.commit()
    reopen(database)
    second = collect_at(monkeypatch, LATER, Feeds())
    with database() as db:
        row = chip(db)
        # The same MI_MARGN content in the same run is one raw row.
        assert capture(db, MARGIN, LATER) is None
        margin = capture(db, MARGIN, FIRST).id
        assert row.margin_balance == 11242
        assert row.margin_raw_payload_id == margin
        fills = db.get(IngestionRun, second["run_id"]).metadata_json[
            "value_fill_groups"
        ]
    # The fill names the margin capture, not the T86 one.
    assert [
        (g["fields"], g["raw_payload_id"], g["symbols"])
        for g in fills
        if g["table"] == "chip_snapshots"
    ] == [(["margin_balance"], margin, ["1101"])]


def test_force_points_every_changed_group_at_the_new_captures(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds())
    reopen(database)
    collect_at(monkeypatch, LATER, Feeds(margin="12000"), force=True)
    with database() as db:
        row = chip(db)
        assert row.margin_balance == 12000
        # Institutional values did not change, so that group keeps its capture.
        assert groups(row) == (
            ("twse_t86", capture(db, T86, FIRST).id),
            ("twse_margin", capture(db, MARGIN, LATER).id),
        )


def test_the_api_lists_each_group(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds(has_margin=False))
    reopen(database)
    collect_at(monkeypatch, LATER, Feeds())
    with database() as db:
        item = chip_dict(chip(db))
    assert item["source"] == "twse_t86+twse_margin"
    assert item["institutional"]["source"] == "twse_t86"
    assert item["margin"]["source"] == "twse_margin"
    assert item["institutional"]["data_as_of"] == item["margin"]["data_as_of"]
    assert item["institutional"]["collected_at"] < item["margin"]["collected_at"]
    with database() as db:
        row = chip(db)
        row.margin_source = None
        item = chip_dict(row)
    assert item["margin"] is None


# --- rows written before 0021 --------------------------------------------------


def as_before_395(row, *, source, raw_payload_id):
    """Clear the group columns and set the row-level provenance as before #395."""

    for name in GROUP_COLUMNS:
        setattr(row, name, None)
    row.source = source
    row.raw_payload_id = raw_payload_id


def test_a_row_before_0021_reads_its_groups_from_the_row_level_fields(
    database, monkeypatch
):
    collect_at(monkeypatch, FIRST, Feeds())
    with database() as db:
        row = chip(db)
        t86 = capture(db, T86, FIRST).id
        as_before_395(row, source="twse_t86+twse_margin", raw_payload_id=t86)
        item = chip_dict(row)
        assert item["institutional"]["source"] == "twse_t86"
        assert item["margin"]["source"] == "twse_margin"
        as_before_395(row, source="twse_margin", raw_payload_id=t86)
        assert chip_dict(row)["institutional"] is None
        as_before_395(row, source="twse_t86", raw_payload_id=t86)
        assert chip_dict(row)["margin"] is None


def test_a_revision_of_a_row_before_0021_keeps_its_margin_part(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds(INITIAL))
    with database() as db:
        row = chip(db)
        as_before_395(
            row,
            source="twse_t86+twse_margin",
            raw_payload_id=capture(db, T86, FIRST).id,
        )
        db.commit()
    reopen(database)
    second = collect_at(monkeypatch, LATER, Feeds(REVISED))
    assert second["value_revisions"] == 1
    with database() as db:
        row = chip(db)
        assert row.source == "twse_t86+twse_margin"
        assert row.institutional_raw_payload_id == capture(db, T86, LATER).id
        # The margin capture was never recorded; chips provenance fills it.
        assert (row.margin_source, row.margin_raw_payload_id) == ("twse_margin", None)


# --- AC-2: chips provenance fills stored rows ----------------------------------


def stored_like_1019(database, monkeypatch):
    """A 10/19-onward row as the code before #395 left it."""

    collect_at(monkeypatch, FIRST, Feeds(has_margin=False))
    reopen(database)
    second = collect_at(monkeypatch, LATER, Feeds())
    with database() as db:
        row = chip(db)
        first_t86 = capture(db, T86, FIRST)
        # 21:30's T86 is the same file, so the run reuses the 18:30 raw row.
        assert capture(db, T86, LATER) is None
        collected = row.institutional_collected_at
        as_before_395(row, source="twse_t86", raw_payload_id=first_t86.id)
        row.collected_at = collected
        # Before #395 the fill named the T86 capture the 21:30 collect used.
        run = db.get(IngestionRun, second["run_id"])
        run.metadata_json = dict(
            run.metadata_json,
            value_fill_groups=[
                {
                    "table": "chip_snapshots",
                    "exchange": "TWSE",
                    "trading_date": DAY.isoformat(),
                    "fields": ["margin_balance", "margin_change"],
                    "raw_payload_id": first_t86.id,
                    "symbols": ["1101"],
                }
            ],
        )
        db.commit()
        return first_t86.id, capture(db, MARGIN, LATER).id, collected


def test_provenance_fills_a_1019_row_from_the_fill_run(database, monkeypatch):
    t86, later_margin, collected = stored_like_1019(database, monkeypatch)
    with database() as db:
        dry = chip_provenance.fill_provenance(db)
    assert (dry["applied"], dry["rows_written"], dry["margin_fill_run"]) == (
        False,
        1,
        1,
    )
    assert dry["sources_after"].get("twse_t86+twse_margin") == 1
    with database() as db:
        assert chip(db).margin_source is None  # dry-run wrote nothing
    with database() as db:
        result = chip_provenance.fill_provenance(db, apply=True)
    assert result["status"] == "success", result
    assert (result["rows_written"], result["pending_after"]) == (1, 0)
    with database() as db:
        row = chip(db)
        margin = db.get(RawPayload, later_margin)
        assert groups(row) == (("twse_t86", t86), ("twse_margin", later_margin))
        assert (row.institutional_collected_at, row.margin_collected_at) == (
            collected,
            margin.collected_at,
        )
        assert (row.source, row.raw_payload_id, row.collected_at) == (
            "twse_t86+twse_margin",
            t86,
            max(collected, margin.collected_at),
        )
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == "chip_provenance")
        )
        assert run.records == 1 and run.metadata_json["rows_written"] == 1
    with database() as db:
        again = chip_provenance.fill_provenance(db, apply=True)
    assert (again["dates"], again.get("rows_written", 0)) == (0, 0)


def test_provenance_fills_an_older_combined_row_from_its_own_collect(
    database, monkeypatch
):
    # Before 10/19 one collect had both files; the row named both, linked T86.
    collect_at(monkeypatch, FIRST, Feeds())
    with database() as db:
        row = chip(db)
        t86, margin = capture(db, T86, FIRST).id, capture(db, MARGIN, FIRST).id
        as_before_395(row, source="twse_t86+twse_margin", raw_payload_id=t86)
        db.commit()
    with database() as db:
        result = chip_provenance.fill_provenance(db, apply=True)
    assert (result["rows_written"], result["margin_earliest_equal"]) == (1, 1)
    assert result.get("institutional_mismatch", 0) == 0
    with database() as db:
        assert groups(chip(db)) == (("twse_t86", t86), ("twse_margin", margin))
        assert chip(db).source == "twse_t86+twse_margin"


def test_provenance_keeps_a_margin_only_row_on_its_capture(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds(has_t86=False))
    with database() as db:
        row = chip(db)
        margin = capture(db, MARGIN, FIRST).id
        as_before_395(row, source="twse_margin", raw_payload_id=margin)
        db.commit()
    with database() as db:
        result = chip_provenance.fill_provenance(db, apply=True)
    assert result["status"] == "success" and result["rows_written"] == 1
    with database() as db:
        assert groups(chip(db)) == ((None, None), ("twse_margin", margin))


def test_provenance_lists_a_margin_value_no_capture_has(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds())
    with database() as db:
        row = chip(db)
        t86 = capture(db, T86, FIRST).id
        as_before_395(row, source="twse_t86", raw_payload_id=t86)
        row.margin_balance = 99999.0
        db.commit()
    with database() as db:
        result = chip_provenance.fill_provenance(db, apply=True)
    assert result["status"] == "partial"
    assert result["margin_unmatched"] == 1
    assert result["unmatched_samples"][0]["symbol"] == "1101"
    with database() as db:
        row = chip(db)
        # No capture is invented: the margin group stays empty.
        assert groups(row) == (("twse_t86", t86), (None, None))
        assert row.source == "twse_t86"


def test_provenance_stops_on_a_file_that_is_not_its_capture(database, monkeypatch):
    t86, later_margin, _ = stored_like_1019(database, monkeypatch)
    with database() as db:
        path = db.get(RawPayload, later_margin).payload_path
    with open(path, "ab") as handle:
        handle.write(b" ")
    result = chip_provenance.run_fill_provenance(apply=True)
    assert result["status"] == "failed" and "SHA-256" in result["error"]
    with database() as db:
        assert chip(db).margin_source is None


def test_provenance_reads_only_pending_rows(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Feeds())
    with database() as db:
        result = chip_provenance.fill_provenance(db, apply=True)
    assert result["dates"] == 0 and result.get("rows_written", 0) == 0


def test_the_cli_runs_provenance(database, monkeypatch, capsys):
    import worker.cli as cli

    stored_like_1019(database, monkeypatch)
    monkeypatch.setattr("sys.argv", ["worker.cli", "chips", "provenance"])
    cli.main()
    out = json.loads(capsys.readouterr().out)
    assert (out["applied"], out["rows_written"]) == (False, 1)
