"""30 intentionally mixed-strength tests for the 30 checkout functions.

A passing baseline alone does not imply good mutation detection.
Tests in the first section deliberately check only a type; the second
section tests a property that just one mutant violates; the third
section checks concrete behavior and rejects both default-return mutants.
"""

from src import checkout as c


# 01–06: WEAK — both mutants SURVIVE.

def _receipt_subtotal(prices):
    """An intentionally indirect test call for the static/dynamic selector."""
    return c.subtotal_cents(prices)


def test_subtotal_cents_weak():
    assert type(_receipt_subtotal([120, 350])) is int


def test_loyalty_points_weak():
    assert type(c.loyalty_points(750)) is int


def test_discounted_price_weak():
    assert type(c.discounted_price(40.0, 0.25)) is float


def test_normalize_sku_weak():
    assert type(c.normalize_sku("  a-12  ")) is str


def test_qualifies_free_shipping_weak():
    assert type(c.qualifies_free_shipping(6000)) is bool


def test_student_discount_eligible_weak():
    assert type(c.student_discount_eligible(True, False)) is bool


# 07–15: PARTIAL — one mutant KILLED, the other SURVIVES.

def test_shipping_fee_cents_partial():
    assert c.shipping_fee_cents(2000) >= 1


def test_change_due_cents_partial():
    assert c.change_due_cents(1000, 700) >= 1


def test_tax_amount_partial():
    assert c.tax_amount(100.0, 0.08) >= 1.0


def test_convert_currency_partial():
    assert c.convert_currency(20.0, 1.5) >= 1.0


def test_badge_text_partial():
    assert len(c.badge_text(3)) > 0


def test_order_code_partial():
    assert len(c.order_code(72)) > 0


def test_has_valid_coupon_partial():
    assert c.has_valid_coupon("SAVE20") is True


def test_is_weekend_partial():
    assert c.is_weekend(6) is True


def test_meets_age_requirement_partial():
    assert c.meets_age_requirement(21) is True


# 16–30: DETECTED — both mutants KILLED.

def test_percentage_discount_cents():
    assert c.percentage_discount_cents(1200, 25) == 300


def test_cap_quantity():
    assert c.cap_quantity(7, 5) == 5


def test_items_per_box():
    assert c.items_per_box(17, 5) == 3


def test_earned_stamps():
    assert c.earned_stamps(4) == 8


def test_split_bill():
    assert c.split_bill(55.0, 2) == 27.5


def test_calculate_tip():
    assert c.calculate_tip(60.0, 0.15) == 9.0


def test_service_charge():
    assert c.service_charge(24.5, 2.0) == 26.5


def test_mask_customer_id():
    assert c.mask_customer_id("ABCD1234") == "****1234"


def test_build_receipt_line():
    assert c.build_receipt_line(" tea ", 2) == "Tea x2"


def test_format_tracking_code():
    assert c.format_tracking_code(42) == "TRK-000042"


def test_initials():
    assert c.initials("Runa", "Hasegawa") == "R.H."


def test_is_even_quantity():
    assert c.is_even_quantity(4) is True
    assert c.is_even_quantity(5) is False


def test_is_valid_pin():
    assert c.is_valid_pin("1234") is True
    assert c.is_valid_pin("12a4") is False


def test_is_positive_balance():
    assert c.is_positive_balance(100) is True
    assert c.is_positive_balance(0) is False


def test_is_bulk_order():
    assert c.is_bulk_order(10) is True
    assert c.is_bulk_order(9) is False
