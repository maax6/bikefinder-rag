from bikefinder_rag.scraper.categories import is_included, parse_displacement_ccm


def test_atv_always_excluded():
    assert not is_included("ATV", 1000.0)
    assert not is_included("ATV", None)


def test_small_scooter_excluded():
    assert not is_included("Scooter", 125.0)
    assert not is_included("Scooter", None)


def test_big_scooter_included():
    # Honda X-ADV, Yamaha TMAX territory.
    assert is_included("Scooter", 745.0)
    assert is_included("Scooter", 500.0)


def test_minibike_and_prototype_kept():
    assert is_included("Minibike, cross", 50.0)
    assert is_included("Prototype/concept model", None)


def test_ordinary_category_kept():
    assert is_included("Naked bike", 650.0)


def test_parse_displacement_ccm():
    assert parse_displacement_ccm("745 ccm") == 745.0
    assert parse_displacement_ccm("124 ccm") == 124.0
    assert parse_displacement_ccm("Electric") is None
