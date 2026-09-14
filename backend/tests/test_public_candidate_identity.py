"""Public score identities through real memory ORM, HTTP and React rendering.

Run via unittest/runpy with -B, STOCK_DB_PATH=:memory: and data/raw paths set
to an existing directory before imports. Do not load filesystem pytest fixtures.
Node uses the installed frontend dependencies and transpiles App.tsx in memory.
"""

import asyncio
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import subprocess
import unittest

from fastapi import FastAPI
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.pool import StaticPool

from app import api
from app.db import Base, enable_sqlite_foreign_keys
from app.models import GroupDailyScore, GroupMembership, IngestionRun, Instrument, ThemeGroup


ROOT = Path(__file__).resolve().parents[2]
BIG_ID = 9007199254740993


class PublicCandidateIdentityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                                    connect_args={"check_same_thread": False})
        enable_sqlite_foreign_keys(self.engine)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.source_day, self.current_day = date(2026, 9, 1), date(2026, 9, 15)
        self.group = ThemeGroup(id="g", name="g", group_type="daily_hot_group",
                                display_name_zh="Verified", name_status="verified", active=True)
        self.stocks = [Instrument(id=BIG_ID, exchange="TWSE", symbol="SAME", name="Old", status="inactive"),
                       Instrument(id=2, exchange="TPEx", symbol="SAME", name="Other")]
        self.db.add_all([self.group, *self.stocks, IngestionRun(
            run_type="collect", source="official", run_date=self.current_day,
            data_as_of=self.current_day.isoformat(), status="success")])
        self.db.flush()
        self.memberships = [GroupMembership(group_id="g", instrument_id=BIG_ID,
                                            valid_from=self.source_day, valid_to=date(2026, 9, 10)),
                            GroupMembership(group_id="g", instrument_id=2, valid_from=self.source_day)]
        self.score = GroupDailyScore(group_id="g", trading_date=self.source_day,
                                    score=80, rank=1, eligible_members=3, data_quality="complete")
        self.db.add_all([*self.memberships, self.score])
        self.persist(self.typed())

    def typed(self):
        return {"benchmark": "TAIEX", "candidate_identity_version": "instrument-id-v1",
                "candidate_symbols": [item.symbol for item in self.stocks],
                "candidate_instruments": [dict(instrument_id=item.id, exchange=item.exchange,
                                                symbol=item.symbol) for item in self.stocks]}

    def persist(self, details):
        expected = deepcopy(details)
        self.score.details_json = deepcopy(details)
        flag_modified(self.score, "details_json")
        self.db.commit()
        self.db.expire_all()
        self.db.info.clear()
        self.assertEqual(self.score.details_json, expected)
        # Python equality conflates True/1 and 2.0/2; verify the persisted JSON
        # representation and ID types before testing strict envelope rejection.
        self.assertEqual(json.dumps(self.score.details_json, sort_keys=True), json.dumps(expected, sort_keys=True))
        if isinstance(expected, dict) and isinstance(expected.get("candidate_instruments"), list):
            for actual, wanted in zip(self.score.details_json["candidate_instruments"], expected["candidate_instruments"]):
                if isinstance(wanted, dict) and "instrument_id" in wanted:
                    self.assertIs(type(actual["instrument_id"]), type(wanted["instrument_id"]))

    def product(self):
        return api.theme_detail("g", self.db)["theme"]

    def route_projections(self):
        """Exercise all public consumers with each malformed/no-score case."""
        return [api.score_dict(self.group, self.score, self.db),
                api.groups(q=None, page=1, page_size=30, limit=None, db=self.db)["items"][0],
                api.group_detail("g", self.db)["group"],
                api.themes(q=None, leaderboard=None, only_qualified=False, page=1, page_size=30, db=self.db)["items"][0],
                self.product(),
                api.theme_members("g", q=None, sort="symbol", page=1, page_size=1, db=self.db)["theme"],
                api.dashboard(db=self.db)["groups"][0], api.dashboard(db=self.db)["themes"][0]]

    def test_source_day_identity_survives_inactive_and_later_exit(self):
        result = self.product()
        self.assertEqual(result["candidate_symbols"], ["SAME", "SAME"])
        self.assertEqual(result["public_candidate_identity_version"], "instrument-id-string-v1")
        self.assertEqual(result["candidate_instruments"], [
            {"instrument_id": str(BIG_ID), "exchange": "TWSE", "symbol": "SAME"},
            {"instrument_id": "2", "exchange": "TPEx", "symbol": "SAME"}])
        self.assertEqual(result["trading_date"], "2026-09-01")
        members = api.theme_members("g", q=None, sort="symbol", page=1, page_size=1, db=self.db)
        self.assertEqual(members["meta"]["data_as_of"], "2026-09-15")
        self.assertEqual([row["exchange"] for row in members["items"]], ["TPEx"])
        self.assertEqual(members["theme"]["candidate_instruments"], result["candidate_instruments"])
        self.assertEqual(api.stock_detail("TWSE", "SAME", self.db)["instrument"]["status"], "inactive")

    def test_inclusive_source_date_and_four_ordered_string_ids(self):
        self.memberships[1].valid_to = self.source_day
        extra = [Instrument(id=3, exchange="TWSE", symbol="IPO", name="IPO", instrument_type="ipo"),
                 Instrument(id=9223372036854775807, exchange="TPEx", symbol="MAX", name="Max")]
        self.db.add_all(extra); self.db.flush()
        self.db.add_all([GroupMembership(group_id="g", instrument_id=item.id,
                                        valid_from=self.source_day, valid_to=self.source_day) for item in extra])
        details = self.typed()
        details["candidate_symbols"] += [item.symbol for item in extra]
        details["candidate_instruments"] += [dict(instrument_id=item.id, exchange=item.exchange, symbol=item.symbol) for item in extra]
        self.persist(details)
        expected = [str(BIG_ID), "2", "3", "9223372036854775807"]
        for helper in (api.score_dict, api.theme_product_dict, api.compact_group_summary, api.compact_theme_summary):
            result = json.loads(json.dumps(helper(self.group, self.score, self.db)))
            self.assertEqual([row["instrument_id"] for row in result["candidate_instruments"]], expected)
        self.assertEqual(api.theme_members("g", q=None, sort="symbol", page=1, page_size=1, db=self.db)["items"], [])

    def test_all_helpers_and_actual_http_routes(self):
        expected = self.product()["candidate_instruments"]
        for helper in (api.score_dict, api.theme_product_dict, api.compact_group_summary, api.compact_theme_summary):
            with self.subTest(helper=helper.__name__):
                self.assertEqual(helper(self.group, self.score, self.db)["candidate_instruments"], expected)
                self.assertEqual(helper(self.group, self.score)["candidate_instruments"], [])
                self.assertEqual(helper(self.group, None, self.db)["candidate_instruments"], [])
        app = FastAPI()
        app.include_router(api.router)
        async def session_override():
            return self.db
        app.dependency_overrides[api.get_db] = session_override

        async def check_routes():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://memory") as client:
                routes = [("/api/groups", lambda p: p["items"][0]),
                          ("/api/groups/g", lambda p: p["group"]),
                          ("/api/themes", lambda p: p["items"][0]),
                          ("/api/themes/g", lambda p: p["theme"]),
                          ("/api/themes/g/members?page=2&page_size=1", lambda p: p["theme"]),
                          ("/api/dashboard", lambda p: p["themes"][0]),
                          ("/api/dashboard", lambda p: p["groups"][0])]
                for path, select in routes:
                    response = await client.get(path)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(select(response.json())["candidate_instruments"], expected, path)
        # ASGI sync route functions use a worker thread with this single shared
        # memory connection; requests are serial and never open a network socket.
        asyncio.run(check_routes())

    def test_invalid_whole_envelope_never_partially_links(self):
        bad_rows = [None, [], "SAME", {}, {"instrument_id": True, "exchange": "TPEx", "symbol": "SAME"}]
        for value in [False, 0, -1, 2.0, "2", 9223372036854775808, None, 999]:
            bad_rows.append({"instrument_id": value, "exchange": "TPEx", "symbol": "SAME"})
        bad_rows += [{"instrument_id": 2, "exchange": "TWSE", "symbol": "SAME"},
                     {"instrument_id": 2, "exchange": "", "symbol": "SAME"},
                     {"instrument_id": 2, "exchange": "TPEx", "symbol": "OTHER"},
                     {"instrument_id": BIG_ID, "exchange": "TWSE", "symbol": "SAME"}]
        cases = []
        for row in bad_rows:
            details = self.typed()
            details["candidate_instruments"][1] = row
            cases.append(details)
        for key, value in [("candidate_identity_version", "future"), ("candidate_instruments", None),
                           ("candidate_instruments", {}), ("candidate_symbols", "SAME"),
                           ("candidate_symbols", ["SAME"]), ("candidate_symbols", ["SAME", None]),
                           ("candidate_symbols", ["SAME", "OTHER"])]:
            details = self.typed(); details[key] = value; cases.append(details)
        no_marker = self.typed(); no_marker.pop("candidate_identity_version"); cases.append(no_marker)
        too_many = self.typed()
        too_many["candidate_symbols"] *= 3; too_many["candidate_instruments"] *= 3; cases.append(too_many)
        for details in cases:
            with self.subTest(details=details):
                self.persist(details)
                self.assertEqual(self.product()["candidate_instruments"], [])
                self.assertEqual(api.score_dict(self.group, self.score, self.db)["candidate_instruments"], [])

    def test_source_membership_and_producer_type_gate(self):
        changes = [(self.memberships[1], "valid_from", date(2026, 9, 2)),
                   (self.memberships[1], "valid_to", date(2026, 8, 31)),
                   (self.stocks[1], "instrument_type", "index"),
                   (self.stocks[1], "symbol", "CHANGED"),
                   (self.stocks[1], "exchange", "OTHER")]
        for row, field, value in changes:
            before = getattr(row, field)
            setattr(row, field, value)
            self.db.flush()
            self.assertEqual(self.product()["candidate_instruments"], [], field)
            setattr(row, field, before); self.db.flush()
        self.group.group_type = "etf"
        self.db.flush()
        self.assertEqual(self.product()["candidate_instruments"], [])
        for item in self.stocks:
            item.instrument_type = "etf"; item.etf_category = "leveraged"
        self.db.flush()
        self.assertEqual(len(self.product()["candidate_instruments"]), 2)
        self.stocks[1].etf_category = "unclassified"; self.db.flush()
        self.assertEqual(self.product()["candidate_instruments"], [])

    def test_legacy_and_malformed_details_remain_safe_text(self):
        cases = [(None, []), ([], []), (["bad"], []), ("bad", []), (42, []),
                 ({"benchmark": "TAIEX", "candidate_symbols": ["SAME", "SAME"]}, ["SAME", "SAME"]),
                 ({"benchmark": "TAIEX", "candidate_symbols": ["SAME", {}, None, 1, " "]}, ["SAME"]),
                 ({"benchmark": "TAIEX", "candidate_symbols": {"SAME": 1}}, [])]
        for details, symbols in cases:
            with self.subTest(details=details):
                self.persist(details)
                self.assertEqual(self.product()["candidate_symbols"], symbols)
                for result in self.route_projections():
                    self.assertEqual(result["candidate_instruments"], [])
                self.assertEqual(api.group_detail("g", self.db)["group"]["candidates"], symbols)

    def test_qualification_gate_and_compact_bounds(self):
        self.score.rank = None; self.db.flush()
        self.assertEqual(self.product()["candidate_instruments"], [])
        self.assertEqual(self.product()["candidate_symbols"], [])
        self.assertEqual(len(api.score_dict(self.group, self.score, self.db)["candidate_instruments"]), 2)
        self.score.rank = 1
        self.persist({"benchmark": "TAIEX", "candidate_symbols": ["A", "B", "C", "D", "E"]})
        self.assertEqual(api.compact_group_summary(self.group, self.score, self.db)["candidates"], ["A", "B", "C", "D"])
        self.assertEqual(api.compact_theme_summary(self.group, self.score, self.db)["candidate_symbols"], ["A", "B", "C", "D"])

    def test_missing_score_detail_and_all_routes(self):
        self.db.delete(self.score); self.db.commit(); self.db.info.clear()
        self.score = None
        for result in self.route_projections():
            self.assertEqual(result["candidate_instruments"], [])
            self.assertEqual(result.get("candidate_symbols", result.get("candidates")), [])

    def test_actual_theme_page_renderer(self):
        payload = {"theme": api.theme_detail("g", self.db),
                   "members": api.theme_members("g", q=None, sort="symbol", page=1, page_size=1, db=self.db)}
        result = subprocess.run(["node", "-e", RENDERER], input=json.dumps(payload), text=True,
                                capture_output=True, cwd=ROOT, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS actual ThemePage", result.stdout)


RENDERER = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),ts=require('./frontend/node_modules/typescript');
const React=require('./frontend/node_modules/react'),{renderToStaticMarkup}=require('./frontend/node_modules/react-dom/server');
const evidence=JSON.parse(fs.readFileSync(0,'utf8'));
const source=fs.readFileSync('frontend/src/App.tsx','utf8');
const actual=source.slice(source.indexOf('function ThemeCandidateTags('),source.indexOf('\nfunction StockTable'));
assert(actual.includes('function ThemePage()'));
let entries=[], data=evidence;
const h=(type,props,...children)=>{if(props?.className==='tag symbol-tag'||props?.className==='tag') entries.push({key:props.key,to:props.to??null,text:children.join('')});return React.createElement(type,props,...children)};
const box=({children})=>React.createElement('div',null,children);
const context={React:{...React,createElement:h},useState:React.useState,useParams:()=>({themeId:'g'}),
 useQuery:({queryKey})=>({data:queryKey[0]==='theme'?data.theme:data.members}),getTheme:()=>{},getThemeMembers:()=>{},
 isTemporaryIndustryTheme:()=>false,themeMetricLabel:()=>null,formatTaiwanDateTime:x=>x,
 Link:({to,children,...props})=>React.createElement('a',{href:to,...props},children),PageTitle:box,Term:box,
 ThemeMemberTable:()=>null,DirectoryPagination:()=>null,QualityBadge:()=>null};
vm.createContext(context);
vm.runInContext(ts.transpileModule(actual,{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020}}).outputText,context);
function render(theme=evidence.theme.theme,items=evidence.members.items,total=1){
 data={theme:{...evidence.theme,theme},members:{...evidence.members,items,meta:{...evidence.members.meta,total}}};
 entries=[];const html=renderToStaticMarkup(React.createElement(context.ThemePage));return {html,entries};
}
const initial=render();
assert.deepStrictEqual(initial.entries.map(x=>x.to),['/stocks/TWSE/SAME','/stocks/TPEx/SAME']);
assert.deepStrictEqual(initial.entries.map(x=>x.key),['9007199254740993:0','2:1']);
assert.deepStrictEqual(initial.entries.map(x=>x.text),['TWSE SAME','TPEx SAME']);
assert(initial.html.includes('2026-09-01')); assert(initial.html.includes('2026-09-15'));
assert(initial.html.indexOf('2026-09-01')<initial.html.indexOf('2026-09-15'));
assert.deepStrictEqual(render(undefined,[],99).entries,initial.entries);
const typed=evidence.theme.theme;
for(const bad of [null,{},[],{instrument_id:'2',exchange:'TWSE',symbol:'OTHER'},
 {instrument_id:9007199254740993,exchange:'TPEx',symbol:'SAME'},
 {instrument_id:'9223372036854775808',exchange:'TPEx',symbol:'SAME'}]){
 const theme={...typed,candidate_instruments:[typed.candidate_instruments[0],bad]};
 assert(render(theme).entries.every(x=>x.to===null));
}
for(const theme of [{...typed,public_candidate_identity_version:'future'},
 {...typed,candidate_instruments:undefined,public_candidate_identity_version:undefined},
 {...typed,candidate_symbols:['SAME',{},null]}]){
 const result=render(theme); assert(result.entries.every(x=>x.to===null));
 assert.equal(new Set(result.entries.map(x=>x.key)).size,result.entries.length);
}
for(const symbols of [null,{},'SAME']) assert.equal(render({...typed,candidate_symbols:symbols}).entries.length,0);
console.log('PASS actual ThemePage: exact string IDs, distinct markets/keys, source date, pagination-independent links, malformed/legacy no links');
"""


if __name__ == "__main__":
    unittest.main()
