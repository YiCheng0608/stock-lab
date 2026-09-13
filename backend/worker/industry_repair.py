"""Opt-in taxonomy diagnostics; every writable database is a new Temp copy.

Run via ``python -m worker.industry_repair --source PATH --evidence-date DATE
--market-date DATE --confirm-isolated-diagnostic``. There is deliberately no
output/target database argument and no in-place repair mode. Historical raw
industry truth is unavailable: the market-date scenario is counterfactual.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from app.taxonomy import canonical_group_id, canonical_industry_label, INDUSTRY_DISPLAY_ZH


NAMESPACE = "taxonomy-diagnostic-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(db, sql, args=()):
    return [dict(row) for row in db.execute(sql, args)]


def connection(path: Path, *, readonly=False):
    db = sqlite3.connect(path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def table_hashes(path: Path):
    with connection(path, readonly=True) as db:
        result = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted = '"' + name.replace('"', '""') + '"'
            serialized = sorted(json.dumps(list(row), ensure_ascii=False, default=str) for row in db.execute(f"SELECT * FROM {quoted}"))
            result[name] = hashlib.sha256("\n".join(serialized).encode()).hexdigest()
        return result


def repair_memberships(db, effective_date: date, evidence_date: date):
    """Transaction-owned by caller. Preserve old rows; refuse ambiguous periods."""
    day = effective_date.isoformat()
    previous = (effective_date - timedelta(days=1)).isoformat()
    changes, unresolved = [], []
    instruments = rows(db, "SELECT * FROM instruments WHERE instrument_type IN ('stock','ipo') AND status='active' ORDER BY id")
    plans = []
    for instrument in instruments:
        raw_code = str(instrument['industry'] or '').strip()
        # Text aliases remain useful to old fixtures, but are not feed evidence.
        label = canonical_industry_label(instrument['exchange'], raw_code) if raw_code.isascii() and raw_code.isdigit() else None
        expected = canonical_group_id('industry', label) if label else None
        if expected:
            group = db.execute('SELECT name,group_type,active FROM theme_groups WHERE id=?', (expected,)).fetchone()
            if group and (group['name'] != f'Industry · {label}' or group['group_type'] != 'official_industry' or not group['active']):
                raise ValueError(f'canonical group identity/active conflict: {expected}')
        existing = rows(db, """SELECT m.* FROM group_memberships m JOIN theme_groups g ON g.id=m.group_id
            WHERE m.instrument_id=? AND g.group_type='official_industry'
            AND (m.valid_to IS NULL OR m.valid_to>=?) ORDER BY m.id""", (instrument['id'], day))
        if any(m['valid_from'] > day for m in existing):
            raise ValueError(f"future membership conflict: {instrument['exchange']}:{instrument['symbol']}")
        correct = [m for m in existing if m['group_id'] == expected]
        wrong = [m for m in existing if m['group_id'] != expected]
        if len(correct) > 1 or any(m['valid_from'] >= day for m in wrong):
            raise ValueError(f"same-day/duplicate membership conflict: {instrument['exchange']}:{instrument['symbol']}")
        if instrument['listing_date'] and instrument['listing_date'] > day:
            if existing:
                raise ValueError('membership before listing')
            continue
        if not label:
            unresolved.append({key: instrument[key] for key in ('id','exchange','symbol','industry')} |
                              {'reason':'unsupported_or_unknown_official_industry', 'action':'close_existing_without_replacement'})
        plans.append((instrument, label, expected, correct, wrong))
    # Validate all intervals before the first write.
    for instrument, label, expected, correct, wrong in plans:
        for membership in wrong:
            db.execute('UPDATE group_memberships SET valid_to=? WHERE id=?', (previous, membership['id']))
        if expected and not correct:
            group = db.execute('SELECT name,group_type FROM theme_groups WHERE id=?', (expected,)).fetchone()
            if group and (group['name'] != f'Industry · {label}' or group['group_type'] != 'official_industry'):
                raise ValueError(f'canonical group identity conflict: {expected}')
            db.execute("""INSERT OR IGNORE INTO theme_groups
                (id,name,group_type,definition_version,source,active,display_name_zh,
                 display_description_zh,display_category,name_source,name_status)
                VALUES (?,?, 'official_industry','taxonomy-diagnostic-v1',?,1,?,?,'股票族群',?,'official')""",
                (expected, f'Industry · {label}', 'TWSE/TPEx official classification', INDUSTRY_DISPLAY_ZH[label],
                 '隔離分類驗證；非歷史分類真值。', f'classification evidence {evidence_date}'))
            db.execute('UPDATE theme_groups SET active=1 WHERE id=?', (expected,))
            db.execute("""INSERT INTO group_memberships
                (group_id,instrument_id,role,confidence,valid_from,valid_to,source)
                VALUES (?,?,'member',1.0,?,NULL,?)""",
                (expected, instrument['id'], day,
                 f'TWSE/TPEx official OpenAPI; exchange={instrument["exchange"]}; taxonomy-diagnostic; evidence_at={evidence_date}; effective={day}'))
        if wrong or (expected and not correct):
            changes.append({key: instrument[key] for key in ('id','exchange','symbol','industry')} |
                           {'closed': wrong, 'new_group_id': expected if not correct else None, 'label': label})
    return {'changes': changes, 'unresolved': unresolved,
            'changed_by_exchange': dict(Counter(item['exchange'] for item in changes))}


def projection(path: Path, market_date: date):
    with connection(path, readonly=True) as db:
        scores = rows(db, 'SELECT * FROM group_daily_scores WHERE trading_date=? ORDER BY group_id', (str(market_date),))
        signals = rows(db, 'SELECT * FROM signals WHERE signal_key LIKE ? ORDER BY signal_key', (NAMESPACE+'-%',))
        for item in scores:
            item.pop('id', None)
        for item in signals:
            for key in ('id', 'created_at'):
                item.pop(key, None)
        return {'scores': scores, 'signals': signals}


def original_signals(path: Path):
    with connection(path, readonly=True) as db:
        return rows(db, 'SELECT * FROM signals WHERE signal_key NOT LIKE ? ORDER BY id', (NAMESPACE+'-%',))


def run_models(path: Path, market_date: date):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from worker.pipeline import _calculate_group_scores, _ensure_strategies, _generate_signals
    engine = create_engine('sqlite:///'+path.as_posix())
    try:
        with Session(engine) as db:
            _calculate_group_scores(db, market_date)
            db.flush()
            strategies = _ensure_strategies(db)
            count = _generate_signals(db, market_date, strategies, namespace=NAMESPACE, data_cutoff=market_date)
            db.commit()
        return count
    finally:
        engine.dispose()


def compare(before, after, key):
    left, right = ({row[key]: row for row in side} for side in (before, after))
    return [{'key': identity, 'before': left.get(identity), 'after': right.get(identity)}
            for identity in sorted(left.keys() | right.keys()) if left.get(identity) != right.get(identity)]


def run_diagnostic(source: Path, evidence_date: date, market_date: date, *, confirmed=False):
    if not confirmed:
        raise ValueError('explicit --confirm-isolated-diagnostic required')
    source = source.resolve(strict=True)
    if evidence_date < market_date:
        raise ValueError('evidence date must not precede market snapshot')
    code_paths = (Path(__file__), Path(__file__).parents[1]/'app'/'taxonomy.py', Path(__file__).with_name('pipeline.py'))
    code_hashes = {str(path):sha256(path) for path in code_paths}
    fixture_path = Path(__file__).parents[1]/'tests'/'fixtures'/'official_industry_codes.json'
    classification_contract = json.loads(fixture_path.read_text(encoding='utf-8'))
    fixture_hash = sha256(fixture_path)
    # No caller-controlled destination. mkdtemp atomically creates a new directory.
    root = Path(tempfile.mkdtemp(prefix='stock-taxonomy-diagnostic-')).resolve()
    print(f'diagnostic directory: {root}', flush=True)
    backup = root / 'source-snapshot.db'
    source_before = sha256(source)
    with connection(source, readonly=True) as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    baseline_hashes = table_hashes(backup)
    with connection(backup, readonly=True) as db:
        actual_market_date = db.execute('SELECT max(trading_date) FROM market_bars').fetchone()[0]
        if actual_market_date != str(market_date):
            raise ValueError(f'market date must equal snapshot max {actual_market_date}')
        if db.execute('SELECT 1 FROM signals WHERE signal_key LIKE ? LIMIT 1', (NAMESPACE+'-%',)).fetchone():
            raise ValueError('source already contains diagnostic namespace')
    # Set every default before importing app.config or pipeline; never init_db.
    os.environ['STOCK_DATA_DIR'] = str(root / 'runtime')
    os.environ['STOCK_RAW_DIR'] = str(root / 'runtime' / 'raw')
    os.environ['STOCK_DB_PATH'] = str(root / 'unused-default.db')
    prepared = root / 'schema-baseline.db'
    shutil.copyfile(backup, prepared)
    from sqlalchemy import create_engine, text
    from app.migrations import upgrade_database
    engine = create_engine('sqlite:///'+prepared.as_posix())
    migration_result = upgrade_database(engine)
    with engine.connect() as db:
        version_table = db.execute(text("SELECT name FROM sqlite_master WHERE name='alembic_version'")).scalar()
        head = db.execute(text('SELECT version_num FROM alembic_version')).scalars().all() if version_table else []
        fallback_table = db.execute(text("SELECT name FROM sqlite_master WHERE name='schema_migrations'")).scalar()
        fallback_versions = db.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars().all() if fallback_table else []
    engine.dispose()
    prepared_hashes = table_hashes(prepared)
    baseline = root / 'counterfactual-baseline.db'
    corrected = root / 'counterfactual-corrected.db'
    current = root / 'current-evidence-date.db'
    for path in (baseline, corrected, current):
        shutil.copyfile(prepared, path)
    with connection(current) as db:
        current_changes = repair_memberships(db, evidence_date, evidence_date)
    with connection(corrected) as db:
        counterfactual_changes = repair_memberships(db, market_date, evidence_date)
    # A second application must be semantically idempotent.
    for path, day in ((current, evidence_date), (corrected, market_date)):
        first = table_hashes(path)
        with connection(path) as db:
            repeated = repair_memberships(db, day, evidence_date)
        if repeated['changes'] or table_hashes(path) != first:
            raise AssertionError('membership repair is not idempotent')
    counts = {}
    for name, path in (('baseline',baseline), ('corrected',corrected)):
        print(f'calculating {name}', flush=True)
        counts[name] = run_models(path, market_date)
    left, right = projection(baseline, market_date), projection(corrected, market_date)
    print('checking corrected model rerun', flush=True)
    run_models(corrected, market_date)
    if projection(corrected, market_date) != right:
        raise AssertionError('model rerun changed semantic projection')
    protected = set(prepared_hashes) - {'theme_groups','group_memberships','group_daily_scores','signals','strategy_versions'}
    invariants = {}
    for path in (baseline, corrected, current):
        after = table_hashes(path)
        unchanged = all(after.get(name) == prepared_hashes[name] for name in protected)
        preserved = original_signals(path) == original_signals(prepared)
        if not unchanged or not preserved:
            raise AssertionError(f'protected inputs/history changed: {path.name}')
        with connection(path, readonly=True) as db:
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            foreign_keys = [list(row) for row in db.execute('PRAGMA foreign_key_check')]
        if integrity != 'ok' or foreign_keys:
            raise AssertionError('database integrity failed')
        invariants[path.name] = {'protected_table_hashes_unchanged': unchanged, 'original_signals_unchanged':preserved,
                                 'integrity_check':integrity,'foreign_key_check':foreign_keys, 'table_hashes':after}
    if table_hashes(current)['group_daily_scores'] != prepared_hashes['group_daily_scores']:
        raise AssertionError('current-date copy rewrote historical scores')
    source_after = sha256(source)
    if source_after != source_before:
        raise AssertionError('source changed during diagnostic; discard result and inspect external writer')
    if {str(path):sha256(path) for path in code_paths} != code_hashes or sha256(fixture_path) != fixture_hash:
        raise AssertionError('implementation or classification fixture changed during diagnostic')
    report = {'mode':'isolated_diagnostic_only', 'classification_evidence_at':str(evidence_date),
              'market_data_as_of':str(market_date), 'current_membership_effective_date':str(evidence_date),
              'counterfactual_membership_effective_date':str(market_date), 'source_path':str(source),
              'source_sha256_before':source_before,'source_sha256_after':source_after,'alembic_head':head,
              'migration_result':migration_result,
              'migration_mode':'alembic' if head else 'compatibility_fallback', 'schema_migration_versions':fallback_versions,
              'classification_evidence_precision':'date_only_review_date', 'classification_contract':classification_contract,
              'classification_contract_sha256':fixture_hash,
              'source_snapshot_table_hashes':baseline_hashes,'prepared_table_hashes':prepared_hashes,
              'migration_changed_tables':[name for name in prepared_hashes if prepared_hashes[name] != baseline_hashes.get(name)],
              'current':current_changes,'counterfactual':counterfactual_changes,'invariants':invariants,
              'model_instrument_counts':counts, 'model_rerun_semantically_identical':True,
              'score_differences':compare(left['scores'],right['scores'],'group_id'),
              'signal_differences':compare(left['signals'],right['signals'],'signal_key'),
              'limitations':['Current scenario interprets legacy snapshot raw codes using current code tables; NOT fresh company classification truth.',
                             'Market-date corrected scenario uses current industry codes: NOT point-in-time truth.',
                             'Historical memberships, scores, signals, evaluations and news remain unverified.',
                             'Current-date scenario does not recompute historical scores.',
                             'No trading, production repair, API or frontend verification is claimed.'],
              'files':{path.name:sha256(path) for path in (backup,prepared,baseline,corrected,current)},
              'code_sha256':code_hashes}
    for name, payload in (('baseline-projection.json',left),('corrected-projection.json',right),('report.json',report)):
        (root/name).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(root/'report.json'),'changed_memberships':current_changes['changed_by_exchange'],
                      'score_differences':len(report['score_differences']),'signal_differences':len(report['signal_differences'])}),flush=True)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--evidence-date',type=date.fromisoformat,required=True)
    parser.add_argument('--market-date',type=date.fromisoformat,required=True)
    parser.add_argument('--confirm-isolated-diagnostic',action='store_true')
    args = parser.parse_args()
    run_diagnostic(args.source,args.evidence_date,args.market_date,confirmed=args.confirm_isolated_diagnostic)


if __name__ == '__main__':
    main()
