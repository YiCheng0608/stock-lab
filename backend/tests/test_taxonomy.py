from datetime import date
import json
from pathlib import Path

import pytest

from app.models import GroupMembership, Instrument, ThemeGroup
from app.news import _is_verified_theme_for_instrument
from app.taxonomy import canonical_group_id, canonical_industry_label


def _group(label: str) -> ThemeGroup:
    return ThemeGroup(
        id=canonical_group_id("industry", label),
        name=f"Industry · {label}",
        group_type="official_industry",
        display_name_zh={
            "Biotechnology": "生技醫療",
            "Information Service": "資訊服務",
            "Shipping": "航運",
            "Communications": "通信網路",
            "Green Energy": "綠能環保",
            "Financial": "金融",
        }[label],
        name_status="official",
        active=True,
    )


def test_exchange_code_namespaces_are_normalised_before_grouping():
    assert canonical_industry_label("TWSE", "22") == "Biotechnology"
    assert canonical_industry_label("TPEx", "22") == "Biotechnology"
    assert canonical_industry_label("TPEx", "30") == "Information Service"
    assert canonical_industry_label("TWSE", "30") == "Information Service"
    assert canonical_industry_label("TPEx", "91") is None


@pytest.mark.parametrize(('code', 'label'), [
    ('18','Wholesale and Retail'), ('19','Composite'), ('20','Other'),
    ('21','Chemical'), ('22','Biotechnology'), ('23','Oil, Gas and Electricity'),
    ('24','Semiconductor'), ('25','Computer and Peripherals'), ('26','Optoelectronics'),
    ('27','Communications'), ('28','Electronic Parts'), ('29','Electronic Distribution'),
    ('30','Information Service'), ('31','Other Electronics'),
])
def test_twse_official_appendix_codes(code, label):
    # TWSE IP specification B.12.00 Appendix 3, printed page 92.
    assert canonical_industry_label('TWSE',code) == label


@pytest.mark.parametrize('exchange', [None, '', 'UNKNOWN', 'NYSE'])
@pytest.mark.parametrize('value', ['22', 'Biotechnology', 'semi'])
def test_unsupported_exchange_fails_closed_even_for_text(exchange, value):
    assert canonical_industry_label(exchange,value) is None


@pytest.mark.parametrize('value', [None,'','00','07','13','91','ETF','garbage','22.0'])
def test_unknown_not_promoted_to_official_group(value):
    assert canonical_industry_label('TWSE', value) is None


def test_market_specific_categories_and_normalized_labels():
    assert canonical_industry_label('TWSE','19') == 'Composite'
    assert canonical_industry_label('TPEx','19') is None
    assert canonical_industry_label('TWSE','32') is None
    assert canonical_industry_label('TPEx','32') == 'Cultural Innovation'
    assert canonical_industry_label('TWSE','33') is None
    assert canonical_industry_label('TPEx','33') == 'Agriculture Technology'
    assert canonical_industry_label(' tWsE ','2') == 'Food'
    assert canonical_industry_label('TPEx','semi') == 'Semiconductor'


@pytest.mark.parametrize('code', ['01','09','12','18','19'])
def test_twse_exclusive_codes_do_not_leak_to_tpex(code):
    assert canonical_industry_label('TWSE',code) is not None
    assert canonical_industry_label('TPEx',code) is None


@pytest.mark.parametrize('code', ['80','91','34'])
@pytest.mark.parametrize('exchange', ['TWSE','TPEx'])
def test_special_or_removed_codes_are_not_industry_rankings(exchange,code):
    assert canonical_industry_label(exchange,code) is None


@pytest.mark.parametrize('code', ['02','03','04','05','06','08','10','11','14','15','16','17',
                                 '20','21','22','23','24','25','26','27','28','29','30','31','35','36','37','38'])
def test_official_shared_codes_have_same_meaning(code):
    assert canonical_industry_label('TWSE',code) == canonical_industry_label('TPEx',code)
    assert canonical_industry_label('TWSE',code) is not None


def test_complete_ordinary_code_sets_match_independent_official_transcription():
    from app.taxonomy import INDUSTRY_CODE_TO_CANONICAL_BY_EXCHANGE
    fixture = json.loads((Path(__file__).parent/'fixtures'/'official_industry_codes.json').read_text(encoding='utf-8'))
    for exchange in ('TWSE','TPEX'):
        assert set(INDUSTRY_CODE_TO_CANONICAL_BY_EXCHANGE[exchange]) == set(fixture[exchange])


def test_news_theme_validation_rejects_cross_exchange_code_collision():
    instrument = Instrument(
        exchange="TPEx",
        symbol="4105",
        name="東洋",
        industry="22",
        instrument_type="stock",
        status="active",
    )
    membership = GroupMembership(
        group_id=canonical_group_id("industry", "Shipping"),
        instrument_id=1,
        valid_from=date(2020, 1, 1),
        source="TWSE/TPEx official OpenAPI; exchange=TPEx",
    )
    assert not _is_verified_theme_for_instrument(_group("Shipping"), membership, instrument)

    correct = _group("Biotechnology")
    membership.group_id = correct.id
    assert _is_verified_theme_for_instrument(correct, membership, instrument)


@pytest.mark.parametrize(
    ("symbol", "industry", "wrong_label", "correct_label"),
    [
        ("4105", "22", "Shipping", "Biotechnology"),
        ("6023", "17", "Communications", "Financial"),
        ("8272", "30", "Green Energy", "Information Service"),
    ],
)
def test_news_theme_validation_rejects_known_tpex_code_collisions(
    symbol, industry, wrong_label, correct_label
):
    instrument = Instrument(
        exchange="TPEx",
        symbol=symbol,
        name="fixture",
        industry=industry,
        instrument_type="stock",
        status="active",
    )
    membership = GroupMembership(
        group_id=canonical_group_id("industry", wrong_label),
        instrument_id=1,
        valid_from=date(2020, 1, 1),
        source="TWSE/TPEx official OpenAPI; exchange=TPEx",
    )
    assert not _is_verified_theme_for_instrument(_group(wrong_label), membership, instrument)
    membership.group_id = canonical_group_id("industry", correct_label)
    assert _is_verified_theme_for_instrument(_group(correct_label), membership, instrument)
