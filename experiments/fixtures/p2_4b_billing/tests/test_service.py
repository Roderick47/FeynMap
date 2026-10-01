from types import SimpleNamespace

import pytest

from billing.policy import OverpaymentError
from billing.service import apply_payment, retry_payment


def test_overpayment_leaves_balance_unchanged():
    invoice = SimpleNamespace(id="INV-7", outstanding_cents=5000, status="open")
    with pytest.raises(OverpaymentError):
        apply_payment(invoice, 7000)
    assert invoice.outstanding_cents == 5000
    assert invoice.status == "open"


def test_exact_payment_marks_invoice_paid():
    invoice = SimpleNamespace(id="INV-8", outstanding_cents=2500, status="open")
    result = apply_payment(invoice, 2500)
    assert invoice.outstanding_cents == 0
    assert invoice.status == "paid"
    assert result == "PAYMENT:INV-8:0"


def test_retry_policy_accepts_declined_and_timeout_only():
    assert retry_payment("declined") is True
    assert retry_payment("timeout") is True
    assert retry_payment("paid") is False
