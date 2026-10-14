#!/usr/bin/env python
"""Issue 39 QA runner: one sealed real acquisition of the seven-stock flow/volume source.

DRAFT for the independent QA session. It is written and self-tested against canned
bytes only; it has never made a request. Running it for real spends the one-shot
quota (15 GET to api.finmindtrade.com) and needs, outside this repository:

  * the global-generated canonical policy bytes and their SHA-256 (the product's
    POLICY_SHA256/POLICY_BYTES must already carry that pin),
  * the global seal raw (a JSON object, see SEAL_KEYS) and its SHA-256 pin,
  * the seal comment URL on Issue 39 and the QA's own session id / model / effort,
    which the QA reads back from its own runtime (this script cannot verify them).

Usage (after reading the product, the stage-1 consumer and this file):
  python -B -X utf8 tools/issue39_flow_volume_ratio_qa.py \\
      --policy-file P --policy-sha256 H --seal-file S --seal-sha256 H \\
      --seal-url https://github.com/YiCheng0608/stock-lab/issues/39#issuecomment-N \\
      --holder-session UUID --model MODEL --effort xhigh [--real]

Without ``--real`` it stops after the offline pre-flight and prints it (no import of
the product, no request). With ``--real`` it installs the cooperative guard, runs the
batch exactly once, verifies it with an independent oracle that does not call the
product's parsers, admits the snapshot, checks the 14 ratios against exact integer
rational arithmetic, probes post-acquisition refusals, releases and cleans up.

The oracle below re-implements every expectation from the pinned formal blob and the
raw bytes; the only things taken from the product are the captured bytes/receipts and
the values it produced, which are what is being checked.

Exit 0 only when pre-flight, acquisition, oracle, admission, 14/14 ratios, refusal
probes and cleanup all pass. Any failure after the first GET is final (NO-RETRY).
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PRODUCT_FILE = BACKEND / "app" / "institutional_flow_ratio_source.py"
CONSUMER_FILE = BACKEND / "app" / "institutional_flow_ratio.py"

# Expectations are typed here, not imported from the product.
HOST = "api.finmindtrade.com"
NAMESPACE = "issue39-seven-flow-to-volume-ratio-two-cutoffs-v1/qa1"
SEAL_VERSION = "issue39-financial-start-v1"
FORMAL_BLOB = "116bfab818fc5f72a650573c611d62b662372026:docs/SOURCE_REGISTRY.md"
FORMAL_SHA256 = "f27024ba1f4d5874610e3446cae34401dbeab4ea485706704e78cd4ef3844240"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
CUTOFFS = ("2026-10-05", "2026-10-06")
NAMES = ("Foreign_Investor", "Foreign_Dealer_Self", "Investment_Trust", "Dealer_self", "Dealer_Hedging")
SEAL_KEYS = ("version", "issuer_thread_id", "coordinator_session_ids", "implementer_session_ids",
             "namespace", "policy_sha256", "valid_from_utc", "valid_until_utc", "authorized", "whole_batch")
_QUERY = "start_date=2026-09-01&end_date=2026-10-06"
URLS = ([f"https://{HOST}/api/v4/data?dataset=TaiwanStockTradingDate&{_QUERY}"]
        + [f"https://{HOST}/api/v4/data?dataset=TaiwanStockPrice&data_id={s}&{_QUERY}" for s in SYMBOLS]
        + [f"https://{HOST}/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={s}&{_QUERY}" for s in SYMBOLS])
INT64 = 9223372036854775807
THRESHOLD = Fraction(-3, 1000)
BATCH_SECONDS = 180


# --- independent reading of the pinned formal blob ------------------------------------------


def _section(text, heading):
    match = re.search(r"^" + re.escape(heading) + r"[^\n]*\n", text, re.M)
    if match is None:
        raise ValueError("formal section missing: " + heading)
    level = len(heading) - len(heading.lstrip("#"))
    tail = text[match.end():]
    stop = re.search(r"^#{1," + str(level) + r"} ", tail, re.M)
    return tail[:stop.start()] if stop else tail


def read_formal(blob):
    """(24 formal days, {symbol: 2026-10-06 volume}, {(cutoff, symbol): (foreign, trust, dealer, total)})."""
    if hashlib.sha256(blob).hexdigest() != FORMAL_SHA256:
        raise ValueError("formal blob does not match the pinned SHA-256")
    text = blob.decode("utf-8")
    calendar = _section(text, "### 31.2")
    days = []
    for label, month in (("Sep20", 9), ("Oct4", 10)):
        found = re.search(r"^- " + label + r"：[^/]+/([^。]+)。", calendar, re.M)
        days += ["2026-%02d-%02d" % (month, int(part)) for part in found.group(1).split("、")]
    volumes = {}
    for line in _section(text, "### 32.2").splitlines():
        found = re.fullmatch(r"\| (\d{4}) \| ([^|]+) \| ([0-9]+)／[^|]+ \| ([0-9]+) \|", line)
        if found:
            volumes[found.group(1)] = int(found.group(3))
    nets, cutoff = {}, None
    for line in _section(text, "### 47.6").splitlines():
        head = re.fullmatch(r"\| (2026-10-0[56]) \|[^|]*\|[^|]*\|[^|]*\|[^|]*\|", line)
        if head:
            cutoff = head.group(1)
            continue
        row = re.fullmatch(r"\| (\d{4}) \| (-?[0-9,]+) \| (-?[0-9,]+) \| (-?[0-9,]+) \| (-?[0-9,]+) \|", line)
        if row and cutoff:
            nets[(cutoff, row.group(1))] = tuple(int(part.replace(",", "")) for part in row.groups()[1:])
    ok = (len(days) == 24 and len(set(days)) == 24 and days == sorted(days)
          and tuple(volumes) == SYMBOLS and len(nets) == 14
          and all(v[0] + v[1] + v[2] == v[3] for v in nets.values()))
    if not ok:
        raise ValueError("formal blob does not yield the expected 24 days / 7 volumes / 14x4 nets")
    return tuple(days), volumes, nets


# --- independent oracle ---------------------------------------------------------------------


def _strict_json(body):
    if body.startswith(b"\xef\xbb\xbf"):
        raise ValueError("BOM")
    text = body.decode("utf-8")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key " + key)
            result[key] = value
        return result

    def refuse(token):
        raise ValueError("non-finite " + token)

    return json.loads(text, object_pairs_hook=pairs, parse_constant=refuse, parse_float=Decimal)


def _is_int(value, *, positive):
    return type(value) is int and 0 <= value <= INT64 and (value > 0 or not positive)


def _receipt_sha256(receipt):
    return hashlib.sha256(json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def oracle(captures, formal):
    """Re-derive everything from the raw captured bytes. Returns a dict; ``mismatches`` empty means pass."""
    days, volume_anchors, net_anchors = formal
    mismatches = []

    def expect(condition, label):
        if not condition:
            mismatches.append(label)

    expect(len(captures) == 15, "capture_count")
    documents = []
    for index, capture in enumerate(captures[:15]):
        receipt, body = capture.receipt, capture.body
        expect(receipt.url == URLS[index], "receipt_url[%d]" % index)
        expect(receipt.method == "GET" and receipt.status == 200 and receipt.full_eof is True, "receipt_status[%d]" % index)
        expect(receipt.body_bytes == len(body) and receipt.body_sha256 == hashlib.sha256(body).hexdigest(), "receipt_body[%d]" % index)
        expect(re.fullmatch(r"application/json(?:\s*;\s*charset=utf-8)?", receipt.content_type.strip(), re.I) is not None, "content_type[%d]" % index)
        expect(receipt.content_encoding == "identity" and receipt.namespace == NAMESPACE, "receipt_scope[%d]" % index)
        try:
            documents.append(_strict_json(body))
        except (ValueError, UnicodeError):
            documents.append(None)
            expect(False, "json[%d]" % index)
    if mismatches:
        return {"mismatches": mismatches}

    def shell(document):
        return (type(document) is dict and set(document) == {"status", "msg", "data"} and document["status"] == 200
                and document["msg"] == "success" and type(document["data"]) is list)

    # calendar
    expect(shell(documents[0]), "calendar_shell")
    rows = documents[0]["data"] if shell(documents[0]) else []
    expect(all(type(r) is dict and set(r) == {"date"} and type(r["date"]) is str for r in rows), "calendar_rows")
    observed = [r["date"] for r in rows if type(r) is dict and type(r.get("date")) is str]
    expect(observed == sorted(set(observed)), "calendar_order")
    in_window = tuple(d for d in observed if "2026-09-01" <= d <= "2026-10-06")
    expect(in_window == days, "calendar_equals_formal_24")

    prices, flows = {}, {}
    price_rows = price_fields = flow_rows = flow_fields = volume_hits = net_hits = 0
    for number, symbol in enumerate(SYMBOLS):
        document = documents[1 + number]
        expect(shell(document) and len(document["data"]) == 24, "price_shell[%s]" % symbol)
        by_day = {}
        for row in document["data"] if shell(document) else []:
            required = {"date", "stock_id", "open", "max", "min", "close", "Trading_Volume", "Trading_money"}
            if not (type(row) is dict and required <= set(row) <= required | {"spread", "Trading_turnover"}):
                expect(False, "price_fields[%s]" % symbol)
                continue
            o, h, l, c = (row[k] for k in ("open", "max", "min", "close"))
            numeric = all(type(x) in (int, Decimal) and Decimal(x).is_finite() and Decimal(x) > 0 for x in (o, h, l, c))
            expect(numeric and Decimal(h) >= max(Decimal(o), Decimal(l), Decimal(c))
                   and Decimal(l) <= min(Decimal(o), Decimal(h), Decimal(c)), "ohlc[%s]" % symbol)
            expect(row["stock_id"] == symbol and row["date"] in days and row["date"] not in by_day, "price_identity[%s]" % symbol)
            expect(_is_int(row["Trading_Volume"], positive=True) and _is_int(row["Trading_money"], positive=True), "price_integers[%s]" % symbol)
            by_day[row["date"]] = row
            price_rows += 1
            price_fields += 6
        expect(tuple(sorted(by_day)) == days, "price_dates[%s]" % symbol)
        prices[symbol] = tuple(by_day[d]["Trading_Volume"] for d in days if d in by_day)
        if "2026-10-06" in by_day:
            hit = by_day["2026-10-06"]["Trading_Volume"] == volume_anchors[symbol]
            expect(hit, "volume_anchor[%s]" % symbol)
            volume_hits += int(hit)

        document = documents[8 + number]
        expect(shell(document) and len(document["data"]) == 120, "flow_shell[%s]" % symbol)
        nets = {}
        for row in document["data"] if shell(document) else []:
            if not (type(row) is dict and set(row) == {"date", "stock_id", "buy", "sell", "name"}):
                expect(False, "flow_fields[%s]" % symbol)
                continue
            valid = (row["stock_id"] == symbol and row["name"] in NAMES and row["date"] in days
                     and (row["date"], row["name"]) not in nets
                     and _is_int(row["buy"], positive=False) and _is_int(row["sell"], positive=False))
            expect(valid, "flow_row[%s]" % symbol)
            if valid:
                nets[(row["date"], row["name"])] = (row["buy"], row["sell"])
                flow_rows += 1
                flow_fields += 2
        expect(set(nets) == {(d, n) for d in days for n in NAMES}, "flow_complete[%s]" % symbol)
        flows[symbol] = nets
        for cutoff in CUTOFFS:
            if set(nets) != {(d, n) for d in days for n in NAMES}:
                continue
            window = [d for d in days if d <= cutoff][-5:]
            net = lambda name: sum(nets[(d, name)][0] - nets[(d, name)][1] for d in window)
            derived = (net("Foreign_Investor"), net("Investment_Trust"), net("Dealer_self") + net("Dealer_Hedging"))
            derived += (sum(derived),)
            hit = derived == net_anchors[(cutoff, symbol)]
            expect(hit, "net_anchor[%s,%s]" % (cutoff, symbol))
            net_hits += 4 * int(hit)

    ratios = {}
    if not mismatches:
        for symbol in SYMBOLS:
            for cutoff in CUTOFFS:
                position = days.index(cutoff)
                window20 = prices[symbol][position - 19:position + 1]
                nets = net_anchors[(cutoff, symbol)]
                ratio = Fraction(nets[3] * 20, sum(window20))
                ratios[(symbol, cutoff)] = {
                    "nets": nets, "volume_sum": sum(window20), "ratio": ratio,
                    "gate": ratio >= THRESHOLD, "window20": window20}
    return {
        "mismatches": mismatches, "days": days, "prices": prices, "flows": flows, "ratios": ratios,
        "admission": {"calendar_rows": len(in_window), "price_rows": price_rows, "price_fields": price_fields,
                      "flow_rows": flow_rows, "flow_fields": flow_fields,
                      "volume_anchor_fields": volume_hits, "net_anchor_fields": net_hits},
        "receipt_sha256s": tuple(_receipt_sha256(c.receipt) for c in captures),
    }


# --- cooperative guard (real runs only) -----------------------------------------------------


def install_guard():
    """Audit-hook guard: only api.finmindtrade.com:443, no process launch, no disk write. Not a sandbox."""
    stats = {"resolve_ok": 0, "connect_ok": 0, "blocked": 0}

    def audit(event, args):
        if event == "socket.getaddrinfo":
            if args[0] == HOST and args[1] in (443, "443"):
                stats["resolve_ok"] += 1
                return
            stats["blocked"] += 1
            raise AssertionError("guard: resolve " + str(args[0]))
        if event in ("socket.connect", "socket.connect_ex", "socket.bind", "socket.sendto"):
            address = args[1]
            # Port 443 only, and only after the allowed host was resolved. Several connects per resolve
            # are legitimate (a dual-stack host may try a second address), so they are counted, not paired.
            if event == "socket.connect" and isinstance(address, tuple) and address[1:2] == (443,) \
                    and stats["resolve_ok"] > 0:
                stats["connect_ok"] += 1
                return
            stats["blocked"] += 1
            raise AssertionError("guard: " + event)
        if event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn"):
            stats["blocked"] += 1
            raise AssertionError("guard: process launch")
        if event == "open":
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(letter in mode for letter in "wax+")) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                stats["blocked"] += 1
                raise AssertionError("guard: disk write")
        if event in ("os.mkdir", "os.remove", "os.rename", "os.rmdir", "os.truncate", "shutil.copyfile", "shutil.move"):
            stats["blocked"] += 1
            raise AssertionError("guard: " + event)

    sys.addaudithook(audit)
    return stats


# --- pre-flight (offline) -------------------------------------------------------------------


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def read_formal_blob():
    return git("cat-file", "blob", FORMAL_BLOB)


def parse_seal(raw, pin, now):
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError("seal does not match its pin")
    seal = json.loads(raw.decode("utf-8"))
    if type(seal) is not dict or set(seal) != set(SEAL_KEYS):
        raise ValueError("seal keys")
    start = datetime.fromisoformat(seal["valid_from_utc"].replace("Z", "+00:00"))
    stop = datetime.fromisoformat(seal["valid_until_utc"].replace("Z", "+00:00"))
    if not start <= now <= stop:
        raise ValueError("seal is outside its validity window")
    if (seal["version"], seal["namespace"]) != (SEAL_VERSION, NAMESPACE):
        raise ValueError("seal scope")
    return seal


def preflight(args, now=None):
    now = now or datetime.now(timezone.utc)
    problems = []
    candidate = git("rev-parse", "HEAD").decode().strip()
    if git("status", "--porcelain", "--untracked-files=all").strip():
        problems.append("working tree is not clean")
    policy = Path(args.policy_file).read_bytes()
    if hashlib.sha256(policy).hexdigest() != args.policy_sha256:
        problems.append("policy bytes do not match --policy-sha256")
    seal = parse_seal(Path(args.seal_file).read_bytes(), args.seal_sha256, now)
    if seal["policy_sha256"] != args.policy_sha256:
        problems.append("seal policy_sha256 differs from the policy pin")
    # The pins live in the product source (read as text here; the product is not imported before the guard).
    source = PRODUCT_FILE.read_text(encoding="utf-8")
    pinned = {name: re.search(r'^%s = (.+)$' % name, source, re.M) for name in
              ("POLICY_SHA256", "POLICY_BYTES", "FORMAL_SHA256", "FORMAL_BLOB", "NAMESPACE")}
    values = {name: (match.group(1).strip().strip('"') if match else None) for name, match in pinned.items()}
    if values["POLICY_SHA256"] != args.policy_sha256:
        problems.append("product POLICY_SHA256 is not the supplied policy pin")
    if values["POLICY_BYTES"] != str(len(policy)):
        problems.append("product POLICY_BYTES is not the supplied policy length")
    if (values["FORMAL_SHA256"], values["FORMAL_BLOB"], values["NAMESPACE"]) != (FORMAL_SHA256, FORMAL_BLOB, NAMESPACE):
        problems.append("product formal blob pin or namespace differs from this runner")
    formal_blob = read_formal_blob()
    read_formal(formal_blob)
    info = {
        "candidate_sha": candidate, "product_sha256": sha256_file(PRODUCT_FILE),
        "consumer_sha256": sha256_file(CONSUMER_FILE), "script_sha256": sha256_file(__file__),
        "policy_sha256": args.policy_sha256, "seal_sha256": args.seal_sha256,
        "formal_blob": FORMAL_BLOB, "formal_sha256": FORMAL_SHA256, "problems": problems,
    }
    return info, policy, seal, formal_blob


# --- the run --------------------------------------------------------------------------------


def run_qa(*, policy, policy_sha256, formal_blob, financial_start=None, binding=None,
           transport=None, guard_stats=None, now=time.monotonic):
    """Run acquisition -> oracle -> admission -> consumer -> refusals -> release.

    ``transport``/boundary ledger are for the offline self-test only; a real run passes neither."""
    sys.path.insert(0, str(BACKEND))
    import app.institutional_flow_ratio_source as product

    summary = {"steps": {}, "mismatches": [], "ratios": [], "receipts": []}
    steps = summary["steps"]
    started = now()
    source = None
    try:
        formal = read_formal(formal_blob)
        arguments = dict(policy_canonical=policy, policy_sha256=policy_sha256, formal_blob=formal_blob)
        if transport is None:
            arguments.update(financial_start=financial_start, execution_binding=binding)
        else:
            arguments.update(transport=transport, ledger=product.AttemptLedger(product.NAMESPACE))
        source = product.FlowVolumeSource(**arguments)
        try:
            source.acquire()
            steps["acquire"] = "pending"
        except product.SourceError as failure:
            steps["acquire"] = "failed"
            summary["failure"] = {key: value for key, value in dict(failure.diagnostics).items()}
            summary["attempts"] = len(source.ledger.attempted) if source.ledger else None
            return summary
        inspection = source.inspection()
        captures = inspection["captures"]
        evidence = oracle(captures, formal)
        summary["mismatches"] = list(evidence["mismatches"])
        steps["oracle_source"] = "pass" if not evidence["mismatches"] else "fail"
        if evidence["mismatches"]:
            return summary
        summary["receipts"] = [{"index": i, "source_id": c.receipt.source_id, "body_bytes": c.receipt.body_bytes,
                                "body_sha256": c.receipt.body_sha256, "receipt_sha256": evidence["receipt_sha256s"][i]}
                               for i, c in enumerate(captures)]
        # getter parity: product's parsed rows equal the oracle's own parse of the same bytes
        for symbol in SYMBOLS:
            bars = inspection["results"][symbol]
            if tuple(b.volume for b in bars) != evidence["prices"][symbol] or tuple(b.date for b in bars) != evidence["days"]:
                summary["mismatches"].append("product_prices[%s]" % symbol)
            rows = inspection["flows"][symbol]
            if {(r.date, r.name): (r.buy, r.sell) for r in rows} != evidence["flows"][symbol] or len(rows) != 120:
                summary["mismatches"].append("product_flows[%s]" % symbol)
        steps["getter_parity"] = "pass" if not summary["mismatches"] else "fail"
        if summary["mismatches"]:
            return summary
        # admission
        bad = [dict(calendar_rows=23), dict(net_anchor_fields=55), dict(receipt_sha256s=evidence["receipt_sha256s"][::-1])]
        base = dict(namespace=product.NAMESPACE, policy_sha256=policy_sha256,
                    holder_thread_id=binding.holder_thread_id if binding else "00000000-0000-4000-8000-000000000000",
                    candidate_sha=binding.candidate_sha if binding else "0" * 40,
                    script_sha256=binding.script_sha256 if binding else "0" * 64,
                    receipt_sha256s=evidence["receipt_sha256s"], independent=True, **evidence["admission"])
        refused = 0
        for override in bad:
            try:
                source.admit_independent_verification(product.OracleAdmission(**{**base, **override}))
            except product.SourceError:
                refused += 1
        steps["wrong_admissions_refused"] = refused
        source.admit_independent_verification(product.OracleAdmission(**base))
        steps["admission"] = source.state
        # consumer: 14 exact rational comparisons
        matched = 0
        for (symbol, cutoff), expected in evidence["ratios"].items():
            values = product.institutional_flow_volume_ratio_v1(source, symbol, cutoff).values
            ratio = expected["ratio"]
            same = ((values["ratio"].numerator, values["ratio"].denominator) == (ratio.numerator, ratio.denominator)
                    and values["gate_passed"] is expected["gate"]
                    and (values["foreign_net_shares"], values["investment_trust_net_shares"],
                         values["dealer_net_shares"], values["total_net_shares"]) == expected["nets"]
                    and values["volume_shares_sum"] == expected["volume_sum"])
            matched += int(same)
            if not same:
                summary["mismatches"].append("ratio[%s,%s]" % (symbol, cutoff))
            summary["ratios"].append({"symbol": symbol, "cutoff": cutoff, "nets": list(expected["nets"]),
                                      "volume_sum": expected["volume_sum"], "ratio": "%d/%d" % (ratio.numerator, ratio.denominator),
                                      "gate_passed": expected["gate"], "product_match": same})
        steps["ratios_matched"] = "%d/14" % matched
        # refusals after acquisition
        refusals = {}
        for label, call in (
                ("cutoff_2026-10-07", lambda: product.institutional_flow_volume_ratio_v1(source, "3105", "2026-10-07")),
                ("symbol_2330", lambda: product.institutional_flow_volume_ratio_v1(source, "2330", "2026-10-05")),
                ("no_snapshot", lambda: product.institutional_flow_volume_ratio_v1(None, "3105", "2026-10-05"))):
            try:
                call()
                refusals[label] = "NOT_REFUSED"
            except product.SourceError as failure:
                refusals[label] = failure.code
        steps["refusals"] = refusals
        if refusals != {"cutoff_2026-10-07": "unsupported_window_scope", "symbol_2330": "unsupported_window_scope",
                        "no_snapshot": "snapshot_required"}:
            summary["mismatches"].append("refusals")
        handle = product.institutional_flow_volume_ratio_v1(source, SYMBOLS[0], CUTOFFS[0])
        summary["ledger_attempted"] = list(source.ledger.attempted)
        source.release()
        released = {"state": source.state}
        for label, call in (("handle", lambda: handle.values), ("inspection", source.inspection)):
            try:
                call()
                released[label] = "NOT_REFUSED"
            except product.SourceError as failure:
                released[label] = failure.code
        steps["after_release"] = released
        if released != {"state": "released", "handle": "consumer_unavailable", "inspection": "inspection_unavailable"}:
            summary["mismatches"].append("after_release")
        return summary
    finally:
        summary["elapsed_seconds"] = round(now() - started, 2)
        summary["elapsed_within_batch_budget"] = summary["elapsed_seconds"] <= BATCH_SECONDS
        if guard_stats is not None:
            summary["guard"] = dict(guard_stats)
        if source is not None and source.state not in ("released", "expired"):
            source.release()
        summary["cleanup"] = {"state": getattr(source, "state", None)}
        source = None
        gc.collect()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("policy-file", "policy-sha256", "seal-file", "seal-sha256", "seal-url",
                 "holder-session", "model", "effort"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--real", action="store_true", help="make the 15 GET requests (spends the one-shot quota)")
    args = parser.parse_args(argv)
    info, policy, seal, formal_blob = preflight(args)
    print(json.dumps({"preflight": info}, indent=1, sort_keys=True))
    if info["problems"] or not args.real:
        return 0 if not info["problems"] and not args.real else 2
    sys.path.insert(0, str(BACKEND))
    import app.institutional_flow_ratio_source as product
    binding = product.ExecutionBinding(
        holder_thread_id=args.holder_session, holder_session_id=args.holder_session, parent_thread_id=None,
        model=args.model, reasoning_effort=args.effort, candidate_sha=info["candidate_sha"],
        loaded_source_sha256=info["product_sha256"], consumer_source_sha256=info["consumer_sha256"],
        script_sha256=info["script_sha256"], native_command=" ".join(sys.argv))
    start = product.FinancialStart(
        version=seal["version"], issuer_thread_id=seal["issuer_thread_id"],
        coordinator_session_ids=tuple(seal["coordinator_session_ids"]),
        implementer_session_ids=tuple(seal["implementer_session_ids"]), namespace=seal["namespace"],
        policy_sha256=seal["policy_sha256"], seal_comment_url=args.seal_url, binding=binding,
        authorized=seal["authorized"], whole_batch=seal["whole_batch"])
    guard = install_guard()
    summary = run_qa(policy=policy, policy_sha256=args.policy_sha256, formal_blob=formal_blob,
                     financial_start=start, binding=binding, guard_stats=guard)
    print(json.dumps(summary, indent=1, sort_keys=True, default=str))
    ok = (not summary["mismatches"] and "failure" not in summary
          and summary["steps"].get("ratios_matched") == "14/14" and summary["elapsed_within_batch_budget"]
          and summary["guard"]["blocked"] == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
