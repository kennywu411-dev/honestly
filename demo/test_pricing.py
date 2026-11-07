from pricing import final_price


def test_ten_percent_off():
    assert final_price(100, 10) == 90.0


def test_no_discount():
    assert final_price(59.99, 0) == 59.99


def test_never_negative():
    assert final_price(20, 150) == 0.0


def test_half_cent_rounds_up():
    assert final_price(10.05, 50) == 5.03
