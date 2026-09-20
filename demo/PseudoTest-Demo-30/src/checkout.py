"""Campus Shop checkout helpers — 30 ordinary synchronous functions.

This module intentionally includes three kinds of existing tests:
* WEAK: both default-return mutants survive.
* PARTIAL: one default-return mutant survives.
* STRONG (for this mutation strategy): both mutants are killed.

All 30 functions are top-level, undecorated, and return exactly one of
int, float, str, or bool under the provided pytest suite.
"""


# 01–06: WEAK TESTS — the current test suite accepts both constant mutants.

def subtotal_cents(prices: list[int]) -> int:
    """Add prices in cents; e.g. [120, 350] -> 470."""
    return sum(prices)


def loyalty_points(spend_cents: int) -> int:
    """Award one point per complete 100 cents spent."""
    return spend_cents // 100


def discounted_price(price: float, rate: float) -> float:
    """Apply a decimal discount rate to a price."""
    return round(price * (1.0 - rate), 2)


def normalize_sku(raw: str) -> str:
    """Strip whitespace and capitalize a stock-keeping unit."""
    return raw.strip().upper()


def qualifies_free_shipping(total_cents: int) -> bool:
    """Shipping is free on orders of at least 5000 cents."""
    return total_cents >= 5000


def student_discount_eligible(is_student: bool, expired: bool) -> bool:
    """A student receives a discount only with an unexpired status."""
    return is_student and not expired


# 07–15: PARTIAL TESTS — exactly one constant mutant is rejected.

def shipping_fee_cents(subtotal: int) -> int:
    """Charge 499 cents for orders below 5000 cents."""
    return 0 if subtotal >= 5000 else 499


def change_due_cents(paid: int, amount_due: int) -> int:
    """Return nonnegative change to give a customer."""
    return max(paid - amount_due, 0)


def tax_amount(price: float, rate: float) -> float:
    """Compute sales tax in dollars."""
    return round(price * rate, 2)


def convert_currency(amount: float, usd_rate: float) -> float:
    """Convert an amount to USD given a per-unit exchange rate."""
    return round(amount * usd_rate, 2)


def badge_text(level: int) -> str:
    """Choose a loyalty badge name."""
    return "VIP" if level >= 3 else "STANDARD"


def order_code(number: int) -> str:
    """Format a numeric order ID."""
    return f"ORD-{number:05d}"


def has_valid_coupon(code: str) -> bool:
    """Accept nontrivial coupon codes beginning with SAVE."""
    return code.startswith("SAVE") and len(code) >= 6


def is_weekend(day_number: int) -> bool:
    """Treat Saturday (5) and Sunday (6) as weekend days."""
    return day_number in (5, 6)


def meets_age_requirement(age: int) -> bool:
    """Customers must be at least 18 years old."""
    return age >= 18


# 16–30: MUTANTS DETECTED — existing tests reject both constant mutants.

def percentage_discount_cents(price_cents: int, percent: int) -> int:
    """Compute an integer-percent discount in cents."""
    return price_cents * percent // 100


def cap_quantity(requested: int, stock: int) -> int:
    """Clamp a requested item count to [0, stock]."""
    return min(max(requested, 0), stock)


def items_per_box(items: int, box_count: int) -> int:
    """Compute how many complete items fit in each box."""
    return items // box_count


def earned_stamps(items_bought: int) -> int:
    """Give two stamps per purchased item."""
    return items_bought * 2


def split_bill(total: float, people: int) -> float:
    """Split a bill evenly in dollars."""
    return round(total / people, 2)


def calculate_tip(total: float, rate: float) -> float:
    """Calculate a tip in dollars."""
    return round(total * rate, 2)


def service_charge(total: float, fee: float) -> float:
    """Add a fixed service fee in dollars."""
    return round(total + fee, 2)


def mask_customer_id(customer_id: str) -> str:
    """Hide all but the final four characters."""
    return "*" * max(len(customer_id) - 4, 0) + customer_id[-4:]


def build_receipt_line(item: str, quantity: int) -> str:
    """Build a single item line on a receipt."""
    return f"{item.strip().title()} x{quantity}"


def format_tracking_code(number: int) -> str:
    """Give a human-readable parcel tracking code."""
    return f"TRK-{number:06d}"


def initials(first: str, last: str) -> str:
    """Create capitalized initials for a customer name."""
    return f"{first[0].upper()}.{last[0].upper()}."


def is_even_quantity(quantity: int) -> bool:
    """Check whether the quantity is even."""
    return quantity % 2 == 0


def is_valid_pin(pin: str) -> bool:
    """Accept exactly four numeric characters."""
    return len(pin) == 4 and pin.isdigit()


def is_positive_balance(balance_cents: int) -> bool:
    """Check whether a store-credit balance is positive."""
    return balance_cents > 0


def is_bulk_order(quantity: int) -> bool:
    """Treat ten or more items as a bulk order."""
    return quantity >= 10
