def final_price(price: float, discount_pct: float) -> float:
    """Price after a percentage discount, rounded to cents."""
    return round(price - price * discount_pct, 2)
