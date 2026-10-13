"""Static TPEx ordinary-share rules: tick ladder, trading session, seller tax, fee terms.

Pure standard library; importing this module opens no file, socket, database
or configuration. Every rule component carries the official source it was read
from (URL, SHA-256 of the saved original, retrieval time, publication and
effective dates, locator). Anything the sources do not state is reported as
``pending_evidence`` or left to an explicitly named caller input; nothing is
filled in from memory.

Callers always name the market, the security type and the rule version. A
component whose source states no effective date raises ``PendingEvidenceError``
unless the caller opts in with ``accept_published_only=True``; the result then
says ``effective_date_unverified``. Legality of a price, a price touch and a
fill are outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import (
    Context, Decimal, DecimalException, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP,
    localcontext,
)
from urllib.parse import urlsplit

RULES_VERSION = "tpex-static-rules/2026-10-12/v1"
MARKET = "TPEx"
SECURITY_TYPE = "ordinary_share"
TPE = timezone(timedelta(hours=8), name="Asia/Taipei")

_CONTEXT = Context(prec=50, rounding=ROUND_HALF_UP, Emin=-100, Emax=100)
# Input sanity bounds for Decimal arithmetic; they are not market rules.
_MAX_VALUE = Decimal("1E12")
_MIN_EXPONENT = -8
_MAX_QUANTITY = 1_000_000_000
_SOURCE_HOSTS = frozenset({
    "www.tpex.org.tw", "www.selaw.com.tw", "law-out.mof.gov.tw", "law.moj.gov.tw",
    "www.mof.gov.tw",
})
_ROUNDING = {"floor": ROUND_FLOOR, "half_up": ROUND_HALF_UP, "ceil": ROUND_CEILING}
_ONE = Decimal(1)


class ExecutionRulesError(ValueError):
    """The request is rejected; ``reason`` is a stable ``component:cause`` string."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PendingEvidenceError(ExecutionRulesError):
    """The sources do not establish the requested value; no value is returned."""


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    url: str
    sha256: str
    retrieved_at: datetime
    issuer: str
    document: str
    via: str | None
    published_on: date | None
    effective_from: date | None
    effective_through: date | None
    effective_basis: str
    locator: str


@dataclass(frozen=True)
class TickBand:
    lower_inclusive: Decimal
    upper_exclusive: Decimal | None
    tick: Decimal
    source_text: str


@dataclass(frozen=True)
class TickRules:
    bands: tuple[TickBand, ...]
    source: SourceRef
    corroboration: tuple[SourceRef, ...]


@dataclass(frozen=True)
class SessionRules:
    order_entry_open: time
    matching_open: time
    closing_call_start: time
    close: time
    deferred_open_until: time
    deferred_close_until: time
    trading_weekdays: tuple[int, ...]
    source: SourceRef
    rule_sources: tuple[SourceRef, ...]
    website_source: SourceRef


@dataclass(frozen=True)
class SellTaxRules:
    rate: Decimal
    excluded_day_trade_rate: Decimal
    source: SourceRef
    corroboration: tuple[SourceRef, ...]
    example: SourceRef
    rounding_status: str = "pending_evidence"


@dataclass(frozen=True)
class BrokerFeeRules:
    """The rule sets a notification threshold only: no uniform rate, ceiling or minimum."""

    authority: SourceRef
    corroboration: tuple[SourceRef, ...]
    notification_threshold_rate: Decimal
    official_terms_status: str = "broker_set_and_filed_no_uniform_rate_or_minimum"
    rounding_status: str = "not_stated"


@dataclass(frozen=True)
class RulePack:
    version: str
    market: str
    security_type: str
    tick: TickRules
    session: SessionRules
    sell_tax: SellTaxRules
    broker_fee: BrokerFeeRules


@dataclass(frozen=True)
class Basis:
    rule_version: str
    on_date: date
    effective_date_status: str
    published_on: date | None
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class TickQuote:
    price: Decimal
    tick: Decimal
    band_lower_inclusive: Decimal
    band_upper_exclusive: Decimal | None
    band_source_text: str
    basis: Basis


@dataclass(frozen=True)
class RoundedPriceQuote:
    price: Decimal
    direction: str
    rounded: Decimal
    tick: Decimal
    basis: Basis


@dataclass(frozen=True)
class SessionWindows:
    order_entry_open: time
    matching_open: time
    closing_call_start: time
    close: time
    deferred_open_until: time
    deferred_close_until: time
    deferred_semantics: str
    closing_call_basis: str
    basis: Basis


@dataclass(frozen=True)
class SessionQuote:
    at: time
    phase: str
    boundary_at: time | None
    boundary_semantics: str | None
    basis: Basis


@dataclass(frozen=True)
class SellTaxQuote:
    price: Decimal
    quantity: int
    notional: Decimal
    rate: Decimal
    tax_exact: Decimal
    rounding_policy: str | None
    tax_rounded: Decimal | None
    rounding_basis: str
    official_rounding_status: str
    basis: Basis


@dataclass(frozen=True)
class CallerFeeTerms:
    """Caller-declared broker terms; the sources set no uniform rate or minimum."""

    broker: str
    rate: Decimal
    discount: Decimal
    minimum: Decimal
    rounding: str


@dataclass(frozen=True)
class BrokerFeeQuote:
    broker: str
    notional: Decimal
    fee: Decimal
    minimum_applied: bool
    terms_basis: str
    official_terms_status: str
    notification_threshold_rate: Decimal
    above_notification_threshold: bool
    basis: Basis


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


_TPEX = "財團法人中華民國證券櫃檯買賣中心"
_SELAW = "證基會證券暨期貨法令判解查詢系統（彙編來源，非發布機關原件）"
_RULES = "證券商營業處所買賣有價證券業務規則"

_SRC_SYSTEM = SourceRef(
    "tpex-mainboard-system-intro",
    "https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html",
    "fd1217d8ef6e8e48769b1e4c3d2aea3b4878148b53879fd33423555d03cb291f",
    _utc("2026-10-12T11:57:32+00:00"),
    _TPEX, "上櫃有價證券交易系統簡介（官網說明頁）", None,
    None, None, None, "not_stated_on_page",
    "等價成交系統 一、交易時間（星期一至星期五、委託8:30、撮合9:00至13:30）；四、升降單位；"
    "五、撮合方式（13:25 起集合交易）",
)
_SRC_ART55 = SourceRef(
    "tpex-rules-art55-selaw-20210111",
    "https://www.selaw.com.tw/Chinese/LawDetail/LawArticleReference?lawDataid=13022101",
    "82f87349047a5173fdbf5a9e558a7956ce004d8130725b36b66e265d5a65642b",
    _utc("2026-10-12T11:58:21+00:00"),
    _TPEX, _RULES, _SELAW,
    date(2021, 1, 11), None, None, "not_stated_on_page",
    "第55條第2項（升降單位）；發佈日期民國110年1月11日版",
)
_SRC_RULES_CURRENT = SourceRef(
    "tpex-rules-current-selaw-20261005",
    "https://www.selaw.com.tw/Chinese/RegulatoryInformationResult?sysNumber=LW10812069",
    "2225a9aeec0a42b2fa56162835b8ef84e12a5bbffb2711f356a6dd120aeccf46",
    _utc("2026-10-12T11:57:56+00:00"),
    _TPEX, _RULES + "（現行法規）", _SELAW,
    date(2026, 10, 5), None, None, "not_stated_on_page",
    "沿革資訊：115-10-05 公告修正第47條，自116-04-01 起實施（僅第47條）",
)


def _current_rules(source_id: str, locator: str) -> SourceRef:
    """One article of the saved full-text page of the 2026-10-05 version."""
    return SourceRef(
        source_id,
        "https://www.selaw.com.tw/Chinese/RegulatoryInformationResult/Article"
        "?sysNumber=LW10812069&releaseDate=2026-10-05",
        "c1ddb12e0593a972ef4015b102e65e42ac37bdb186855772ea65ef51471e7d49",
        _utc("2026-10-12T12:11:07+00:00"),
        _TPEX, _RULES + "（現行法規，發佈日期民國115年10月5日）", _SELAW,
        date(2026, 10, 5), None, None, "not_stated_on_page", locator,
    )


_SRC_ART35 = _current_rules(
    "tpex-rules-art35-selaw-20261005",
    "第35條第1項（等價成交系統買賣申報得自市場交易時間開始前三十分鐘起輸入）、"
    "第4項（暫緩開市延緩二分鐘；暫緩收市一時三十一分至一時三十三分、一時三十三分撮合）",
)
_SRC_ART40 = _current_rules(
    "tpex-rules-art40-selaw-20261005",
    "第40條第1項第1款（股票採等價成交系統者為上午九時至下午一時三十分）",
)
_SRC_ART55_CURRENT = _current_rules(
    "tpex-rules-art55-selaw-20261005",
    "第55條第2項（升降單位，與2021-01-11版逐字相同；第4項兩版不同）",
)
_SRC_ART64 = _current_rules(
    "tpex-rules-art64-selaw-20261005",
    "第64條第1項（成交後收取手續費）、第2項（費率報請主管機關核定）、"
    "第3項（自行訂定費率、折讓、每筆最低費用並備查；逾千分之一點四二五應通知客戶）",
)
_SRC_OTC_MEASURES = SourceRef(
    "moj-securities-otc-trading-measures",
    "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=G0400071",
    "e15be76abf1cb5d6be5f56c5f171511ef00e43c88783042277b35e01a95082a9",
    _utc("2026-10-12T12:03:20+00:00"),
    "金融監督管理委員會", "證券商營業處所買賣有價證券管理辦法", "全國法規資料庫（法務部）",
    date(2017, 3, 31), None, None, "not_stated_on_page",
    "第7條第4、6款（業務規則應訂營業時間、價格升降單位）；第14條（手續費費率核定程序）；第18條",
)
_SRC_TAX = SourceRef(
    "mof-securities-transaction-tax-act",
    "https://law-out.mof.gov.tw/LawContent.aspx?id=FL006079&kw=b&media=print",
    "e5f6388ea66efe64e295c0757d76d6a4c0b8dd4bbc5c6394065c9ff9d2793291",
    _utc("2026-10-12T11:57:48+00:00"),
    "財政部賦稅署", "證券交易稅條例", "財政部主管法規共用系統",
    date(2025, 1, 2), None, None, "not_stated_on_page",
    "第2條第1款（股票千分之三）；第2-2條（現股當日沖銷，本版排除）；第3條；第16條",
)
_SRC_TAX_MOJ = SourceRef(
    "moj-securities-transaction-tax-act",
    "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=G0340078",
    "372ef60403bdfc4ff2108204562a209b7cf56975c99da40cf604802460bd0e48",
    _utc("2026-10-12T12:03:35+00:00"),
    "財政部賦稅署", "證券交易稅條例", "全國法規資料庫（法務部）",
    date(2025, 1, 2), None, None, "not_stated_on_page",
    "全文：第2條第1款、第2-2條、第16條；全文無稅額尾數處理條文",
)
_SRC_TAX_EXAMPLE = SourceRef(
    "mof-tax-example-20260310",
    "https://www.mof.gov.tw/%20/singlehtml/384fb3077bb349ea973e7fc6f13b6974?cntId=c29280e284a54c44a893e45b84f6efa5",
    "6a70c06754ac5d05a9ea4638fdcabbaef747e2d19c6d3b0f8526a6c69076fc66",
    _utc("2026-10-12T11:57:52+00:00"),
    "財政部臺北國稅局", "買賣有價證券應按實際成交價格繳納證券交易稅（新聞稿）", None,
    date(2026, 3, 10), None, None, "not_a_rule_example_only",
    "算例：200,000股×90元＝18,000,000元，×3‰＝54,000元",
)


def _band(lower: str, upper: str | None, tick: str, text: str) -> TickBand:
    return TickBand(Decimal(lower), None if upper is None else Decimal(upper), Decimal(tick), text)


_PACK = RulePack(
    version=RULES_VERSION,
    market=MARKET,
    security_type=SECURITY_TYPE,
    tick=TickRules(
        bands=(
            _band("0", "10", "0.01", "未滿十元者為一分"),
            _band("10", "50", "0.05", "十元至未滿五十元者為五分"),
            _band("50", "100", "0.1", "五十元至未滿一百元者為一角"),
            _band("100", "500", "0.5", "一百元至未滿五百元者為五角"),
            _band("500", "1000", "1", "五百元至未滿一千元者為一元"),
            _band("1000", None, "5", "一千元以上者為五元"),
        ),
        # The paragraph is identical in the 2021-01-11 and 2026-10-05 versions;
        # versions in between were not read, so the gate starts at 2021-01-11.
        source=_SRC_ART55,
        corroboration=(_SRC_ART55_CURRENT, _SRC_SYSTEM, _SRC_RULES_CURRENT, _SRC_OTC_MEASURES),
    ),
    session=SessionRules(
        order_entry_open=time(8, 30), matching_open=time(9, 0),
        closing_call_start=time(13, 25), close=time(13, 30),
        deferred_open_until=time(9, 2), deferred_close_until=time(13, 33),
        trading_weekdays=(0, 1, 2, 3, 4),
        source=_SRC_ART40, rule_sources=(_SRC_ART35,), website_source=_SRC_SYSTEM,
    ),
    sell_tax=SellTaxRules(
        rate=Decimal("0.003"), excluded_day_trade_rate=Decimal("0.0015"),
        source=_SRC_TAX, corroboration=(_SRC_TAX_MOJ,), example=_SRC_TAX_EXAMPLE,
    ),
    broker_fee=BrokerFeeRules(
        authority=_SRC_ART64, corroboration=(_SRC_OTC_MEASURES,),
        notification_threshold_rate=Decimal("0.001425"),
    ),
)
_PACKS = {_PACK.version: _PACK}


def pack_sources(pack: RulePack) -> tuple[SourceRef, ...]:
    """Every source the pack rests on, once each in a stable order."""
    ordered = (
        pack.tick.source, *pack.tick.corroboration,
        pack.session.source, *pack.session.rule_sources, pack.session.website_source,
        pack.sell_tax.source, *pack.sell_tax.corroboration, pack.sell_tax.example,
        pack.broker_fee.authority, *pack.broker_fee.corroboration,
    )
    unique: dict[str, SourceRef] = {}
    for src in ordered:
        if unique.setdefault(src.source_id, src) != src:
            raise ExecutionRulesError(src.source_id + ":conflicting_source_definitions")
    return tuple(unique.values())


def _validate_sources() -> None:
    for pack in _PACKS.values():
        for src in pack_sources(pack):
            url = urlsplit(src.url)
            if url.scheme != "https" or url.hostname not in _SOURCE_HOSTS:
                raise ExecutionRulesError(src.source_id + ":source_url_not_allowed")
            if len(src.sha256) != 64 or any(c not in "0123456789abcdef" for c in src.sha256):
                raise ExecutionRulesError(src.source_id + ":sha256_invalid")
            if src.retrieved_at.tzinfo is None or not src.locator or not src.document:
                raise ExecutionRulesError(src.source_id + ":source_fields_missing")
            if src.effective_through is not None and (
                src.effective_from is None or src.effective_through < src.effective_from
            ):
                raise ExecutionRulesError(src.source_id + ":effective_range_invalid")


_validate_sources()


def get_rule_pack(version: object) -> RulePack:
    """Read one named version; an unknown version is never replaced by a latest."""
    if type(version) is not str or version not in _PACKS:
        raise ExecutionRulesError("rule_version:unknown_or_unsupported")
    return _PACKS[version]


def _scope(market: object, security_type: object, version: object) -> RulePack:
    if type(market) is not str or market != MARKET:
        raise ExecutionRulesError("market:unknown_or_unsupported")
    if type(security_type) is not str or security_type != SECURITY_TYPE:
        raise ExecutionRulesError("security_type:unknown_or_unsupported")
    return get_rule_pack(version)


def _gate(pack: RulePack, source: SourceRef, extra: tuple[SourceRef, ...], label: str,
          on_date: object, accept_published_only: object) -> Basis:
    """Date window of one component, judged on its gating ``source``."""
    if type(on_date) is not date:
        raise ExecutionRulesError("on_date:date_required")
    if type(accept_published_only) is not bool:
        raise ExecutionRulesError("accept_published_only:bool_required")
    if on_date > source.retrieved_at.astimezone(TPE).date():
        raise ExecutionRulesError(label + ":after_verified_date")
    if source.effective_through is not None and on_date > source.effective_through:
        raise ExecutionRulesError(label + ":after_effective_through")
    if source.effective_from is not None:
        if on_date < source.effective_from:
            raise ExecutionRulesError(label + ":before_effective_from")
        status = "effective_date_stated"
    else:
        if source.published_on is not None and on_date < source.published_on:
            raise ExecutionRulesError(label + ":before_published_date")
        if not accept_published_only:
            raise PendingEvidenceError(label + ":effective_date_unverified")
        status = "effective_date_unverified"
    ids = tuple(dict.fromkeys(s.source_id for s in (source, *extra)))
    return Basis(pack.version, on_date, status, source.published_on, ids)


def _decimal(value: object, label: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ExecutionRulesError(label + ":finite_decimal_required")
    if value.as_tuple().exponent < _MIN_EXPONENT or not 0 <= value <= _MAX_VALUE:
        raise ExecutionRulesError(label + ":outside_supported_range")
    if positive and not value:
        raise ExecutionRulesError(label + ":positive_decimal_required")
    return value


def _band_for(price: Decimal, rules: TickRules) -> TickBand:
    for band in rules.bands:
        if band.upper_exclusive is None or price < band.upper_exclusive:
            return band
    raise ExecutionRulesError("tick:uncovered_price")


def tick_size(price: object, *, market: object, security_type: object, on_date: object,
              rule_version: object, accept_published_only: object = False) -> TickQuote:
    """Tick (升降單位) for a price; band lower bounds are inclusive, uppers exclusive."""
    pack = _scope(market, security_type, rule_version)
    basis = _gate(pack, pack.tick.source, pack.tick.corroboration[:1], "tick", on_date,
                  accept_published_only)
    value = _decimal(price, "price", positive=True)
    band = _band_for(value, pack.tick)
    return TickQuote(value, band.tick, band.lower_inclusive, band.upper_exclusive,
                     band.source_text, basis)


def round_price(price: object, direction: object, *, market: object, security_type: object,
                on_date: object, rule_version: object,
                accept_published_only: object = False) -> RoundedPriceQuote:
    """Round to the tick of the band holding ``price``; ``up`` is ceiling, ``down`` floor."""
    if type(direction) is not str or direction not in {"up", "down"}:
        raise ExecutionRulesError("direction:up_or_down_required")
    quote = tick_size(price, market=market, security_type=security_type, on_date=on_date,
                      rule_version=rule_version, accept_published_only=accept_published_only)
    mode = ROUND_CEILING if direction == "up" else ROUND_FLOOR
    with localcontext(_CONTEXT):
        rounded = (quote.price / quote.tick).to_integral_value(rounding=mode) * quote.tick
    if rounded <= 0:
        raise ExecutionRulesError("rounded_price:not_positive")
    # Every band boundary is a multiple of both neighbouring ticks, so rounding
    # inside a band cannot leave the ladder; keep the check as a guard anyway.
    if rounded % _band_for(rounded, get_rule_pack(rule_version).tick).tick:
        raise ExecutionRulesError("rounded_price:not_on_tick")
    return RoundedPriceQuote(quote.price, direction, rounded, quote.tick, quote.basis)


def session_windows(*, market: object, security_type: object, on_date: object,
                    rule_version: object, accept_published_only: object = False) -> SessionWindows:
    """Clock times of the 等價成交系統 on a Monday-to-Friday date.

    09:00 and 13:30 come from rule article 40, the order-entry start from article 35
    (thirty minutes before 09:00). The 13:25 start of the closing call is stated only
    on the TPEx website: the rule text leaves that period's length to a separate
    standard. Deferred open and close apply only to securities meeting the deferral
    standard. Holidays and temporary closures are a calendar question, not answered here.
    """
    pack = _scope(market, security_type, rule_version)
    rules = pack.session
    basis = _gate(pack, rules.source, (*rules.rule_sources, rules.website_source), "session",
                  on_date, accept_published_only)
    if on_date.weekday() not in rules.trading_weekdays:
        raise ExecutionRulesError("session:not_a_stated_trading_weekday")
    return SessionWindows(
        rules.order_entry_open, rules.matching_open, rules.closing_call_start, rules.close,
        rules.deferred_open_until, rules.deferred_close_until,
        "only_for_securities_meeting_the_deferral_standard",
        "website_description_only_not_in_rule_text", basis,
    )


def session_phase(at: object, *, market: object, security_type: object, on_date: object,
                  rule_version: object, accept_published_only: object = False) -> SessionQuote:
    """Classify a wall-clock time (Asia/Taipei, naive ``time``) in the base schedule.

    The sources give each boundary as "A 至 B" without saying which ends are
    included, so an exact boundary instant is reported as ``boundary`` with
    ``boundary_semantics="unspecified_by_source"`` rather than assigned a side.
    """
    if type(at) is not time or at.tzinfo is not None:
        raise ExecutionRulesError("at:naive_time_required")
    win = session_windows(market=market, security_type=security_type, on_date=on_date,
                          rule_version=rule_version, accept_published_only=accept_published_only)
    marks = (win.order_entry_open, win.matching_open, win.closing_call_start, win.close)
    if at in marks:
        return SessionQuote(at, "boundary", at, "unspecified_by_source", win.basis)
    if at < win.order_entry_open or at > win.close:
        phase = "closed"
    elif at < win.matching_open:
        phase = "order_entry_before_open"
    elif at < win.closing_call_start:
        phase = "continuous_matching"
    else:
        phase = "closing_call_auction"
    return SessionQuote(at, phase, None, None, win.basis)


def sell_tax(*, price: object, quantity: object, day_trade: object, market: object,
             security_type: object, on_date: object, rule_version: object,
             rounding: object = None, accept_published_only: object = False) -> SellTaxQuote:
    """Seller's securities transaction tax of a non-day-trade ordinary share.

    ``tax_exact`` is price x quantity x 0.003 with no rounding. The sources set no
    rule for the sub-dollar remainder, so ``official_rounding_status`` stays
    ``pending_evidence``; a ``rounding`` name (floor, half_up, ceil) is the
    caller's declared policy and is labelled as such. The tax act's page gives an
    amendment date but no effective date, so, like the other components, a value
    needs ``accept_published_only=True``.
    """
    pack = _scope(market, security_type, rule_version)
    basis = _gate(pack, pack.sell_tax.source, pack.sell_tax.corroboration, "sell_tax", on_date,
                  accept_published_only)
    if type(day_trade) is not bool:
        raise ExecutionRulesError("day_trade:bool_required")
    if day_trade:
        raise ExecutionRulesError("sell_tax:day_trade_rate_not_supported")
    if rounding is not None and (type(rounding) is not str or rounding not in _ROUNDING):
        raise ExecutionRulesError("rounding:unsupported_policy")
    value = _decimal(price, "price", positive=True)
    if type(quantity) is not int or not 0 < quantity <= _MAX_QUANTITY:
        raise ExecutionRulesError("quantity:positive_int_required")
    try:
        with localcontext(_CONTEXT):
            notional = value * quantity
            exact = notional * pack.sell_tax.rate
            rounded = None
            if rounding is not None:
                rounded = exact.quantize(_ONE, rounding=_ROUNDING[rounding])
    except DecimalException as exc:
        raise ExecutionRulesError("decimal:unsupported_operation") from exc
    return SellTaxQuote(
        value, quantity, notional, pack.sell_tax.rate, exact, rounding, rounded,
        "not_defined_by_sources" if rounding is None else "caller_declared:" + rounding,
        pack.sell_tax.rounding_status, basis,
    )


def broker_fee(*, notional: object, terms: object, market: object, security_type: object,
               on_date: object, rule_version: object,
               accept_published_only: object = False) -> BrokerFeeQuote:
    """Brokerage fee from caller-declared terms.

    Rule article 64 lets each broker set its own rate, discount and per-order
    minimum, filed with the TPEx; 1.425‰ is the rate above which customers must be
    notified in advance, not a ceiling. No uniform rate, minimum or rounding is
    stated, so all of them are the caller's. fee = max(notional x rate x discount,
    minimum), rounded to whole NT$ by the declared policy; the minimum must be a
    whole-dollar amount so the order of "minimum" and "rounding" cannot matter.
    """
    pack = _scope(market, security_type, rule_version)
    rules = pack.broker_fee
    basis = _gate(pack, rules.authority, rules.corroboration, "broker_fee", on_date,
                  accept_published_only)
    if type(terms) is not CallerFeeTerms:
        raise ExecutionRulesError("terms:caller_fee_terms_required")
    if type(terms.broker) is not str or not terms.broker.strip():
        raise ExecutionRulesError("terms.broker:nonempty_string_required")
    rate = _decimal(terms.rate, "terms.rate")
    discount = _decimal(terms.discount, "terms.discount", positive=True)
    minimum = _decimal(terms.minimum, "terms.minimum")
    if rate >= 1 or discount > 1:
        raise ExecutionRulesError("terms:rate_or_discount_out_of_range")
    if minimum != minimum.to_integral_value():
        raise ExecutionRulesError("terms.minimum:whole_dollar_required")
    if type(terms.rounding) is not str or terms.rounding not in _ROUNDING:
        raise ExecutionRulesError("terms.rounding:unsupported_policy")
    amount = _decimal(notional, "notional", positive=True)
    try:
        with localcontext(_CONTEXT):
            raw = amount * rate * discount
            rounded = raw.quantize(_ONE, rounding=_ROUNDING[terms.rounding])
    except DecimalException as exc:
        raise ExecutionRulesError("decimal:unsupported_operation") from exc
    return BrokerFeeQuote(
        terms.broker, amount, max(rounded, minimum), rounded < minimum, "caller_declared",
        rules.official_terms_status, rules.notification_threshold_rate,
        rate > rules.notification_threshold_rate, basis,
    )
