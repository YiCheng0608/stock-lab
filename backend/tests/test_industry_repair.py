from datetime import date
import sqlite3

import pytest

from worker.industry_repair import repair_memberships, run_diagnostic
from app.taxonomy import canonical_group_id


@pytest.fixture
def db():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.executescript('''
        CREATE TABLE instruments (id INTEGER PRIMARY KEY, exchange TEXT, symbol TEXT,
          industry TEXT,instrument_type TEXT,status TEXT,listing_date TEXT);
        CREATE TABLE theme_groups (id TEXT PRIMARY KEY,name TEXT,group_type TEXT,
          definition_version TEXT,source TEXT,active INTEGER,display_name_zh TEXT,
          display_description_zh TEXT,display_category TEXT,name_source TEXT,name_status TEXT);
        CREATE TABLE group_memberships (id INTEGER PRIMARY KEY,group_id TEXT,instrument_id INTEGER,
          role TEXT,confidence REAL,valid_from TEXT,valid_to TEXT,source TEXT,
          UNIQUE(group_id,instrument_id,valid_from));
        INSERT INTO instruments VALUES (1,'TPEx','3176','22','stock','active','2000-01-01');
        INSERT INTO theme_groups (id,name,group_type,active) VALUES ('old','Industry · Shipping','official_industry',1);
        INSERT INTO group_memberships VALUES (1,'old',1,'member',1,'2020-01-01',NULL,'legacy');
    ''')
    yield connection
    connection.close()


def test_preserves_history_and_has_gapless_idempotent_transition(db):
    result = repair_memberships(db,date(2026,9,13),date(2026,9,13))
    assert result['changed_by_exchange'] == {'TPEx':1}
    periods = db.execute('SELECT * FROM group_memberships ORDER BY id').fetchall()
    assert periods[0]['valid_from'] == '2020-01-01'
    assert periods[0]['valid_to'] == '2026-09-12'
    assert periods[0]['source'] == 'legacy'
    assert periods[1]['valid_from'] == '2026-09-13'
    assert periods[1]['valid_to'] is None
    assert periods[1]['group_id'] == canonical_group_id('industry','Biotechnology')
    assert repair_memberships(db,date(2026,9,13),date(2026,9,13))['changes'] == []
    assert db.execute('SELECT industry FROM instruments').fetchone()[0] == '22'


@pytest.mark.parametrize('value', ['91','garbage',None])
def test_unknown_closes_wrong_membership_without_guessing(db,value):
    db.execute('UPDATE instruments SET industry=?',(value,))
    result = repair_memberships(db,date(2026,9,13),date(2026,9,13))
    assert len(result['unresolved']) == 1
    assert db.execute('SELECT count(*) FROM group_memberships WHERE valid_to IS NULL').fetchone()[0] == 0


@pytest.mark.parametrize('start', ['2026-09-13','2026-09-14'])
def test_same_day_and_future_conflicts_are_refused_before_writes(db,start):
    db.execute('UPDATE group_memberships SET valid_from=?',(start,))
    before = list(db.iterdump())
    with pytest.raises(ValueError,match='conflict'):
        repair_memberships(db,date(2026,9,13),date(2026,9,13))
    assert list(db.iterdump()) == before


def test_unsupported_exchange_does_not_receive_text_group(db):
    db.execute("UPDATE instruments SET exchange='OTHER',industry='Biotechnology'")
    repair_memberships(db,date(2026,9,13),date(2026,9,13))
    assert db.execute('SELECT count(*) FROM group_memberships WHERE valid_to IS NULL').fetchone()[0] == 0


def test_requires_opt_in_before_reading_source(tmp_path):
    with pytest.raises(ValueError,match='explicit'):
        run_diagnostic(tmp_path/'missing.db',date(2026,9,13),date(2026,9,8))


@pytest.mark.parametrize(('name','kind','active'), [
    ('Industry · Shipping','official_industry',1),
    ('Industry · Biotechnology','etf',1),
    ('Industry · Biotechnology','official_industry',0),
])
def test_existing_correct_id_with_invalid_group_metadata_fails_before_writes(db,name,kind,active):
    correct_id = canonical_group_id('industry','Biotechnology')
    db.execute('UPDATE theme_groups SET id=?,name=?,group_type=?,active=?',(correct_id,name,kind,active))
    db.execute('UPDATE group_memberships SET group_id=?',(correct_id,))
    before = list(db.iterdump())
    with pytest.raises(ValueError,match='identity/active conflict'):
        repair_memberships(db,date(2026,9,13),date(2026,9,13))
    assert list(db.iterdump()) == before
