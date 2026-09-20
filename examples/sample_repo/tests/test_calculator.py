from src.calculator import add, discount, total


def test_add():
    assert add(2, 3) == 5


def test_discount():
    assert discount(100) >= 0


def test_total_indirectly_calls_add():
    assert total(2, 3) == 5
