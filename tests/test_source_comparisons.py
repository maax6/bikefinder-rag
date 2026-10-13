import pytest

from bikefinder_rag.catalog.comparisons import comparison_calculations, is_arithmetic_question


def fiche(model, power='100 ch à 8 000 tr/min', dry='200 kg', wet='220 kg', displacement='1000 cc', seat='800 mm'):
    rows = []
    for section, label, value in [
        ('Moteur', 'Puissance', power), ('Moteur', 'Cylindrée', displacement),
        ('Dimensions', 'Hauteur de selle', seat), ('Dimensions', 'Poids à sec', dry),
        ('Dimensions', 'Poids tous pleins faits', wet),
    ]:
        if value is not None:
            rows.append({'section': section, 'label': label, 'value': value})
    return {'brand': 'Fixture', 'model': model, 'year': 2024,
            'source_url': f'https://example.test/{model}', 'record': {'spec_rows': rows}}


@pytest.mark.parametrize('question', [
    'Quel écart de puissance entre ces deux modèles ?',
    'De combien diffèrent les cylindrées ?',
    'Quelle différence de hauteur de selle ?',
    'Lequel est plus puissant ?',
    'Lequel est plus léger à sec ?',
    'Calcule le rapport puissance/poids tous pleins.',
    'Quel ratio ch/kg à sec ?',
])
def test_explicit_source_arithmetic_is_recognized(question):
    assert is_arithmetic_question(question)


@pytest.mark.parametrize('question', [
    'Compare leurs puissances et poids à sec côte à côte.',
    'Quels chiffres sont documentés dans les deux fiches ?',
    'Quelles conséquences de la différence de puissance ?',
    'Lequel est plus confortable ?',
    'Quelle différence de fiabilité ?',
    'Quelle différence de sensations avec ces poids à sec ?',
    'Quelle différence de rapport de transmission ?',
])
def test_source_table_or_consequences_do_not_trigger_arithmetic(question):
    assert not is_arithmetic_question(question)
    assert comparison_calculations(question, []) == ''


def test_explicit_gaps_use_only_requested_same_unit_source_fields():
    records = [fiche('A'), fiche('B', power='80 ch', displacement='650 cc', seat='790 mm')]
    output = comparison_calculations('Quel écart de puissance, cylindrée et hauteur de selle ?', records)
    assert '20 ch' in output and '350 cc' in output and '10 mm' in output
    assert 'Poids à sec' not in output
    assert 'https://example.test/A' in output and 'https://example.test/B' in output


def test_decimal_gap_and_equal_power_are_not_invented_or_rounded():
    records = [fiche('A', power='10,1 ch'), fiche('B', power='10,3 ch')]
    assert '0,2 ch' in comparison_calculations('Quel écart de puissance ?', records)
    assert 'Égalité' in comparison_calculations('Lequel est plus puissant ?', [records[0], records[0]])


def test_rank_and_gap_use_explicit_weight_type():
    records = [fiche('A', dry='180 kg', wet='230 kg'), fiche('B', dry='190 kg', wet='220 kg')]
    dry = comparison_calculations('Lequel est plus léger à sec ?', records)
    wet = comparison_calculations('Lequel est plus léger tous pleins ?', records)
    assert 'Fixture A (2024) : 180 kg' in dry
    assert 'Fixture B (2024) : 220 kg' in wet
    assert '10 kg' in comparison_calculations('Quel écart de poids à sec ?', records)


@pytest.mark.parametrize('question', [
    'Lequel est plus léger ?', 'Quel écart de poids ?',
    'Quel rapport puissance/poids ?', 'Quel rapport ch/kg à sec et tous pleins ?',
])
def test_weight_type_is_mandatory_and_cannot_be_mixed(question):
    output = comparison_calculations(question, [fiche('A'), fiche('B')])
    assert 'Précise un seul type commun' in output
    assert '0,5 ch/kg' not in output


def test_ratio_displays_formula_source_qualification_and_rounding():
    records = [fiche('A'), fiche('B', power='100 ch', dry='300 kg')]
    output = comparison_calculations('Quel rapport ch/kg à sec ?', records)
    assert '100 ch / 200 kg = 0,5 ch/kg' in output
    assert '100 ch / 300 kg ≈ 0,333 ch/kg' in output
    assert '100 ch à 8 000 tr/min' in output
    assert 'Dimensions — Poids à sec : 200 kg' in output
    assert 'Calcul dérivé des valeurs de catalogue' in output
    assert 'rapport mesuré non établi' in output


def test_missing_or_non_ch_power_never_uses_another_unit_or_sheet():
    output = comparison_calculations('Quel écart de puissance ?', [fiche('A'), fiche('B', power='70 kW')])
    assert 'Valeur numérique univoque non documentée : Fixture B (2024)' in output
    assert '30 ch' not in output
    ratio = comparison_calculations('Quel rapport puissance/poids à sec ?', [fiche('A'), fiche('B', dry=None)])
    assert 'Non calculable : valeur numérique univoque non documentée pour poids à sec' in ratio


def test_conflicting_source_values_remain_unknown():
    record = fiche('A')
    record['record']['spec_rows'].append({'section': 'Moteur', 'label': 'Puissance', 'value': '110 ch'})
    output = comparison_calculations('Lequel est plus puissant ?', [record, fiche('B')])
    assert 'Valeur numérique univoque non documentée : Fixture A (2024)' in output


def test_zero_weight_does_not_create_a_ratio():
    output = comparison_calculations('Quel rapport ch/kg à sec ?', [fiche('A', dry='0 kg'), fiche('B')])
    assert 'poids documenté doit être strictement positif' in output


def test_requested_conversion_is_rejected():
    output = comparison_calculations('Quel écart de puissance en kW ?', [fiche('A'), fiche('B')])
    assert 'Aucune conversion implicite' in output


def test_requested_power_gap_and_ratio_are_both_preserved():
    output = comparison_calculations('Quel écart de puissance et quel rapport ch/kg à sec ?',
                                     [fiche('A'), fiche('B', power='80 ch')])
    assert 'Écart — Puissance' in output and '20 ch' in output
    assert '100 ch / 200 kg = 0,5 ch/kg' in output
    assert 'Écart — Poids' not in output


@pytest.mark.parametrize('question', ['Quel écart de rapport puissance/poids à sec ?', 'Quel écart ch/kg à sec ?'])
def test_explicit_ratio_gap_does_not_add_unrequested_component_gaps(question):
    output = comparison_calculations(question,
                                     [fiche('A'), fiche('B', power='80 ch')])
    assert 'Écart des rapports puissance/poids à sec' in output
    assert '0,1 ch/kg' in output
    assert 'Écart — Puissance' not in output and 'Écart — Poids' not in output


@pytest.mark.parametrize('records', [[], [fiche('A')], [fiche('A'), fiche('B'), fiche('C')]])
def test_exactly_two_identified_records_are_required(records):
    assert 'exactement deux fiches' in comparison_calculations('Quel écart de puissance ?', records)


def adjustable_seat(model, text):
    record = fiche(model, seat=None)
    record['record']['spec_rows'].append({'section': 'Dimensions', 'label': '', 'value': text})
    return record


def test_lowest_seat_recognizes_explicit_ranking_and_overlapping_range():
    question = 'Laquelle est la plus basse de selle ?'
    assert is_arithmetic_question(question)
    records = [adjustable_seat('Himalayan', 'Hauteur de selle réglable entre 825 mm et 845 mm'),
               fiche('NX500', seat='830 mm')]
    output = comparison_calculations(question, records)
    assert '825–845 mm' in output and '830 mm' in output
    assert 'le classement dépend du réglage' in output
    assert 'Aucun vainqueur unique' in output
    assert 'https://example.test/Himalayan' in output and 'https://example.test/NX500' in output


def test_disjoint_seat_range_can_be_ranked_using_its_full_bounds():
    records = [adjustable_seat('A', 'Hauteur de selle réglable entre780mm et800mm'), fiche('B', seat='830 mm')]
    output = comparison_calculations('Laquelle est la plus basse de selle ?', records)
    assert 'Fixture A (2024) a la selle plus basse sur toute la plage documentée' in output
    assert '780–800 mm' in output and '830 mm' in output


def test_equal_point_seats_are_an_equality_and_touching_ranges_are_not_a_unique_winner():
    assert 'Égalité des hauteurs de selle' in comparison_calculations(
        'Laquelle est la plus basse de selle ?', [fiche('A'), fiche('B')])
    records = [adjustable_seat('A', 'Hauteur de selle réglable entre 780 mm et 800 mm'), fiche('B', seat='800 mm')]
    assert 'Aucun vainqueur unique' in comparison_calculations('Laquelle est la plus basse de selle ?', records)


@pytest.mark.parametrize('seat', [None, '83 cm'])
def test_missing_or_other_unit_seat_cannot_be_ranked(seat):
    output = comparison_calculations('Laquelle est la plus basse de selle ?', [fiche('A'), fiche('B', seat=seat)])
    assert 'Hauteur de selle en mm univoque non documentée : Fixture B (2024)' in output
    assert 'Aucune valeur ni conversion substituée' in output


def test_higher_seat_ranking_uses_the_opposite_disjoint_interval():
    records = [adjustable_seat('A', 'Hauteur de selle réglable entre 780 mm et 800 mm'), fiche('B', seat='830 mm')]
    assert 'Fixture B (2024) a la selle plus haute' in comparison_calculations('Laquelle a la selle la plus haute ?', records)
