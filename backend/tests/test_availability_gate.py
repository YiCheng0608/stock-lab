"""Memory-only tests for caller-declared availability cutoff checks."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

from app.availability_gate import AVAILABILITY_GATE_VERSION, evaluate_availability
from app.time_evidence import TIME_EVIDENCE_VERSION, normalize_timestamp


DECISION = "2026-03-09T17:00:00+08:00"


def _point(value, *, status="known", precision="instant", reason=None):
    result = {
        "status": status,
        "precision": precision,
        "value": value,
        "source": "caller-source",
        "evidence": {"kind": "raw", "id": "row-1"},
        "ref": "caller://row-1",
    }
    if reason is not None:
        result["reason"] = reason
    return result


def _record(*, snapshot="snapshot-1", revision=False):
    return {
        "version": TIME_EVIDENCE_VERSION,
        "subject_identity": {"exchange": "TWSE", "symbol": "2330"},
        "source_identity": {"id": "caller-source"},
        "snapshot_identity": {"id": snapshot},
        "revision_identity": (
            {"id": "rev-2", "kind": "revision", "supersedes": "rev-1"}
            if revision else {"id": "rev-1", "kind": "root"}
        ),
        "market_date": _point("2026-03-09", precision="date"),
        "published_at": _point("2026-03-09T08:00:00+08:00"),
        "first_available_at": _point("2026-03-09T09:00:00+08:00"),
        "collected_at": _point("2026-03-09T16:00:00+08:00"),
        "revision_available_at": (
            _point("2026-03-09T16:00:00+08:00")
            if revision else _point(None, status="not_applicable", precision="none", reason="root_has_no_predecessor")
        ),
        "decision_at": _point(DECISION),
        "generated_at": _point("2026-03-09T17:01:00+08:00"),
        "earliest_execution_at": _point("2026-03-10T09:00:00+08:00"),
    }


def _request(*entries, run_type="live", decision_at=DECISION):
    return {
        "version": AVAILABILITY_GATE_VERSION,
        "type": run_type,
        "decision_at": decision_at,
        "required_inputs": [
            {"input_id": input_id, **{name: copy.deepcopy(record[name]) for name in (
                "subject_identity", "source_identity", "snapshot_identity", "revision_identity"
            )}}
            for input_id, record in entries
        ],
        "evidence": [
            {"input_id": input_id, "time_evidence": copy.deepcopy(record)}
            for input_id, record in entries
        ],
    }


def _codes(reasons):
    return {reason["code"] for reason in reasons}


class AvailabilityGateTests(unittest.TestCase):
    def test_completeness_is_caller_declared_on_success_failure_and_early_return(self):
        request = _request(("first", _record()), ("second", _record(snapshot="snapshot-2")))
        success = evaluate_availability(request)
        self.assertTrue(success["cutoff_satisfied"])

        failed_request = copy.deepcopy(request)
        failed_request["evidence"][0]["time_evidence"]["first_available_at"]["value"] = "2026-03-09T17:00:01+08:00"
        failure = evaluate_availability(failed_request)
        self.assertFalse(failure["cutoff_satisfied"])

        early_return = evaluate_availability(None)
        self.assertFalse(early_return["cutoff_satisfied"])
        self.assertIn("invalid_request_type", _codes(early_return["request_reasons"]))

        shortened = copy.deepcopy(request)
        shortened["required_inputs"].pop()
        shortened["evidence"].pop()
        shortened_result = evaluate_availability(shortened)
        self.assertTrue(shortened_result["cutoff_satisfied"])
        self.assertEqual(len(shortened_result["items"]), 1)

        for report in (success, failure, early_return, shortened_result):
            self.assertEqual(report["required_inputs_completeness"], "caller_declared_only")
            self.assertEqual(report["availability_truth"], "not_asserted")
            self.assertEqual(report["point_in_time_status"], "not_asserted")

    def test_utc_normalization_overflow_rejects_at_request_and_evidence_boundaries(self):
        lower = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14)))
        upper = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(-timedelta(hours=12)))
        for boundary in (lower, upper):
            for value in (boundary, boundary.isoformat()):
                with self.subTest(layer="request_decision", value=value):
                    request = _request(("price", _record()), decision_at=value)
                    report = evaluate_availability(request)
                    self.assertFalse(report["cutoff_satisfied"])
                    self.assertIn("invalid_decision_at", _codes(report["request_reasons"]))

            with self.subTest(layer="required_identity", boundary=boundary):
                request = _request(("price", _record()))
                request["required_inputs"][0]["subject_identity"]["observed_at"] = boundary
                report = evaluate_availability(request)
                self.assertFalse(report["cutoff_satisfied"])
                self.assertIn("invalid_required_identity", _codes(report["items"][0]["reasons"]))

            with self.subTest(layer="evidence_time", boundary=boundary):
                record = _record()
                record["first_available_at"]["value"] = boundary
                report = evaluate_availability(_request(("price", record)))
                self.assertFalse(report["cutoff_satisfied"])
                self.assertIn("invalid_time_evidence_datetime", _codes(report["items"][0]["reasons"]))

            with self.subTest(layer="evidence_identity", boundary=boundary):
                request = _request(("price", _record()))
                request["evidence"][0]["time_evidence"]["subject_identity"]["observed_at"] = boundary
                report = evaluate_availability(request)
                self.assertFalse(report["cutoff_satisfied"])
                self.assertIn("invalid_time_evidence_datetime", _codes(report["items"][0]["reasons"]))

    def test_empty_required_and_each_wrapper_field_set_reject(self):
        empty = _request()
        report = evaluate_availability(empty)
        self.assertFalse(report["cutoff_satisfied"])
        self.assertIn("empty_required_inputs", _codes(report["request_reasons"]))

        for layer in ("request_extra", "request_missing", "required_extra", "required_missing", "evidence_extra", "evidence_missing"):
            with self.subTest(layer=layer):
                request = _request(("price", _record()))
                if layer == "request_extra":
                    request["trusted_marker"] = True
                elif layer == "request_missing":
                    del request["type"]
                elif layer == "required_extra":
                    request["required_inputs"][0]["trusted_marker"] = True
                elif layer == "required_missing":
                    del request["required_inputs"][0]["source_identity"]
                elif layer == "evidence_extra":
                    request["evidence"][0]["trusted_marker"] = True
                else:
                    del request["evidence"][0]["time_evidence"]
                report = evaluate_availability(request)
                self.assertFalse(report["cutoff_satisfied"])
                expected = (
                    "request_fields_mismatch" if layer.startswith("request") else
                    "required_input_fields_mismatch" if layer.startswith("required") else
                    "evidence_entry_fields_mismatch"
                )
                observed = _codes(report["request_reasons"]) | _codes(report["items"][0]["reasons"])
                self.assertIn(expected, observed)

    def test_illegal_root_and_revision_structures_reject(self):
        for structure in ("required_root_parent", "required_revision_no_parent", "evidence_root_parent",
                          "evidence_revision_no_parent", "root_revision_time", "revision_not_applicable"):
            with self.subTest(structure=structure):
                request = _request(("price", _record()))
                if structure == "required_root_parent":
                    request["required_inputs"][0]["revision_identity"]["supersedes"] = "rev-0"
                elif structure == "required_revision_no_parent":
                    request["required_inputs"][0]["revision_identity"] = {"id": "rev-2", "kind": "revision"}
                elif structure == "evidence_root_parent":
                    request["evidence"][0]["time_evidence"]["revision_identity"]["supersedes"] = "rev-0"
                elif structure == "evidence_revision_no_parent":
                    request["evidence"][0]["time_evidence"]["revision_identity"] = {"id": "rev-2", "kind": "revision"}
                elif structure == "root_revision_time":
                    request["evidence"][0]["time_evidence"]["revision_available_at"] = _point(DECISION)
                else:
                    request = _request(("price", _record(revision=True)))
                    request["evidence"][0]["time_evidence"]["revision_available_at"] = _point(
                        None, status="not_applicable", precision="none", reason="invalid_revision_time"
                    )
                report = evaluate_availability(request)
                self.assertFalse(report["cutoff_satisfied"])
                code = "invalid_required_identity" if structure.startswith("required") else "invalid_time_evidence"
                self.assertIn(code, _codes(report["items"][0]["reasons"]))

    def test_equal_boundary_passes_for_root_and_revision(self):
        root = _record()
        root["first_available_at"]["value"] = DECISION
        root["collected_at"]["value"] = DECISION
        revision = _record(snapshot="snapshot-2", revision=True)
        revision["first_available_at"]["value"] = DECISION
        revision["revision_available_at"]["value"] = DECISION
        revision["collected_at"]["value"] = DECISION
        report = evaluate_availability(_request(("root", root), ("revision", revision)))
        self.assertTrue(report["cutoff_satisfied"])
        self.assertTrue(all(item["cutoff_satisfied"] for item in report["items"]))
        self.assertEqual(report["availability_truth"], "not_asserted")
        self.assertEqual(report["point_in_time_status"], "not_asserted")
        self.assertNotIn("trading_approval", report)
        self.assertNotIn("pit_verified", report)

    def test_late_original_and_late_revision_are_rejected(self):
        original = _record()
        original["first_available_at"]["value"] = "2026-03-09T17:00:01+08:00"
        report = evaluate_availability(_request(("price", original)))
        self.assertFalse(report["cutoff_satisfied"])
        self.assertIn("first_available_at_late", _codes(report["items"][0]["reasons"]))

        revision = _record(revision=True)
        revision["revision_available_at"]["value"] = "2026-03-09T17:00:01+08:00"
        report = evaluate_availability(_request(("price", revision)))
        self.assertFalse(report["cutoff_satisfied"])
        self.assertIn("revision_available_at_late", _codes(report["items"][0]["reasons"]))

    def test_t_plus_two_revision_cannot_enter_t_plus_one_or_fall_back_to_root(self):
        revision = _record(revision=True)
        revision["revision_available_at"]["value"] = "2026-03-11T09:00:00+08:00"
        revision["earliest_execution_at"]["value"] = "2026-03-12T09:00:00+08:00"
        report = evaluate_availability(_request(("signal", revision)))
        self.assertIn("revision_available_at_late", _codes(report["items"][0]["reasons"]))

        request = _request(("signal", revision))
        request["evidence"][0]["time_evidence"] = _record()
        report = evaluate_availability(request)
        self.assertFalse(report["cutoff_satisfied"])
        self.assertIn("identity_mismatch", _codes(report["items"][0]["reasons"]))

    def test_live_collected_late_rejects_but_historical_does_not_use_collected(self):
        record = _record()
        record["collected_at"]["value"] = "2026-03-09T17:00:01+08:00"
        live = evaluate_availability(_request(("price", record)))
        historical = evaluate_availability(_request(("price", record), run_type="historical"))
        self.assertIn("collected_at_late", _codes(live["items"][0]["reasons"]))
        self.assertTrue(historical["cutoff_satisfied"])

    def test_historical_and_backfill_collected_only_do_not_substitute_availability(self):
        record = _record()
        record["first_available_at"] = _point(None, status="unknown", precision="none", reason="not_observed")
        for run_type in ("historical", "backfill"):
            with self.subTest(run_type=run_type):
                report = evaluate_availability(_request(("price", record), run_type=run_type))
                self.assertFalse(report["cutoff_satisfied"])
                self.assertIn("first_available_at_not_known", _codes(report["items"][0]["reasons"]))

    def test_missing_time_role_unknown_revision_and_unknown_live_collection_reject(self):
        missing = _record()
        del missing["first_available_at"]
        report = evaluate_availability(_request(("price", missing)))
        self.assertIn("invalid_time_evidence", _codes(report["items"][0]["reasons"]))

        revision = _record(revision=True)
        revision["revision_available_at"] = _point(None, status="unknown", precision="none", reason="not_observed")
        report = evaluate_availability(_request(("price", revision), run_type="historical"))
        self.assertIn("revision_available_at_not_known", _codes(report["items"][0]["reasons"]))

        live = _record()
        live["collected_at"] = _point(None, status="unknown", precision="none", reason="not_observed")
        report = evaluate_availability(_request(("price", live)))
        self.assertIn("collected_at_not_known", _codes(report["items"][0]["reasons"]))

    def test_unknown_unavailable_date_coarse_and_naive_fail_closed(self):
        cases = (
            (_point(None, status="unknown", precision="none", reason="unknown"), "first_available_at_not_known"),
            (_point(None, status="unavailable", precision="none", reason="unavailable"), "first_available_at_not_known"),
            (_point("2026-03-09", precision="date"), "first_available_at_not_instant"),
            (_point("2026-03-09T09:00:00+08:00", precision="second"), "first_available_at_not_instant"),
            (_point("2026-03-09T09:00:00+08:00", status="available"), "first_available_at_not_known"),
            (_point("2026-03-09T09:00:00+08:00", precision="timestamp"), "first_available_at_not_instant"),
            (_point("2026-03-09T09:00:00"), "invalid_time_evidence"),
        )
        for point, code in cases:
            with self.subTest(code=code, point=point):
                record = _record()
                record["first_available_at"] = point
                report = evaluate_availability(_request(("price", record)))
                self.assertFalse(report["cutoff_satisfied"])
                self.assertIn(code, _codes(report["items"][0]["reasons"]))

    def test_timezone_equivalent_input_has_identical_result(self):
        first = _request(("price", _record()))
        second = copy.deepcopy(first)
        second["decision_at"] = normalize_timestamp(second["decision_at"])
        for role in ("published_at", "first_available_at", "collected_at", "decision_at", "generated_at", "earliest_execution_at"):
            point = second["evidence"][0]["time_evidence"][role]
            point["value"] = normalize_timestamp(point["value"])
        self.assertEqual(evaluate_availability(first), evaluate_availability(second))

    def test_exact_pairing_rejects_missing_extra_duplicate_and_identity_mismatch(self):
        base = _request(("price", _record()))
        missing = copy.deepcopy(base)
        missing["evidence"] = []
        report = evaluate_availability(missing)
        self.assertIn("missing_evidence", _codes(report["items"][0]["reasons"]))

        extra = copy.deepcopy(base)
        extra["evidence"].append({"input_id": "not-required", "time_evidence": _record(snapshot="other")})
        report = evaluate_availability(extra)
        self.assertFalse(report["cutoff_satisfied"])
        self.assertIn("extra_evidence", _codes(report["unexpected_evidence"][0]["reasons"]))
        self.assertIn("evidence_set_not_exact", _codes(report["items"][0]["reasons"]))

        duplicate = copy.deepcopy(base)
        duplicate["evidence"].append(copy.deepcopy(duplicate["evidence"][0]))
        report = evaluate_availability(duplicate)
        self.assertIn("duplicate_evidence", _codes(report["items"][0]["reasons"]))

        mismatch = copy.deepcopy(base)
        for name, changed in (
            ("subject_identity", {"exchange": "TWSE", "symbol": "2317"}),
            ("source_identity", {"id": "another-source"}),
            ("snapshot_identity", {"id": "different"}),
            ("revision_identity", {"id": "different", "kind": "root"}),
        ):
            with self.subTest(identity=name):
                mismatch = copy.deepcopy(base)
                mismatch["evidence"][0]["time_evidence"][name] = changed
                report = evaluate_availability(mismatch)
                self.assertIn({"code": "identity_mismatch", "detail": name}, report["items"][0]["reasons"])

        typed_mismatch = copy.deepcopy(base)
        typed_mismatch["required_inputs"][0]["snapshot_identity"]["ordinal"] = True
        typed_mismatch["evidence"][0]["time_evidence"]["snapshot_identity"]["ordinal"] = 1
        report = evaluate_availability(typed_mismatch)
        self.assertIn({"code": "identity_mismatch", "detail": "snapshot_identity"}, report["items"][0]["reasons"])

        duplicate_required = copy.deepcopy(base)
        duplicate_required["required_inputs"].append(copy.deepcopy(duplicate_required["required_inputs"][0]))
        report = evaluate_availability(duplicate_required)
        self.assertFalse(report["cutoff_satisfied"])
        self.assertTrue(all("duplicate_required_input" in _codes(item["reasons"]) for item in report["items"]))

        duplicate_identity = copy.deepcopy(base)
        second = copy.deepcopy(duplicate_identity["required_inputs"][0])
        second["input_id"] = "other-id"
        duplicate_identity["required_inputs"].append(second)
        report = evaluate_availability(duplicate_identity)
        self.assertFalse(report["cutoff_satisfied"])
        self.assertTrue(all("duplicate_required_identity" in _codes(item["reasons"]) for item in report["items"]))

    def test_unsupported_versions_types_and_decision_mismatch_reject(self):
        base = _request(("price", _record()))
        changes = (
            (lambda r: r.__setitem__("version", "future/v2"), "unsupported_gate_version"),
            (lambda r: r.__setitem__("type", "realtime"), "unsupported_run_type"),
            (lambda r: r["evidence"][0]["time_evidence"].__setitem__("version", "time-evidence/v2"), "unsupported_time_evidence_version"),
            (lambda r: r["evidence"][0].__setitem__("time_evidence", []), "invalid_time_evidence_type"),
            (lambda r: r.__setitem__("decision_at", "2026-03-09T17:00:01+08:00"), "decision_at_mismatch"),
        )
        for change, code in changes:
            with self.subTest(code=code):
                request = copy.deepcopy(base)
                change(request)
                report = evaluate_availability(request)
                self.assertFalse(report["cutoff_satisfied"])
                observed = _codes(report["request_reasons"]) | _codes(report["items"][0]["reasons"])
                self.assertIn(code, observed)

    def test_other_dates_and_markers_cannot_replace_first_availability(self):
        record = _record()
        record["first_available_at"] = _point(None, status="unknown", precision="none", reason="not_observed")
        record["data_cutoff"] = DECISION
        record["trusted_availability"] = True
        report = evaluate_availability(_request(("price", record), run_type="historical"))
        self.assertFalse(report["cutoff_satisfied"])
        self.assertIn("first_available_at_not_known", _codes(report["items"][0]["reasons"]))

    def test_all_required_and_output_is_detached_deterministic(self):
        good = _record()
        late = _record(snapshot="snapshot-2")
        late["first_available_at"]["value"] = "2026-03-09T17:00:01+08:00"
        request = _request(("good", good), ("late", late))
        before = copy.deepcopy(request)
        first = evaluate_availability(request)
        second = evaluate_availability(request)
        self.assertEqual(request, before)
        self.assertEqual(first, second)
        self.assertFalse(first["cutoff_satisfied"])
        self.assertTrue(first["items"][0]["cutoff_satisfied"])
        self.assertFalse(first["items"][1]["cutoff_satisfied"])
        first["items"][0]["input_id"] = "changed"
        first["items"][1]["reasons"].append({"code": "changed"})
        self.assertEqual(request, before)
        self.assertEqual(evaluate_availability(request), second)


if __name__ == "__main__":
    unittest.main()
