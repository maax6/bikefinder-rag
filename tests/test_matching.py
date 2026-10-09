import pytest

from bikefinder_rag.matching import MotorcycleMatcher


@pytest.mark.parametrize(
    ("brand", "source", "target"),
    [
        ("Honda", "CBF 500", "CBF 600 N"),
        ("Suzuki", "GSF 650 Bandit S", "GSF1250S Bandit"),
        ("Suzuki", "M 1500 Intruder", "Intruder M800"),
        ("Honda", "CB 500", "CB 750"),
        ("Honda", "CB 500 Four", "CB Four"),
    ],
)
def test_does_not_drop_distinctive_model_numbers(brand, source, target):
    matcher = MotorcycleMatcher([(1, brand, target, 2009)])

    assert matcher.match_explained(brand, source, 2009) == ([], None, None)


@pytest.mark.parametrize(
    ("brand", "source", "target"),
    [
        ("Yamaha", "YZF-R1 1000", "YZF-R1"),
        ("Kawasaki", "ZX-10R 1000", "Ninja ZX-10R"),
        ("Kawasaki", "ZX-10R1000", "Ninja ZX-10R"),
        ("Yamaha", "MT-07 700", "MT-07"),
    ],
)
def test_ignores_redundant_displacement_suffix(brand, source, target):
    matcher = MotorcycleMatcher([(1, brand, target, 2020)])

    assert matcher.match_explained(brand, source, 2020) == ([1], 0, "no-suffix")


def test_suffix_fallback_preserves_the_model_number():
    matcher = MotorcycleMatcher([(1, "Yamaha", "YZF-R6", 2020)])

    assert matcher.match_explained("Yamaha", "YZF-R1 1000", 2020) == ([], None, None)


def test_suffix_fallback_rejects_conflicting_extra_number_in_target():
    matcher = MotorcycleMatcher([(1, "Yamaha", "YZF-R1 600", 2020)])

    assert matcher.match_explained("Yamaha", "YZF-R1 1000", 2020) == ([], None, None)


def test_number_in_middle_is_not_treated_as_a_displacement_suffix():
    matcher = MotorcycleMatcher([(1, "Yamaha", "MT-07 SP", 2020)])

    assert matcher.match_explained("Yamaha", "MT-07 700 SP", 2020) == ([], None, None)


@pytest.mark.parametrize(
    ("brand", "source", "row_brand", "target"),
    [
        ("Suzuki", "Bandit 1250", "Suzuki", "GSF 1250 Bandit"),
        ("Ducati", "1098 R", "Ducati", "Superbike 1098 R"),
        ("MV Agusta", "Brutale 800", "MV", "Agusta Brutale 800"),
        ("Moto Guzzi", "V7 Stone", "Moto", "Guzzi V7 Stone"),
    ],
)
def test_forward_matching_keeps_prefix_and_multiword_brand_support(brand, source, row_brand, target):
    matcher = MotorcycleMatcher([(1, row_brand, target, 2020)])

    assert matcher.match_explained(brand, source, 2020) == ([1], 0, "forward")


def test_exact_match_wins_over_suffix_fallback():
    matcher = MotorcycleMatcher([
        (1, "Yamaha", "YZF-R1", 2020),
        (2, "Yamaha", "YZF-R1 1000", 2020),
    ])

    assert matcher.match_explained("Yamaha", "YZF-R1 1000", 2020) == ([2], 0, "forward")


def test_forward_matching_keeps_the_tightest_variant():
    matcher = MotorcycleMatcher([
        (1, "Honda", "CBF 500 N ABS", 2004),
        (2, "Honda", "CBF 500 N", 2004),
        (3, "Honda", "CBF 600 N", 2004),
    ])

    assert matcher.match_explained("Honda", "CBF 500", 2004) == ([2], 0, "forward")


def test_equally_specific_matches_remain_explicitly_ambiguous():
    matcher = MotorcycleMatcher([
        (1, "Honda", "CBF 500 N", 2004),
        (2, "Honda", "CBF 500 S", 2004),
    ])

    assert matcher.match_explained("Honda", "CBF 500", 2004) == ([1, 2], 0, "forward")


def test_suffix_fallback_keeps_equally_specific_variants():
    matcher = MotorcycleMatcher([
        (1, "Yamaha", "YZF-R1 M", 2020),
        (2, "Yamaha", "YZF-R1 SP", 2020),
    ])

    assert matcher.match_explained("Yamaha", "YZF-R1 1000", 2020) == ([1, 2], 0, "no-suffix")


def test_reverse_matching_keeps_valid_verbose_names():
    matcher = MotorcycleMatcher([(1, "Ducati", "1098 R", 2008)])

    assert matcher.match_explained("Ducati", "Superbike 1098 R Special", 2008) == ([1], 0, "reverse")


def test_reverse_matching_accepts_a_redundant_suffix_without_losing_the_model_number():
    matcher = MotorcycleMatcher([(1, "Kawasaki", "ZX-10R", 2020)])

    assert matcher.match_explained("Kawasaki", "Ninja ZX-10R 1000", 2020) == ([1], 0, "reverse")


def test_reverse_matching_does_not_drop_an_extra_distinctive_number():
    matcher = MotorcycleMatcher([(1, "Honda", "CB 500 Four", 2009)])

    assert matcher.match_explained("Honda", "CB 500 Four 750 Special", 2009) == ([], None, None)


def test_exact_year_precedes_neighboring_years():
    matcher = MotorcycleMatcher([
        (1, "Honda", "CBF 500", 2003),
        (2, "Honda", "CBF 500", 2004),
    ])

    assert matcher.match_explained("Honda", "CBF 500", 2004) == ([2], 0, "forward")


def test_numeric_conflict_in_current_year_does_not_hide_valid_previous_year():
    matcher = MotorcycleMatcher([
        (1, "Honda", "CBF 600 N", 2004),
        (2, "Honda", "CBF 500", 2003),
    ])

    assert matcher.match_explained("Honda", "CBF 500", 2004) == ([2], -1, "forward")


def test_custom_offsets_and_public_match_return_are_preserved():
    matcher = MotorcycleMatcher([(1, "Yamaha", "YZF-R1", 2018)])

    assert matcher.match("Yamaha", "YZF-R1 1000", 2020) == ([], None)
    assert matcher.match("Yamaha", "YZF-R1 1000", 2020, year_offsets=(0, -2)) == ([1], -2)


def test_empty_name_does_not_match_the_catalog():
    matcher = MotorcycleMatcher([(1, "Honda", "CBF 500", 2004)])

    assert matcher.match_explained("", "", 2004) == ([], None, None)
