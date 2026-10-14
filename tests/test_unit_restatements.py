from copy import deepcopy
from decimal import Decimal

import pytest

from bikefinder_rag.catalog.unit_restatements import (
    CH_IN_KW,
    CUBIC_INCH_IN_CC,
    INCH_IN_MM,
    LBFT_IN_NM,
    POUND_IN_KG,
    STANDARD_GRAVITY,
    US_GALLON_IN_LITRES,
    requested_conversions,
)


def record(*rows):
    return {'spec_rows': [dict(zip(('section', 'label', 'value'), row)) for row in rows]}


def full_record():
    return record(
        ('Châssis', 'Réservoir', '14 litres'),
        ('Châssis', 'Hauteur de selle', '815 mm'),
        ('Châssis', 'Empattement', '1 400 mm'),
        ('Moteur', '', '9,50 mkg à 7 000 tr/min'),
        ('Châssis', 'Poids à sec', '180 kg'),
        ('Châssis', 'Poids tous pleins faits', '200 kg'),
        ('Moteur', '', '1 084 cc (Alésage * course: 73 x 64.8 mm)'),
    )


def test_exact_factors_are_derived_from_definitions_without_float_rounding():
    assert INCH_IN_MM == Decimal('25.4')
    assert POUND_IN_KG == Decimal('0.45359237')
    assert CUBIC_INCH_IN_CC == (INCH_IN_MM / 10) ** 3
    assert US_GALLON_IN_LITRES == 231 * CUBIC_INCH_IN_CC / 1000
    assert LBFT_IN_NM == POUND_IN_KG * STANDARD_GRAVITY * Decimal('0.3048')
    assert CH_IN_KW == Decimal('0.73549875')
    assert CH_IN_KW == 75 * STANDARD_GRAVITY / 1000


@pytest.mark.parametrize('question', [
    'Convertis la puissance en kW, avec le régime.',
    'Peux-tu convertir ses chevaux en kW ?',
    'Je demande la conversion de la puissance en kW.',
    'Peux-tu convertir la puissance en kilowatts ?',
])
def test_explicit_power_conversion_from_metric_ch_keeps_source_and_regime(question):
    item = record(('Moteur', '', '100 ch à 7 500 tr/min'))
    before = deepcopy(item)
    output = requested_conversions(item, question)
    assert '100 ch × 0,73549875 ≈ 73,55 kW' in output
    assert '100 ch à 7 500 tr/min' in output and '7500 tr/min' in output
    assert 'métriques' in output and 'nist.gov' in output
    assert item == before


def test_metric_cv_uses_same_exact_definition_as_ch():
    output = requested_conversions(record(('Moteur', 'Puissance', '75 CV à 9000 tr/min')),
                                   'Convertis la puissance en kW.')
    assert '55,16 kW' in output
    assert '75 CV à 9000 tr/min' in output
    assert '1 ch = 1 CV' in output


@pytest.mark.parametrize('question', [
    'Quelle est la puissance en kW ?',
    'Quelles motos de moins de 70 kW ?',
    'Convertis la puissance, en ch.',
    'Ne convertis pas la puissance en kW.',
    'Puissance en ch, sans conversion en kW.',
    'Convertis la puissance en ch, pas en kW.',
])
def test_kw_mentions_without_explicit_conversion_or_negated_request_do_nothing(question):
    assert requested_conversions(record(('Moteur', 'Puissance', '100 ch')), question) == ''


@pytest.mark.parametrize('constraint', ['moins de 70 kW', 'sous 70 kW', '< 70 kW', '70 kW maximum', 'entre 50 et 70 kW'])
def test_kw_filter_does_not_become_a_restatement_even_when_conversion_is_mentioned(constraint):
    question = f'Après conversion de puissance, quelles motos ont {constraint} ?'
    assert requested_conversions(record(('Moteur', 'Puissance', '100 ch')), question) == ''


@pytest.mark.parametrize('value', [
    '100 hp à 7500 tr/min', '100 HP', '100 PS', '100 chevaux', '100 ch / 110 ch',
    '100 ch (version bridée)', '100 ch (74 kW) à 7500 tr/min', 'nc', '0 ch',
])
def test_imperial_ambiguous_qualified_or_unknown_power_is_not_converted(value):
    output = requested_conversions(record(('Moteur', 'Puissance', value)), 'Convertis la puissance en kW.')
    assert 'aucune conversion' in output
    assert '73,55' not in output and '≈' not in output


def test_conflicting_power_regimes_do_not_become_one_kw_value():
    output = requested_conversions(record(
        ('Moteur', 'Puissance', '100 ch à 7500 tr/min'),
        ('Moteur', 'Puissance', '100 ch à 8500 tr/min'),
    ), 'Convertis la puissance en kW.')
    assert 'contradictoires' in output and 'aucune conversion' in output


def test_same_metric_power_in_ch_and_cv_is_not_a_conflict():
    output = requested_conversions(record(
        ('Moteur', 'Puissance', '100 ch à 7500 tr/min'),
        ('Moteur', 'Puissance', '100 CV à 7500 tr/min'),
    ), 'Conversion de la puissance en kW.')
    assert '73,55 kW' in output and 'aucune conversion' not in output


def test_power_qualified_by_a_variant_label_is_not_converted_globally():
    output = requested_conversions(record(('Moteur', 'Puissance (version A2)', '47,5 ch')),
                                   'Convertis la puissance en kW.')
    assert 'aucune conversion' in output and '≈' not in output


def test_only_explicit_requests_produce_restatements():
    assert requested_conversions(full_record(), 'Donne-moi la fiche technique.') == ''
    assert requested_conversions(full_record(), 'Quel est le réservoir en litres ?') == ''


@pytest.mark.parametrize('question', [
    'Réservoir en litres, pas en gallons US.',
    'Selle et empattement en millimètres, pas en pouces.',
    'Couple en mkg, pas en Nm ni en lb·ft.',
    'Poids en kilos, pas en livres.',
    'Cylindrée en cc, pas en cm³ ni en pouces cubes.',
])
def test_negated_target_units_are_not_requests(question):
    assert requested_conversions(full_record(), question) == ''


def test_us_qualifier_is_still_explicit_when_imperial_unit_is_excluded():
    output = requested_conversions(full_record(), 'Le réservoir en gallons US, pas impériaux.')
    assert '3,70 gallons américains (US)' in output


@pytest.mark.parametrize('excluded', [
    'pas des gallons impériaux',
    'pas les gallons impériaux',
    'pas en gallons impériaux',
    'ni des gallons britanniques',
    'sans gallons impériaux',
    'pas le gallon impérial',
])
def test_explicit_us_gallon_request_ignores_negated_other_gallon_family(excluded):
    item = record(('Châssis', 'Réservoir', '13,40 litres'))
    output = requested_conversions(item, f'Le réservoir en gallons américains, {excluded}.')
    assert '3,54 gallons américains (US)' in output
    assert '13,40 litres' in output
    assert 'précise' not in output


@pytest.mark.parametrize('question', [
    'Réservoir en gallons américains et en gallons impériaux ?',
    'Réservoir en gallons US ou britanniques ?',
    'Réservoir en gallons américains et gallon impérial ?',
])
def test_both_gallon_families_requested_still_need_clarification(question):
    item = record(('Châssis', 'Réservoir', '13,40 litres'))
    output = requested_conversions(item, question)
    assert 'précise' in output and 'aucune conversion' in output
    assert '3,54' not in output


@pytest.mark.parametrize('question', [
    'Le réservoir, ça donne combien en gallons US ?',
    'Convertis la capacité en gallons américains.',
    'Et en gallons des États-Unis ?',
])
def test_reservoir_in_explicit_us_gallons(question):
    output = requested_conversions(full_record(), question)
    assert '3,70 gallons américains (US)' in output
    assert '14 L / 3,785411784' in output
    assert '14 litres' in output and 'nist.gov' in output
    assert 'arrondis' in output and '2 décimales' in output


@pytest.mark.parametrize('question', [
    'Le réservoir en gallons ?', 'En gallons impériaux ?',
    'En gallons US ou britanniques ?',
])
def test_unqualified_or_imperial_gallons_are_not_silently_us(question):
    output = requested_conversions(full_record(), question)
    assert 'américains (US)' in output and 'aucune conversion' in output
    assert '3,70' not in output


def test_requested_seat_and_wheelbase_have_separate_inch_formulas():
    output = requested_conversions(full_record(), 'La selle et l’empattement en pouces ?')
    assert '815 mm / 25,4 ≈ 32,09 pouces' in output
    assert '1400 mm / 25,4 ≈ 55,12 pouces' in output
    assert 'Hauteur de selle' in output and 'Empattement' in output
    assert 'cylindrée' not in output.lower()


def test_seat_adjustment_range_keeps_both_endpoints():
    item = record(('Châssis', '', 'Hauteur de selle réglable entre 825 mm et 845 mm'))
    output = requested_conversions(item, 'La hauteur de selle réglable en pouces ?')
    assert '825–845 mm' in output and '32,48–33,27 pouces' in output
    assert 'plage réglable conservée' in output
    assert '825 mm et 845 mm' in output


@pytest.mark.parametrize('value', ['830 mm (selle basse en option)', '825 / 845 mm selon version', 'nc'])
def test_seat_qualifications_do_not_become_one_point(value):
    output = requested_conversions(record(('Châssis', 'Hauteur de selle', value)), 'La selle en pouces ?')
    assert 'aucune conversion' in output
    assert '32,' not in output


def test_conflicting_wheelbases_cannot_be_converted_as_one_value():
    output = requested_conversions(record(
        ('Châssis', 'Empattement', '1 400 mm'),
        ('Châssis', 'Empattement', '1 420 mm'),
    ), 'Empattement en pouces ?')
    assert 'contradictoires' in output and 'aucune conversion' in output


def test_mkg_to_nm_and_lbft_keeps_original_regime_and_units():
    output = requested_conversions(full_record(), 'Le couple en N·m et lb·ft, avec le régime ?')
    assert '9,5 mkg × 9,80665 ≈ 93,2 N·m' in output
    assert '68,7 lb·ft' in output and '1,3558179483314004' in output
    assert '9,50 mkg à 7 000 tr/min' in output and 'kgf·m' in output
    assert '7 000 tr/min' in output
    assert 'Poids' not in output


@pytest.mark.parametrize('unit', ['Nm', 'N·m', 'N.m', 'N m'])
def test_normalized_nm_source_and_lbft(unit):
    output = requested_conversions(record(('Moteur', 'Couple', f'100 {unit} à 6000 tr/min')),
                                   'Convertis le couple en Nm et lb-ft.')
    assert '100 N·m' in output and '73,8 lb·ft' in output
    assert f'100 {unit} à 6000 tr/min' in output
    assert '× 9,80665' not in output


def test_same_torque_at_different_regimes_is_not_merged():
    output = requested_conversions(record(
        ('Moteur', 'Couple', '100 Nm à 6000 tr/min'),
        ('Moteur', 'Couple', '100 Nm à 6500 tr/min'),
    ), 'Couple en lb·ft ?')
    assert 'contradictoires' in output and 'aucune conversion' in output


def test_parenthesized_nm_is_a_source_value_and_preserves_both_original_units():
    item = record(('Moteur', '', '10,50 mkg (103 Nm) à 10 500 tr/min'))
    output = requested_conversions(item, 'Couple en N·m et lb·ft ?')
    assert '103 N·m (unité source normalisée)' in output
    assert '76,0 lb·ft' in output
    assert '10,50 mkg (103 Nm) à 10 500 tr/min' in output
    assert '× 9,80665' not in output


def test_incompatible_mkg_and_parenthesized_nm_are_not_one_derived_value():
    item = record(('Moteur', '', '10,90 mkg (107,10 Nm) à 10 500 tr/min'))
    output = requested_conversions(item, 'Couple en N·m et lb·ft ?')
    assert 'aucune conversion' in output and '≈' not in output
    assert '10,90 mkg (107,10 Nm)' in output


@pytest.mark.parametrize('value', ['10 mkg (version bridée)', '100 Nm / 110 Nm selon version', 'nc'])
def test_torque_variant_or_unknown_has_no_derived_global_value(value):
    output = requested_conversions(record(('Moteur', 'Couple', value)), 'Couple en Nm et lb·ft ?')
    assert 'aucune conversion' in output
    assert '≈' not in output


def test_dry_and_wet_weight_in_pounds_keep_separate_definitions():
    output = requested_conversions(full_record(), 'Convertis les deux types de poids en livres.')
    assert 'Poids à sec' in output and 'Poids tous pleins / en ordre de marche' in output
    assert '180 kg / 0,45359237 ≈ 396,8 livres (lb)' in output
    assert '200 kg / 0,45359237 ≈ 440,9 livres (lb)' in output
    assert '1 livre avoirdupois' in output


def test_explicit_dry_weight_does_not_convert_wet_weight():
    output = requested_conversions(full_record(), 'Le poids à sec en lb ?')
    assert '396,8' in output and '440,9' not in output


def test_source_weight_without_definition_is_not_assumed_dry_or_wet():
    output = requested_conversions(record(('Châssis', 'Poids', '200 kg')), 'Le poids en livres ?')
    assert 'type sec / plein' in output and 'aucune conversion' in output
    assert '440,9' not in output


def test_weight_label_variant_is_not_a_global_value():
    output = requested_conversions(record(('Châssis', 'Poids tous pleins faits (DCT)', '240 kg')),
                                   'Le poids plein en livres ?')
    assert 'aucune conversion' in output and '529,' not in output


def test_cc_is_cm3_and_cubic_inches_preserve_bore_information():
    output = requested_conversions(full_record(), 'La cylindrée en cm³ et en pouces cubes ?')
    assert '1084 cc = 1084 cm³' in output
    assert '1084 cc / 16,387064 ≈ 66,15 pouces cubes' in output
    assert 'Alésage * course: 73 x 64.8 mm' in output
    assert 'Hauteur de selle' not in output


def test_cubic_inches_do_not_trigger_linear_inch_conversion():
    output = requested_conversions(full_record(), 'Et en cubic inches ?')
    assert '66,15 pouces cubes' in output
    assert '55,12' not in output and '32,09' not in output


def test_displacement_variant_suffix_cannot_be_silently_dropped():
    output = requested_conversions(record(('Moteur', 'Cylindrée', '1084 cc (version Adventure)')),
                                   'Cylindrée en pouces cubes ?')
    assert 'aucune conversion' in output
    assert '66,15' not in output


def test_identical_source_rows_are_one_conversion_with_originals_untouched():
    item = full_record()
    item['spec_rows'].append(deepcopy(item['spec_rows'][0]))
    before = deepcopy(item)
    output = requested_conversions(item, 'Réservoir en gallons US ?')
    assert output.count('3,70 gallons américains (US)') == 1
    assert item == before


def test_requested_missing_values_are_visible_without_imputation():
    output = requested_conversions(record(), 'Selle et empattement en pouces, couple en lb·ft, réservoir en gallons US ?')
    assert output.count('non documentée') == 4
    assert output.count('aucune conversion') == 4
    assert '≈' not in output


@pytest.mark.parametrize('value', ['0 litres', '-3 litres', '14 litres avec réserve de 2 litres', '14 litres / 16 litres'])
def test_invalid_or_qualified_capacity_is_not_stripped_to_a_number(value):
    output = requested_conversions(record(('Châssis', 'Réservoir', value)), 'Réservoir en gallons US ?')
    assert 'aucune conversion' in output and '≈' not in output
