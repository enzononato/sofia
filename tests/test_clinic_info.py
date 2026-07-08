"""
Unit tests for app.services.ai_tools:
  - _get_clinic_info(): installments normalization (async, no DB access).
  - _normalize_service_price(): module-level pure function (extracted from the
    nested _price() that used to live inside _list_services()).
"""

from decimal import Decimal

import pytest

from app.services.ai_tools import (
    _evaluation_policy_info,
    _get_clinic_info,
    _normalize_service_price,
)

# asyncio_mode=auto (pytest.ini) runs async tests without a marker, so no
# module-level pytestmark — that would wrongly tag the sync price test too.

_NOT_CONFIGURED_MSG = (
    "Parcelamento não configurado — a quantidade de parcelas é combinada na "
    "clínica; NÃO invente um número."
)


@pytest.mark.parametrize("raw", [None, 0, 1, "abc"])
async def test_max_installments_unset_or_invalid_reports_not_configured(raw):
    tenant_settings = {"clinic": {"max_installments": raw}} if raw is not None else {"clinic": {}}
    info = await _get_clinic_info(tenant_settings, tenant_name="Clínica Teste")
    assert info["max_installments"] is None
    assert info["installments_info"] == _NOT_CONFIGURED_MSG


async def test_max_installments_absent_key_reports_not_configured():
    info = await _get_clinic_info({"clinic": {}}, tenant_name="Clínica Teste")
    assert info["max_installments"] is None
    assert info["installments_info"] == _NOT_CONFIGURED_MSG


async def test_max_installments_configured_reports_number():
    info = await _get_clinic_info({"clinic": {"max_installments": 6}}, tenant_name="Clínica Teste")
    assert info["max_installments"] == 6
    assert "6" in info["installments_info"]
    assert info["installments_info"] == "Parcelamento em até 6x no cartão de crédito."


@pytest.mark.parametrize(
    "price,expected",
    [
        (None, None),
        (Decimal("0"), None),
        (0, None),
        (Decimal("-5"), None),
        (Decimal("150.00"), "150.00"),
    ],
)
def test_normalize_service_price(price, expected):
    assert _normalize_service_price(price) == expected


# ── Evaluation/consultation pricing policy ───────────────────────────────────
# Sofia invented "a consulta é de graça" in production. The policy must be
# explicit: unset → never claim free/paid; free → says free; paid → the value.

def test_evaluation_policy_unset_forbids_claiming_free_or_paid():
    msg = _evaluation_policy_info({})
    assert "NÃO configurada" in msg or "NÃO afirme" in msg
    # Must not assert a definite free/paid stance.
    assert "gratuita" not in msg.lower().replace("não afirme que a avaliação é gratuita", "")


def test_evaluation_policy_free():
    msg = _evaluation_policy_info({"evaluation_fee_mode": "free"})
    assert "GRATUITA" in msg or "gratuita" in msg.lower()


def test_evaluation_policy_paid_with_value():
    msg = _evaluation_policy_info({"evaluation_fee_mode": "paid", "evaluation_fee": 100})
    assert "100" in msg
    assert "abat" not in msg.lower()  # not deductible unless flagged


def test_evaluation_policy_paid_deductible():
    msg = _evaluation_policy_info(
        {"evaluation_fee_mode": "paid", "evaluation_fee": 100, "evaluation_fee_deductible": True}
    )
    assert "100" in msg
    assert "ABATIDO" in msg or "abat" in msg.lower()


def test_evaluation_policy_paid_without_value_stays_vague():
    # "paid" but no number: must not invent a value, still signals there's a cost.
    msg = _evaluation_policy_info({"evaluation_fee_mode": "paid"})
    assert "custa" in msg.lower()


@pytest.mark.parametrize("bad", [0, -5, "abc", None])
def test_evaluation_policy_paid_ignores_invalid_fee(bad):
    settings = {"evaluation_fee_mode": "paid"}
    if bad is not None:
        settings["evaluation_fee"] = bad
    msg = _evaluation_policy_info(settings)
    # No "R$ 0,00" and no crash — falls back to a vague "valor definido na clínica".
    assert "0,00" not in msg
    assert "custa" in msg.lower()


async def test_get_clinic_info_exposes_evaluation_info():
    info = await _get_clinic_info(
        {"clinic": {"evaluation_fee_mode": "free"}}, tenant_name="Clínica Teste"
    )
    assert "evaluation_info" in info
    assert "gratuita" in info["evaluation_info"].lower()
