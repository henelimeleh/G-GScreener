import app


def test_normalize_uses_massive_starter_fields():
    stock = app.normalize_snapshot({
        "ticker": "ABC",
        "todaysChangePerc": 7.25,
        "min": {"c": 53.625, "av": 1_750_000},
        "prevDay": {"c": 50},
    })

    assert stock["price"] == 53.625
    assert stock["volume"] == 1_750_000
    assert stock["gap"] == 7.25


def test_demo_has_gap_up_gap_down_and_rvol():
    gap_up, gap_down, rvol = app.demo()

    assert gap_up[0]["gap_pct"] > 0
    assert gap_down[0]["gap_pct"] < 0
    assert rvol[0]["rvol"] >= 5
