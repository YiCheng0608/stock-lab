"""verify 真資料證據推送前的遮罩（#943）：``page_checks.py --mask-evidence <OUT>``.

AC-1: the evidence of a real-data run whose news JSON holds 「開盤」, a number and 美元 (as
api/news-domestic-100-1.json did on 2026-11-21) is refused by quote_guard and the hook; after
the step SKILL.md runs before pushing, every file push_pr_assets.sh would push passes both.
AC-2: only the hit values become <價>／<時間>／<值>; every other byte stays, a JSON line keeps
its own spacing, JSON still parses, and the original is kept under .private/unmasked/.
AC-3: the checks read the original values (a masked page would fail N2) and results.json keeps
its states. The quote numbers are made up and built here, never written next to 開盤 (the hook
and CI rule g refuse such a file).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "tools" / "ops"
GUARD = OPS / "agent_guard.cjs"
NODE = shutil.which("node")

sys.path.insert(0, str(OPS))
try:
    import quote_guard
finally:
    sys.path.remove(str(OPS))


def _load():
    if "page_checks" in sys.modules:
        return sys.modules["page_checks"]
    spec = importlib.util.spec_from_file_location(
        "page_checks", ROOT / "tools" / "verify" / "page_checks.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["page_checks"] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


page_checks = _load()

OPEN = "開" + "盤"
PRICE = f"{6 * 37}.{5}"  # a made-up ADR price
AT = ":".join(f"{n:02d}" for n in (9, 3, 15))
SENTENCE = f"台積電 ADR 前一晚{OPEN} {PRICE} 美元，收盤走高"
MASKED_SENTENCE = f"台積電 ADR 前一晚{OPEN} <價> 美元，收盤走高"
TITLE = f"台積電 ADR {OPEN}{PRICE} 美元"
MASKED_TITLE = f"台積電 ADR {OPEN}<價> 美元"
IMAGE = b"\x89PNG\r\n" + SENTENCE.encode("utf-8")


def _news_payload(summary: str, title: str) -> dict:
    return {
        "status": "success",
        "items": [
            {"id": 35411, "title": "沒有報價的標題", "ai": {"summary": "營收創高"}},
            {"id": 35412, "title": title, "ai": {"summary": summary}},
        ],
    }


def _dump(payload) -> str:
    # How page_checks writes api/*.json, results.json and manual/*.json.
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _jsonl(record: dict) -> str:
    # How screenshot.cjs writes a line (JSON.stringify: no spaces).
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def _results(detail: str) -> list[dict]:
    return [
        {
            "page": "news",
            "code": "N2",
            "state": "pass",
            "status": "通過",
            "detail": detail,
        },
        {
            "page": "news",
            "code": "N3",
            "state": "fail",
            "status": "失敗",
            "detail": "x",
        },
    ]


def _evidence(out: Path) -> dict[str, bytes]:
    """A real-data $OUT of the 2026-11-21 kind; returns each file's bytes."""

    files = {
        "api/news-domestic-100-1.json": _dump(_news_payload(SENTENCE, TITLE)),
        "api/dashboard.json": _dump({"status": "success", "close": 123.45}),
        "shots/news.txt": f"新聞\n{TITLE}\n可能正向\n發布於 2026/11/21 08:00\n",
        "shots/news.jsonl": _jsonl({"width": 1280, "ready": True, "text": TITLE})
        + "\n"
        + _jsonl({"width": 390, "ready": True, "missingClicks": []})
        + "\n",
        "manual/N7.json": _dump(
            {"rule": "前 3 則", "samples": [{"id": 35412, "summary": SENTENCE}]}
        ),
        "results.json": _dump(_results(f"domestic 前 2 則：{TITLE}")),
        "summary.md": f"## verify 檢查結果\n\n| N2 | 通過 | {TITLE} |\n| N3 | 失敗 | {AT} 成交 |\n",
        "facts.json": _dump({"portfolio_positions": 0}),
    }
    written: dict[str, bytes] = {}
    for rel, text in files.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        written[rel] = text.encode("utf-8")
    (out / "shots" / "news-1280.png").write_bytes(IMAGE)
    (out / ".private").mkdir()
    (out / ".private" / "copy.json").write_text(SENTENCE, encoding="utf-8")
    return written


def _pushed(out: Path) -> list[Path]:
    """The files push_pr_assets.sh pushes and the hook reads: not hidden, not images."""

    return sorted(
        path
        for path in out.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(out).parts)
        and path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    )


def _hits(out: Path) -> list[str]:
    return [
        line
        for path in _pushed(out)
        for line in quote_guard.describe(
            path.relative_to(out).as_posix(),
            quote_guard.hits(path.read_bytes().decode("utf-8")),
        )
    ]


def _hook(out: Path) -> subprocess.CompletedProcess:
    command = f"bash tools/ops/push_pr_assets.sh --issue 943 --dir {out.as_posix()}"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(ROOT),
    }
    return subprocess.run(
        [NODE, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
        timeout=60,
    )


def test_ac1_evidence_with_open_price_passes_the_guard_after_the_mask_step(tmp_path):
    out = tmp_path / "20261121-0130"
    _evidence(out)
    before = _hits(out)
    # The reproduction: the news JSON (line of 35412's summary) hits template:open.
    assert any(
        line.startswith("api/news-domestic-100-1.json:")
        and line.endswith("template:open")
        for line in before
    ), before

    assert page_checks.main(["--mask-evidence", str(out)]) == 0

    assert _hits(out) == []
    for path in _pushed(out):
        assert quote_guard.main(["check", str(path)]) == 0, path


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_ac1_the_hook_lets_the_masked_push_through(tmp_path):
    out = tmp_path / "20261121-0130"
    _evidence(out)
    refused = _hook(out)
    assert refused.returncode == 2, refused.stderr
    assert "news-domestic-100-1.json" in refused.stderr

    assert page_checks.main(["--mask-evidence", str(out)]) == 0

    allowed = _hook(out)
    assert allowed.returncode == 0, allowed.stderr


def test_ac2_only_the_hit_values_change_and_json_still_parses(tmp_path):
    out = tmp_path / "out"
    original = _evidence(out)

    assert page_checks.main(["--mask-evidence", str(out)]) == 0

    expected = {
        "api/news-domestic-100-1.json": _dump(
            _news_payload(MASKED_SENTENCE, MASKED_TITLE)
        ),
        "shots/news.txt": original["shots/news.txt"]
        .decode()
        .replace(TITLE, MASKED_TITLE),
        # The compact line stays compact (quote_guard alone would re-space it).
        "shots/news.jsonl": _jsonl({"width": 1280, "ready": True, "text": MASKED_TITLE})
        + "\n"
        + _jsonl({"width": 390, "ready": True, "missingClicks": []})
        + "\n",
        "manual/N7.json": _dump(
            {"rule": "前 3 則", "samples": [{"id": 35412, "summary": MASKED_SENTENCE}]}
        ),
        "results.json": _dump(_results(f"domestic 前 2 則：{MASKED_TITLE}")),
        "summary.md": "## verify 檢查結果\n\n"
        f"| N2 | 通過 | {MASKED_TITLE} |\n| N3 | 失敗 | <時間> 成交 |\n",
    }
    for rel, data in original.items():
        now = (out / rel).read_bytes()
        if rel in expected:
            assert now.decode("utf-8") == expected[rel], rel
            # The original is kept, outside what is pushed.
            assert (out / ".private" / "unmasked" / rel).read_bytes() == data, rel
        else:
            assert now == data, rel  # no hit: not touched
            assert not (out / ".private" / "unmasked" / rel).exists(), rel
    for path in _pushed(out):
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            json.loads(text)
        elif path.suffix == ".jsonl":
            for line in filter(None, text.split("\n")):
                json.loads(line)
    assert (
        out / "shots" / "news-1280.png"
    ).read_bytes() == IMAGE  # images are not read
    assert (out / ".private" / "copy.json").read_text(encoding="utf-8") == SENTENCE


def test_ac2_a_second_run_keeps_the_first_original(tmp_path):
    out = tmp_path / "out"
    original = _evidence(out)
    assert page_checks.main(["--mask-evidence", str(out)]) == 0
    assert page_checks.main(["--mask-evidence", str(out)]) == 0  # nothing left to mask
    # summary.md edited again (step 2 of 證據) with another hit.
    summary = out / "summary.md"
    edited = summary.read_text(encoding="utf-8") + f"N7 原句：{SENTENCE}\n"
    summary.write_text(edited, encoding="utf-8")
    assert page_checks.main(["--mask-evidence", str(out)]) == 0

    kept = out / ".private" / "unmasked"
    assert (kept / "summary.md").read_bytes() == original["summary.md"]
    assert (kept / "summary.md.2").read_text(encoding="utf-8") == edited
    assert _hits(out) == []


def test_mask_refuses_and_changes_nothing_when_a_file_cannot_be_masked(
    tmp_path, capsys
):
    out = tmp_path / "out"
    original = _evidence(out)
    # A field of Fugle's answer as a bare number: masking it would leave no valid JSON.
    broken = _dump({"lastPrice": 12.5})
    (out / "api" / "quote.json").write_text(broken, encoding="utf-8")
    (out / "blob.bin").write_bytes(b"\xff\xfe\x00")

    assert page_checks.main(["--mask-evidence", str(out)]) == 1

    err = capsys.readouterr().err
    assert "api/quote.json" in err and "blob.bin" in err
    assert "12.5" not in err and PRICE not in err  # never prints a quote
    for rel, data in original.items():
        assert (out / rel).read_bytes() == data, rel
    assert not (out / ".private" / "unmasked").exists()


def test_mask_evidence_needs_a_directory(tmp_path, capsys):
    assert page_checks.main(["--mask-evidence", str(tmp_path / "missing")]) == 2
    assert "not a directory" in capsys.readouterr().err


# ---- AC-3: the checks use the original values ----


class FakeRun(page_checks.Run):
    """Fixed API payloads and page text instead of HTTP and screenshots."""

    def __init__(self, tmp_path, payloads, pages):
        super().__init__(
            "http://api",
            "http://web",
            tmp_path / "db",
            tmp_path / "out",
            now=datetime(2026, 11, 21, 12, tzinfo=page_checks.TAIPEI),
        )
        self.payloads, self.pages = payloads, pages

    def get(self, path, name=None):
        if path not in self.payloads:
            raise page_checks.Undetermined(f"/api/{path} 回 404")
        return self.payloads[path]

    def shoot(self, shot):
        return {width: {"width": width, "ready": True} for width in shot.widths}

    def text(self, shot, width=1280):
        return page_checks.Text(
            f"{shot.name}-{width}.txt", self.pages[f"{shot.name}-{width}"]
        )


def _n2_run(tmp_path, domestic_page):
    return FakeRun(
        tmp_path,
        {
            "news?category=domestic&limit=20": {"items": [{"id": "1", "title": TITLE}]},
            "news?category=international&limit=20": {"items": []},
            "news?source_kind=official_disclosure&limit=20": {"items": []},
        },
        {
            "news-1280": domestic_page,
            "news-international-1280": "目前沒有符合條件的國際新聞。\n",
            "news-official-1280": "目前沒有符合條件的官方公告。\n",
        },
    )


def test_ac3_checks_read_the_original_values_and_results_keep_their_states(tmp_path):
    page = f"新聞\n{TITLE}\n可能正向\nAI 推論\nYahoo奇摩股市\n·\n發布於 2026/11/21 08:00\n展開\n"
    # The run compares the original page with the original API: 通過.
    detail = page_checks.n2(_n2_run(tmp_path, page))
    assert "domestic 前 1 則" in detail
    # Had the page been masked before the check, the same title would be missing.
    with pytest.raises(page_checks.Fail):
        page_checks.n2(_n2_run(tmp_path, quote_guard.mask(page)))

    out = tmp_path / "evidence"
    _evidence(out)
    results = [dict(r, detail=f"{r['detail']} {TITLE}") for r in _results(detail)]
    (out / "results.json").write_text(_dump(results), encoding="utf-8")
    assert page_checks.main(["--mask-evidence", str(out)]) == 0

    masked = json.loads((out / "results.json").read_text(encoding="utf-8"))
    keys = ("page", "code", "state", "status")
    assert [{k: r[k] for k in keys} for r in masked] == [
        {k: r[k] for k in keys} for r in results
    ]
    assert [r["detail"] for r in masked] == [
        r["detail"].replace(TITLE, MASKED_TITLE) for r in results
    ]
