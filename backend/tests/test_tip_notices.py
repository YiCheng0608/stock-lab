"""臺灣50 and 中型100 changes from TIP technical notices (Issue #1149).

TIP's files are not in the repository (#1 decision 7235997024): every ``.doc``, PDF
and list page here is built by the test from short text written for it, laid out as
the notices are (#1149 decision 7236130467).  ``make_doc`` writes a minimal OLE
compound file with a Word 97 FIB, a compressed and a Unicode piece; ``make_pdf`` a
PDF with a Type0 font, Identity-H and a ``ToUnicode`` CMap, cells placed in columns.
Both go through the real ``olefile`` and ``pypdf``.
"""

from __future__ import annotations

import argparse
import struct
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    IndexConstituentChange,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)
from worker import sources
from worker import tip_notices as tn
from worker import valuation_backfill as vb

# 2026-11-06 11:00 Taipei: outside the quiet and the even hours.
NOON = datetime(2026, 11, 6, 3, 0)

# --- file builders (standard library only) ------------------------------------------

SECTOR = 512
END, FREE, FATSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF


def _dir_entry(
    name: str,
    kind: int,
    *,
    left=NOSTREAM,
    right=NOSTREAM,
    child=NOSTREAM,
    start=END,
    size=0,
) -> bytes:
    encoded = (name + "\0").encode("utf-16-le") if name else b""
    entry = bytearray(128)
    entry[: len(encoded)] = encoded
    struct.pack_into("<HBB", entry, 64, len(encoded), kind, 1)
    struct.pack_into("<III", entry, 68, left, right, child)
    struct.pack_into("<IQ", entry, 116, start, size)
    return bytes(entry)


def _ole(streams: list[tuple[str, bytes]]) -> bytes:
    """A version 3 compound file: FAT at sector 0, directory at 1, the streams after.

    Each stream is padded to at least 4096 bytes, so none is in the mini stream.
    """

    padded = [
        (n, d + b"\0" * (max(4096, -(-len(d) // SECTOR) * SECTOR) - len(d)))
        for n, d in streams
    ]
    fat = [FATSECT, END]
    starts = []
    for _name, data in padded:
        count = len(data) // SECTOR
        first = len(fat)
        starts.append(first)
        fat.extend(range(first + 1, first + count))
        fat.append(END)
    assert len(fat) <= SECTOR // 4
    fat += [FREE] * (SECTOR // 4 - len(fat))
    header = bytearray(SECTOR)
    header[:8] = tn.OLE_MAGIC
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, 1, 1, 0, 4096, END, 0, END, 0)
    difat = [0] + [FREE] * 108
    struct.pack_into("<109I", header, 76, *difat)
    # Root -> entry 1 (WordDocument); entry 2 (the table, a shorter name) is its left.
    directory = _dir_entry("Root Entry", 5, child=1)
    # The padded sizes: at least the 4096-byte cutoff, so not in the mini stream.
    directory += _dir_entry(
        padded[0][0], 2, left=2, start=starts[0], size=len(padded[0][1])
    )
    directory += _dir_entry(padded[1][0], 2, start=starts[1], size=len(padded[1][1]))
    directory += _dir_entry("", 0)
    body = struct.pack(f"<{SECTOR // 4}I", *fat) + directory
    return bytes(header) + body + b"".join(d for _n, d in padded)


def make_doc(
    pieces: list[tuple[str, bool]],
    *,
    table="1Table",
    prc=True,
    clx: bytes | None = None,
    encrypted=False,
) -> bytes:
    """A Word 97 ``.doc`` whose main text is the pieces: (text, compressed)."""

    text_at = 1024
    word = bytearray(text_at)
    flags = (0x0200 if table == "1Table" else 0) | (0x0100 if encrypted else 0)
    struct.pack_into("<HHH", word, 0, tn.WORD_IDENT, 0x00C1, 0)
    struct.pack_into("<H", word, 0x0A, flags)
    struct.pack_into("<H", word, 32, 14)  # csw, then 28 bytes of fibRgW
    struct.pack_into("<H", word, 62, 22)  # cslw, then 88 bytes of fibRgLw
    struct.pack_into("<H", word, 152, 93)  # cbRgFcLcb, then 93 pairs
    cps, pcds, total = [0], [], 0
    content = bytearray()
    for text, compressed in pieces:
        offset = text_at + len(content)
        if compressed:
            content += text.encode("cp1252")
            fc = (offset * 2) | 0x40000000
        else:
            content += text.encode("utf-16-le")
            fc = offset
        total += len(text)
        cps.append(total)
        pcds.append(struct.pack("<HIH", 0, fc, 0))
    struct.pack_into("<i", word, 64 + 3 * 4, total)  # ccpText
    plc = struct.pack(f"<{len(cps)}I", *cps) + b"".join(pcds)
    if clx is None:
        clx = (
            (b"\x01\x02\x00\x00\x00" if prc else b"")
            + b"\x02"
            + struct.pack("<I", len(plc))
            + plc
        )
    table_stream = b"\0" * 16 + clx
    struct.pack_into("<II", word, 154 + tn.FC_CLX_PAIR * 8, 16, len(clx))
    word += content
    return _ole([("WordDocument", bytes(word)), (table, table_stream)])


def make_pdf(rows: list[list[tuple[float, str]]]) -> bytes:
    """A one-page PDF: each row a line of (x, text) cells, from the top down."""

    chars = sorted({c for row in rows for _x, t in row for c in t})
    cid = {c: i + 1 for i, c in enumerate(chars)}
    lines = []
    y = 800
    for row in rows:
        for x, text in row:
            hexed = "".join(f"{cid[c]:04X}" for c in text)
            lines.append(f"BT /F1 10 Tf 1 0 0 1 {x} {y} Tm <{hexed}> Tj ET")
        y -= 14
    stream = "\n".join(lines).encode("ascii")
    bfchar = "\n".join(f"<{cid[c]:04X}> <{ord(c):04X}>" for c in chars)
    cmap = (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
        "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
        f"{len(chars)} beginbfchar\n{bfchar}\nendbfchar\n"
        "endcmap CMapName currentdict /CMap defineresource pop end end"
    ).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /Test-Ming /Encoding /Identity-H "
        b"/DescendantFonts [6 0 R] /ToUnicode 7 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Test-Ming "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        b"/FontDescriptor 8 0 R /DW 1000 >>",
        b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"\nendstream",
        b"<< /Type /FontDescriptor /FontName /Test-Ming /Flags 4 "
        b"/FontBBox [0 0 1000 1000] /ItalicAngle 0 /Ascent 880 /Descent -120 "
        b"/CapHeight 700 /StemV 80 >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def make_list(rows: list[tuple[str, str, str, str | None]]) -> bytes:
    """A list page: the desktop table and a mobile one, as the site's."""

    cells = ""
    for day, title, category, doc_id in rows:
        link = (
            ""
            if doc_id is None
            else f'<a href="{tn.FILE_URL.format(id=doc_id)}" data-v-1><img></a>'
        )
        cells += (
            f"<tr data-v-1><td data-v-1>{day}</td> <td data-v-1>{title}</td> "
            f"<td data-v-1>{category}</td> <td data-v-1>{link}</td></tr>"
        )
    page = (
        '<!doctype html><html><body><div><table class="d-none d-lg-table" data-v-1>'
        '<thead data-v-1><tr data-v-1><th width="180" data-v-1>檔案日期</th> '
        "<th data-v-1>檔案名稱</th> <th data-v-1>檔案類別</th> <th data-v-1>連結</th>"
        f"</tr></thead> <tbody data-v-1>{cells}</tbody></table>"
        '<table class="d-lg-none border-top-black table-mobile"><tbody><tr>'
        "<th>檔案日期</th> <td>2018/01/01</td></tr></tbody></table></div>"
        "<script>window.__NUXT__=(function(a){return {}})(1)</script></body></html>"
    )
    return page.encode("utf-8")


# --- notice texts written for the tests -------------------------------------------------

# ROC dates, code first, 係數 free floats, 無, a third index after the two.
ROC_REVIEW = """技術通知
臺灣指數系列成分股審核

97 年 7月 10 日公布臺灣50指數、臺灣中型100指數及臺灣高股息指數審核結果。相關變動將自97年7月18日（星期五）交易結束後生效（亦即自97年7月21日（星期一）起生效）。
臺灣50指數
成分股納入：
        無
成分股刪除：
        無
成分股候補名單：
        1101 甲泥    ，公眾流通量係數為75%
2603 乙運    ，公眾流通量係數為50%
臺灣中型100指數
成分股納入：
        2201 丙車，公眾流通量係數為100%
\t9940 丁屋，公眾流通量係數為50%
成分股刪除：
        2301 戊電
        3019 己光
臺灣高股息指數
成分股納入：
        9999 庚股，公眾流通量係數為30%
成分股刪除：
        2395 辛華
"""

# Western dates, name first, long free floats, numbered headings, a holiday.
WESTERN_REVIEW = """技術通知
臺灣指數系列及臺灣高股息指數成分股審核
 2018年6月1日
公布下列有關臺灣50指數、臺灣中型100指數、臺灣資訊科
技指數審核結果。相關變動將自2018年6月15日（星期五）交易結束後生效（亦即自2018年6月18日（星期一）起生效）。
註：2018年6月18日休市一日。

一、 臺灣50指數
 (一) 成分股納入：
 壬科 2492 公眾流通量為100.000000000000%
 (二) 成分股刪除：
 癸電 2324
 (三) 成分股候補名單：
 子銀-KY  6541 公眾流通量為33.449629575852%
二、 臺灣中型100指數
 （一） 成分股納入：
 癸電 2324 公眾流通量為93.230000000000%
 丑鋼 2027 公眾流通量為91.000000000000%
 （二） 成分股刪除：
 壬科 2492
 寅伸 4915
三、 臺灣資訊科技指數
 （一） 成分股納入：
 無
六、 公眾流通量調整
 無
"""


def entries(parsed, index, action):
    return [
        (e.symbol, e.name, e.free_float_pct) for e in parsed.sections[index][action]
    ]


# --- parsing ------------------------------------------------------------------------------


def test_a_roc_review_with_code_first_and_none():
    parsed = tn.parse_notice(ROC_REVIEW, "periodic", date(2008, 7, 10))
    assert parsed.announced == date(2008, 7, 10)
    assert parsed.effective == date(2008, 7, 21)
    assert set(parsed.sections) == {"TW50", "TWMC100"}
    assert entries(parsed, "TW50", "add") == [] == entries(parsed, "TW50", "delete")
    assert entries(parsed, "TW50", "reserve") == [
        ("1101", "甲泥", 75.0),
        ("2603", "乙運", 50.0),
    ]
    assert entries(parsed, "TWMC100", "add") == [
        ("2201", "丙車", 100.0),
        ("9940", "丁屋", 50.0),
    ]
    assert entries(parsed, "TWMC100", "delete") == [
        ("2301", "戊電", None),
        ("3019", "己光", None),
    ]


def test_a_western_review_with_name_first_and_a_holiday_effective_date():
    parsed = tn.parse_notice(WESTERN_REVIEW, "periodic", date(2018, 6, 1))
    assert parsed.announced == date(2018, 6, 1)
    # 2018-06-18 is a holiday: kept as written.
    assert parsed.effective == date(2018, 6, 18)
    assert entries(parsed, "TW50", "add") == [("2492", "壬科", 100.0)]
    assert entries(parsed, "TW50", "delete") == [("2324", "癸電", None)]
    assert entries(parsed, "TW50", "reserve") == [("6541", "子銀-KY", 33.449629575852)]
    assert [e[0] for e in entries(parsed, "TWMC100", "add")] == ["2324", "2027"]


def test_a_review_with_one_more_addition_than_deletion_fails_whole():
    text = WESTERN_REVIEW.replace(" 寅伸 4915\n", "")
    with pytest.raises(tn.NoticeError, match="TWMC100: 2 additions but 1 deletions"):
        tn.parse_notice(text, "periodic", date(2018, 6, 1))


def test_a_review_missing_a_named_section_fails():
    text = WESTERN_REVIEW.replace("二、 臺灣中型100指數", "二、 臺灣其他指數")
    with pytest.raises(tn.NoticeError, match="no section of"):
        tn.parse_notice(text, "periodic", date(2018, 6, 1))


def test_a_tw50_only_review_needs_only_that_section():
    text = ROC_REVIEW.replace("臺灣中型100指數及", "").replace(
        "臺灣中型100指數\n", "臺灣發達指數\n"
    )
    parsed = tn.parse_notice(text, "periodic", date(2008, 7, 10))
    assert set(parsed.sections) == {"TW50"}


@pytest.mark.parametrize(
    "old, new, error",
    [
        (" 癸電 2324\n (三)", " 癸電 2324 甲\n (三)", "unreadable line"),
        (" 癸電 2324\n (三)", " 癸電\n (三)", "unreadable line"),
        (" 寅伸 4915\n", " 壬科 2492\n", "a code twice"),
        ("亦即自2018年6月18日", "亦即自2018年6月31日", "unreadable date"),
        ("亦即自2018年6月18日（星期一）起生效", "生效", "without an effective date"),
        (" 無\n六、", " 無\n 卯股 1234\n六、", None),
        ("(一) 成分股納入：", "(一) 成分股納入：\n 無", "after"),
    ],
)
def test_lines_and_dates_that_do_not_read_fail_the_notice(old, new, error):
    text = WESTERN_REVIEW.replace(old, new)
    assert text != WESTERN_REVIEW
    if error is None:
        # Under 臺灣資訊科技指數: not read, not checked.
        tn.parse_notice(text, "periodic", date(2018, 6, 1))
        return
    with pytest.raises(tn.NoticeError, match=error):
        tn.parse_notice(text, "periodic", date(2018, 6, 1))


def test_an_announcement_far_from_the_site_date_fails():
    with pytest.raises(tn.NoticeError, match="but listed"):
        tn.parse_notice(WESTERN_REVIEW, "periodic", date(2018, 6, 20))
    # A day later on the site, as 3 of the 7 #1130 samples.
    assert tn.parse_notice(WESTERN_REVIEW, "periodic", date(2018, 6, 2)).announced == (
        date(2018, 6, 1)
    )


SHARES_NOTICE = """技術通知
臺灣指數系列成分股甲公司股數變動
2019年3月4日
甲公司發行股數自 1,000 股變更為 1,200 股，自2019年3月11日起生效。
"""
PROSE_NOTICE = """技術通知
2019年3月4日
乙公司終止上市，將自臺灣中型100指數中刪除，由候補名單第一順位遞補。
"""
DEFERRED_NOTICE = """技術通知
臺灣指數系列成分股變動：丙公司納入成分股延期
2024年5月2日
因停止買賣，丙公司納入延期，另行公告。
臺灣中型100指數
成分股納入：
 丙公司 6789
成分股刪除：
 無
"""


def test_an_ad_hoc_notice_without_the_indexes_is_read_without_rows():
    parsed = tn.parse_notice(SHARES_NOTICE, "ad_hoc", date(2019, 3, 4))
    assert parsed.sections == {} and parsed.effective == date(2019, 3, 11)


def test_an_ad_hoc_change_in_prose_is_left_for_manual_reading():
    with pytest.raises(tn.NoticeError, match="manual reading"):
        tn.parse_notice(PROSE_NOTICE, "ad_hoc", date(2019, 3, 4))


def test_a_deferral_has_no_effective_date_and_no_count_check():
    parsed = tn.parse_notice(DEFERRED_NOTICE, "ad_hoc", date(2024, 5, 2))
    assert parsed.deferred and parsed.effective is None
    assert entries(parsed, "TWMC100", "add") == [("6789", "丙公司", None)]
    assert entries(parsed, "TWMC100", "delete") == []


def test_an_ad_hoc_change_must_balance_unless_deferred():
    text = DEFERRED_NOTICE.replace("延期", "").replace("納入成分股", "納入")
    with pytest.raises(tn.NoticeError, match="1 additions but 0 deletions"):
        tn.parse_notice(text, "ad_hoc", date(2024, 5, 2))


# --- titles and the list ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "title, category, kind",
    [
        (
            "臺灣證券交易所與富時國際有限公司合編之臺灣指數系列成分股審核",
            "定審結果",
            "periodic",
        ),
        # Filed as 其他 (2017-12-02, 2018-03-02): still a review.
        (
            "臺灣證券交易所與富時國際有限公司合編之臺灣指數系列成分股審核",
            "其他",
            "periodic",
        ),
        ("臺灣50指數成分股審核", "定審結果", "periodic"),
        ("臺灣指數系列及臺灣高股息指數定期審核", "定審結果", "periodic"),
        ("臺灣指數系列基本規則改變-成分股定期審核時間變更", "定審結果", None),
        ("臺灣指數系列成分股變動：成分股刪除甲公司", "其他", "ad_hoc"),
        ("臺灣50指數成分股候補名單", "其他", "ad_hoc"),
        ("臺灣指數系列基本規則修正", "其他", None),
        ("「臺灣指數公司特選高股息低波動指數」成分股審核結果", "定審結果", None),
        ("臺灣指數公司編製規則修訂", "其他", None),
    ],
)
def test_notices_are_picked_by_title_not_by_category(title, category, kind):
    assert tn.notice_kind(title, category) == kind


def test_the_list_page_reads_the_desktop_table():
    page = make_list(
        [
            ("2018/06/01", "臺灣指數系列成分股審核", "定審結果", "247"),
            ("2018/05/02", "某指數 &amp; 規則", "其他", None),
        ]
    ).decode()
    rows = tn.parse_list(page, 2018)
    assert rows[0] == tn.ListedNotice(
        "247",
        date(2018, 6, 1),
        "臺灣指數系列成分股審核",
        "定審結果",
        tn.FILE_URL.format(id=247),
    )
    assert rows[1].doc_id == "" and rows[1].title == "某指數 & 規則"
    with pytest.raises(tn.NoticeError, match="has a row of"):
        tn.parse_list(page, 2017)
    with pytest.raises(tn.NoticeError, match="list tables"):
        tn.parse_list(page.replace("d-lg-table", "x"), 2018)
    with pytest.raises(tn.NoticeError, match="unknown list columns"):
        tn.parse_list(page.replace("檔案類別", "類別"), 2018)


# --- text of the files ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", ["1Table", "0Table"])
def test_a_doc_reads_its_compressed_and_unicode_pieces(table):
    data = make_doc(
        [("Technical notice\r", True), (ROC_REVIEW.replace("\n", "\r"), False)],
        table=table,
    )
    fmt, text = tn.file_text(data)
    assert fmt == "doc"
    assert text.startswith("Technical notice\n技術通知\n")
    parsed = tn.parse_notice(text, "periodic", date(2008, 7, 10))
    assert entries(parsed, "TWMC100", "add")[0] == ("2201", "丙車", 100.0)


def test_a_doc_drops_field_codes_and_cell_marks():
    data = make_doc([("\x13 HYPERLINK x \x14link\x15 a\x07b\x0bc\r", True)], prc=False)
    assert tn.file_text(data)[1] == "link a\nb\nc\n"


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"clx": b"\x05\x00\x00\x00"}, "no piece table"),
        ({"clx": b"\x02\x40\x00\x00\x00" + b"\x00" * 8}, "piece table does not read"),
        ({"encrypted": True}, "encrypted"),
    ],
)
def test_a_doc_whose_clx_does_not_read_fails(kwargs, error):
    data = make_doc([("abc", True)], **kwargs)
    with pytest.raises(tn.NoticeError, match=error):
        tn.file_text(data)


def test_a_doc_whose_table_stream_is_the_other_one_fails():
    data = make_doc([("abc", True)], table="1Table")
    # The FIB names 0Table, the file has 1Table.
    flags_at = 3 * SECTOR + 0x0A
    data = data[:flags_at] + b"\0\0" + data[flags_at + 2 :]
    with pytest.raises(tn.NoticeError, match="no 0Table stream"):
        tn.file_text(data)


def test_damaged_files_fail_instead_of_crashing():
    with pytest.raises(tn.NoticeError, match="not an OLE file"):
        tn.file_text(tn.OLE_MAGIC + b"\0" * 100)
    with pytest.raises(tn.NoticeError, match="unreadable PDF"):
        tn.file_text(b"%PDF-1.4\n garbage")
    with pytest.raises(tn.NoticeError, match="not a .doc or PDF"):
        tn.file_text(b"<!doctype html>")


PDF_ROWS = [
    [(72, "技術通知")],
    [(72, "2018年6月1日")],
    [(72, "公布臺灣50指數、臺灣中型100指數審核結果，亦即自2018年6月18日起生效。")],
    [(72, "一、"), (100, "臺灣50指數")],
    [(80, "(一) 成分股納入：")],
    [(80, "壬科"), (160, "2492"), (220, "公眾流通量為100.000000000000%")],
    [(80, "(二) 成分股刪除：")],
    [(80, "癸電"), (160, "2324")],
    [(72, "二、"), (100, "臺灣中型100指數")],
    [(80, "(一) 成分股納入：")],
    [(80, "癸電"), (160, "2324"), (220, "公眾流通量為93.230000000000%")],
    [(80, "(二) 成分股刪除：")],
    [(80, "壬科"), (160, "2492")],
]


def test_a_pdf_keeps_the_columns_of_a_line_in_layout_mode():
    fmt, text = tn.file_text(make_pdf(PDF_ROWS))
    assert fmt == "pdf"
    parsed = tn.parse_notice(text, "periodic", date(2018, 6, 1))
    assert parsed.announced == date(2018, 6, 1)
    assert entries(parsed, "TW50", "add") == [("2492", "壬科", 100.0)]
    assert entries(parsed, "TWMC100", "add") == [("2324", "癸電", 93.23)]
    assert entries(parsed, "TWMC100", "delete") == [("2492", "壬科", None)]


# --- the run -------------------------------------------------------------------------------------


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def add_instrument(db, symbol, days, exchange="TWSE"):
    item = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type="stock",
        status="active",
    )
    db.add(item)
    db.flush()
    for day in days:
        db.add(
            MarketBar(
                instrument_id=item.id,
                trading_date=day,
                open=10,
                high=10,
                low=10,
                close=10,
                adj_close=10,
                volume=1,
                source="twse",
            )
        )
    db.flush()
    return item


LIST_2018 = [
    # A review filed as 其他, as 2018-03-02; a day later on the site.
    (
        "2018/06/02",
        "臺灣證券交易所與富時國際有限公司合編之臺灣指數系列成分股審核",
        "其他",
        "247",
    ),
    ("2018/05/10", "臺灣指數系列成分股甲公司股數變動", "其他", "240"),
    ("2018/05/01", "臺灣指數系列成分股審核", "定審結果", "238"),
    ("2018/04/01", "「臺灣指數公司某指數」成分股審核結果", "定審結果", "230"),
    ("2018/03/01", "臺灣指數系列基本規則修正", "其他", "229"),
]
UNBALANCED = WESTERN_REVIEW.replace("2018年6月1日", "2018年5月1日").replace(
    " 寅伸 4915\n", ""
)


class Site:
    def __init__(self, files=None):
        self.files = {
            tn.LIST_URL.format(year=2018): make_list(LIST_2018),
            tn.FILE_URL.format(id=247): make_pdf(PDF_ROWS),
            tn.FILE_URL.format(id=240): make_doc(
                [
                    (
                        SHARES_NOTICE.replace("2019", "2018")
                        .replace("3月4日", "5月10日")
                        .replace("3月11日", "5月17日"),
                        False,
                    )
                ]
            ),
            tn.FILE_URL.format(id=238): make_doc([(UNBALANCED, False)]),
            **(files or {}),
        }
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        answer = self.files[url]
        if isinstance(answer, Exception):
            raise answer
        return answer


def run(factory, site, *, reapply=False, now=lambda: NOON, sleep=None, monotonic=None):
    with factory() as db:
        return tn.backfill(
            db,
            date(2018, 1, 1),
            date(2018, 12, 31),
            reapply=reapply,
            fetch=site,
            now=now,
            sleep=sleep or (lambda _s: None),
            monotonic=monotonic or (lambda: 1000.0),
        )


def seed(db):
    # A bar on 2018-06-01 (announced) and none on 06-18 (the holiday it takes effect).
    add_instrument(db, "2492", [date(2018, 6, 1)])
    add_instrument(db, "2324", [date(2018, 5, 31), date(2018, 6, 1)])
    add_instrument(db, "2324", [date(2018, 6, 1)], exchange="TPEx")
    db.commit()


def test_a_backfill_writes_the_notices_and_a_rerun_asks_nothing(factory):
    with factory() as db:
        seed(db)
    site = Site()
    result = run(factory, site)
    counts = result["feeds"]["tip-notices"]
    assert result["status"] == "partial" and result["requests"] == 4
    assert site.calls[0] == tn.LIST_URL.format(year=2018)
    assert (counts["picked"], counts["periodic"], counts["ad_hoc"]) == (3, 2, 1)
    assert (counts["success"], counts["without_rows"], counts["failed"]) == (2, 1, 1)
    assert counts["failed_notices"][0]["id"] == "238"
    assert "1 deletions" in counts["failed_notices"][0]["error"]
    assert counts["formats"] == {"doc": 2, "pdf": 1}
    assert (counts["rows"], counts["inserted"], counts["unmatched"]) == (4, 4, 0)
    with factory() as db:
        rows = db.scalars(
            select(IndexConstituentChange).order_by(
                IndexConstituentChange.index_code, IndexConstituentChange.action
            )
        ).all()
        tw = {
            i.symbol: i.id
            for i in db.scalars(select(Instrument).where(Instrument.exchange == "TWSE"))
        }
        assert [(r.index_code, r.action, r.symbol) for r in rows] == [
            ("TW50", "add", "2492"),
            ("TW50", "delete", "2324"),
            ("TWMC100", "add", "2324"),
            ("TWMC100", "delete", "2492"),
        ]
        first = rows[0]
        assert first.instrument_id == tw["2492"]
        assert rows[1].instrument_id == tw["2324"]  # the TWSE one, not TPEx
        assert first.announced_date == date(2018, 6, 1)
        assert first.site_file_date == date(2018, 6, 2)
        assert first.effective_date == date(2018, 6, 18)
        assert first.announced_time is None
        assert (first.review_kind, first.source, first.source_doc_id) == (
            "periodic",
            "tip_technical_notice",
            "247",
        )
        assert first.free_float_pct == 100.0 and rows[1].free_float_pct is None
        assert first.data_as_of == date(2018, 6, 1)
        raw = db.get(RawPayload, first.raw_payload_id)
        assert raw.source == "tip" and raw.endpoint == tn.FILE_URL.format(id=247)
        assert tn.unwrap_body(vb.read_raw(raw)) == site.files[raw.endpoint]
        # The failed notice wrote nothing and kept its file.
        failed = db.scalar(
            select(IngestionRun).where(
                IngestionRun.request_key == "valuation_backfill:tip-notices:238"
            )
        )
        assert failed.status == "failed" and failed.metadata_json["raw_payload_id"]
        assert not db.scalars(
            select(IndexConstituentChange).where(
                IndexConstituentChange.source_doc_id == "238"
            )
        ).all()
    # The list of 2018 was taken in 2026: final.  The failed notice is read from its
    # raw again, without a request.
    again = Site()
    second = run(factory, again)
    assert again.calls == [] and second["requests"] == 0
    counts = second["feeds"]["tip-notices"]
    assert (counts["list_done_before"], counts["done_before"], counts["reapplied"]) == (
        1,
        2,
        1,
    )
    assert counts["failed"] == 1 and second["changed"] == 0


def test_reapply_asks_nothing_and_changes_nothing(factory):
    with factory() as db:
        seed(db)
    run(factory, Site())
    site = Site()
    result = run(factory, site, reapply=True)
    counts = result["feeds"]["tip-notices"]
    assert site.calls == [] and result["requests"] == 0
    assert (counts["list_reapplied"], counts["reapplied"], counts["changed"]) == (
        1,
        3,
        0,
    )
    assert counts["unchanged"] == 4


def test_reapply_writes_no_manifest_row_for_what_was_never_asked(factory):
    site = Site()
    result = run(factory, site, reapply=True)
    assert site.calls == [] and result["feeds"]["tip-notices"]["list_not_answered"] == 1
    with factory() as db:
        assert db.scalars(select(IngestionRun)).all() == []


def test_a_code_without_a_twse_bar_is_unmatched_not_created(factory):
    result = run(factory, Site())
    counts = result["feeds"]["tip-notices"]
    assert counts["unmatched"] == 4 and counts["unmatched_codes"] == ["2324", "2492"]
    with factory() as db:
        assert db.scalars(select(Instrument)).all() == []
        assert {
            r.instrument_id for r in db.scalars(select(IndexConstituentChange))
        } == {None}


def test_the_current_years_list_is_asked_again():
    raw = RawPayload(collected_at=datetime(2018, 12, 31, 15, 59))
    assert not tn._list_is_final(raw, 2018)  # 23:59 Taipei
    raw.collected_at = datetime(2018, 12, 31, 16, 0)
    assert tn._list_is_final(raw, 2018)


def test_a_failed_request_is_asked_again_and_five_in_a_row_stop_the_run(factory):
    down = sources.OfficialDataError("official endpoint rejected request (503)")
    site = Site({tn.FILE_URL.format(id=247): down})
    result = run(factory, site)
    assert result["feeds"]["tip-notices"]["failed"] == 2
    with factory() as db:
        run_247 = db.scalar(
            select(IngestionRun).where(
                IngestionRun.request_key == "valuation_backfill:tip-notices:247"
            )
        )
        assert (
            run_247.status == "failed" and "raw_payload_id" not in run_247.metadata_json
        )
    again = Site()
    run(factory, again)
    assert again.calls == [tn.FILE_URL.format(id=247)]
    blocked = Site()  # no list of 2013 to 2017: each request fails
    with factory() as db:
        result = tn.backfill(
            db,
            date(2013, 1, 1),
            date(2017, 12, 31),
            fetch=blocked,
            now=lambda: NOON,
            sleep=lambda _s: None,
            monotonic=lambda: 0.0,
        )
    assert result["aborted"] == "5 failed requests in a row to taiwanindex.com.tw"
    assert len(blocked.calls) == 5


def test_requests_to_a_host_keep_three_and_a_half_seconds(factory):
    clock = [100.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    run(factory, Site(), sleep=sleep, monotonic=lambda: clock[0])
    # The list (taiwanindex.com.tw), then three files on backend.taiwanindex.com.tw.
    assert slept == [tn.REQUEST_INTERVAL_SECONDS] * 2


@pytest.mark.parametrize(
    "taipei, wait",
    [
        ((21, 20), 2 * 3600 + 10 * 60),  # the quiet hours, to 23:30
        ((13, 55), 15 * 60),  # before an even hour, to 14:10
        ((14, 5), 5 * 60),
        ((14, 10), 0),
        ((14, 55), 0),  # before an odd hour
        ((23, 55), 15 * 60),  # to 00:10
    ],
)
def test_requests_wait_out_the_quiet_and_the_even_hours(taipei, wait):
    hour, minute = taipei
    moment = datetime(2026, 11, 6, hour, minute, tzinfo=tn.TAIPEI)
    assert tn.seconds_to_window_end(moment) == wait


def test_a_request_in_the_even_hour_waits(factory):
    moments = [datetime(2026, 11, 6, 5, 55), NOON]  # 13:55 Taipei, then 11:00
    slept = []

    def now():
        return moments[0] if not slept else moments[1]

    run(factory, Site(), now=now, sleep=slept.append)
    assert slept[0] == 15 * 60


def test_the_table_must_exist(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with sessionmaker(bind=engine)() as db, pytest.raises(ValueError, match="init-db"):
        tn.backfill(db, date(2018, 1, 1), date(2018, 12, 31), fetch=Site())
    engine.dispose()


# --- the command -----------------------------------------------------------------------------


def test_tip_notices_is_a_feed_of_valuation_backfill_run_only_when_named(monkeypatch):
    from worker import cli

    calls = []
    monkeypatch.setattr(
        vb,
        "backfill",
        lambda *a, **k: calls.append(("sessions", k["feeds"]))
        or {
            "status": "success",
            "start": "s",
            "end": "e",
            "requests": 1,
            "aborted": None,
            "changed": 2,
            "feeds": {"twse-pb": {}},
            "duration_seconds": 1.0,
        },
    )
    monkeypatch.setattr(
        tn,
        "backfill",
        lambda *a, **k: calls.append(("tip", k["reapply"]))
        or {
            "status": "partial",
            "start": "s",
            "end": "e",
            "requests": 3,
            "aborted": None,
            "changed": 4,
            "feeds": {"tip-notices": {}},
            "duration_seconds": 2.0,
        },
    )
    vb.run_valuation_backfill("2018-01-01", "2018-12-31")
    assert calls == [("sessions", list(vb.FEEDS))]
    calls.clear()
    only = vb.run_valuation_backfill("2018-01-01", "2018-12-31", feeds=["tip-notices"])
    assert calls == [("tip", False)] and only["requests"] == 3
    calls.clear()
    both = vb.run_valuation_backfill(
        "2018-01-01", "2018-12-31", feeds=["twse-pb", "tip-notices"], reapply=True
    )
    assert calls == [("sessions", ["twse-pb"]), ("tip", True)]
    assert (both["status"], both["requests"], both["changed"]) == ("partial", 4, 6)
    assert set(both["feeds"]) == {"twse-pb", "tip-notices"}
    parser = argparse.ArgumentParser()
    action = parser.add_argument("--feed", choices=sorted(vb.FEED_CHOICES))
    assert "tip-notices" in action.choices and cli.VALUATION_FEEDS == vb.FEED_CHOICES


# --- the migration -----------------------------------------------------------------------------


def test_the_migration_adds_an_empty_table_and_goes_down_again(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config

    from app import migrations
    from app.migration_revisions import REVISIONS

    revision = "0052_index_constituent_changes"
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    table = "index_constituent_changes"
    try:
        command.upgrade(config, revision)
        assert table in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar()
                == 0
            )
            indexes = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
        assert {
            "ix_index_constituent_changes_announced_date",
            "ix_index_constituent_changes_instrument_id",
            "ix_index_constituent_changes_source_doc_id",
            "ix_index_constituent_changes_raw_payload_id",
        } <= indexes
        unique = inspect(engine).get_unique_constraints(table)
        assert [u["column_names"] for u in unique] == [
            ["index_code", "symbol", "action", "announced_date", "source_doc_id"]
        ]
        command.downgrade(config, previous)
        assert table not in inspect(engine).get_table_names()
        command.upgrade(config, revision)
        assert table in inspect(engine).get_table_names()
    finally:
        engine.dispose()
