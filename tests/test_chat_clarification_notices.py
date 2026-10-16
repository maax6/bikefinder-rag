"""Regression checks for unresolved model families and redundant notices."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from bikefinder_rag.agent import rag_router, rag_synthesis


@pytest.fixture
def family_catalog(monkeypatch):
    legacy = rag_router.legacy
    models = ['XJ6 600 Naked', 'XJ6 600 Diversion', 'XJ6 600 Diversion F']
    groups = [{'brand': 'Yamaha', 'model': model, 'years': {2011},
               'aliases': legacy.aliases('Yamaha', model),
               'primary_aliases': legacy.aliases('Yamaha', model, False)} for model in models]
    monkeypatch.setattr(legacy, '_identities', {'groups': groups, 'brands': ['Yamaha']})
    monkeypatch.setenv('BIKEFINDER_JEV_RAG', '1')
    monkeypatch.setenv('BIKEFINDER_CATALOG_RESEARCH', '0')
    monkeypatch.setenv('BIKEFINDER_CATALOG_EXPERIMENT', '0')
    monkeypatch.setattr(rag_router, 'classify_sources', Mock(side_effect=AssertionError('Ambiguous family must clarify first')))
    return models


def test_xj6_a2_clarifies_real_variants_and_keeps_supplied_year(family_catalog):
    result = rag_router.route_question(object(), 'Quelle type de bridage pour un XJ6 A2 2011')
    assert result['route'] == 'clarification'
    assert all(model in result['answer'] for model in family_catalog)
    assert '2011' in result['answer']
    assert 'Précise un modèle et son millésime' not in result['answer']
    assert not result['evidence']['retrieval_executed']
    assert result['plan']['identity']['year'] == 2011


@pytest.mark.parametrize('reply,model', [('La Naked', 'XJ6 600 Naked'),
    ('Diversion', 'XJ6 600 Diversion'), ('Diversion F', 'XJ6 600 Diversion F')])
def test_variant_reply_retains_request_and_year(monkeypatch, family_catalog, reply, model):
    first = rag_router.route_question(object(), 'Quel bridage pour un XJ6 A2 2011 ?')
    raw = {'answers': {'identity_binding': {'choice': 'recognized'}, 'intent': {'choice': 'legal_proof'},
        **{'field_' + f: {'choice': 'no', 'confidence': 1} for f in rag_router.FIELDS}}}
    monkeypatch.setattr(rag_router, 'classify_sources', lambda *args: (raw, 0))
    source = Mock(return_value={'answer': 'Mentions de la fiche', 'evidence': {'sources': [], 'missing': [], 'retrievals': []}})
    monkeypatch.setattr(rag_router, 'answer_from_sources', source)
    monkeypatch.setattr(rag_router, 'compose', lambda q, result: result)
    rag_router.route_question(object(), reply, [{'role': 'assistant', '_catalog_plan': first['plan']}])
    question, plan = source.call_args.args[1:3]
    assert 'bridage' in question and '2011' in question
    assert plan['models'] == [{'brand': 'Yamaha', 'model': model, 'year': 2011}]
    assert plan['legal_proof_required']


def test_a2_is_not_an_unknown_edition_but_nebula_still_is():
    model = [{'brand': 'Yamaha', 'model': 'XJ6 600 Naked'}]
    assert not rag_router.unresolved_mentions('XJ6 600 Naked A2 2011', model)
    assert rag_router.unresolved_mentions('XJ6 600 Naked Nebula A2 2011', model)


def test_unknown_reply_does_not_pick_a_variant(family_catalog):
    first = rag_router.route_question(object(), 'Quel bridage pour un XJ6 A2 2011 ?')
    assert rag_router.pending_variant('La plus jolie', first['plan']) is None


@pytest.fixture
def uncertain_answer(monkeypatch):
    monkeypatch.setenv('BIKEFINDER_RAG_SYNTHESIS', '1')
    monkeypatch.setattr(rag_synthesis, 'generate', Mock(return_value=(
        {'claims': [{'text': 'La fiche indique une puissance de 48 ch.', 'sources': ['P1']}]}, {})))
    return {'answer': 'Puissance : 48 ch. Source.', 'plan': {}, 'route': 'rag_partial',
            'evidence': {'retrieval_executed': True, 'sources': [
                {'object_id': 'bike', 'brand': 'Honda', 'model': 'Example', 'year': 2022,
                 'source_url': 'https://source.test/bike', 'source_sha256': 'hash',
                 'coverage': {'power_ch': {'requested_facts_status': 'unverified',
                                          'source_passages_available': True}},
                 'passages': [{'id': 'bike:power', 'original_text': 'Puissance : 48 ch.', 'section': 'Moteur'}]}],
                'missing': [{'kind': 'field', 'object_id': 'bike', 'field': 'power_ch',
                             'message': "La fiche fournit ces mentions, mais leur couverture du détail demandé n'a pas pu être vérifiée"}]}}


def test_verified_final_answer_does_not_repeat_obsolete_source_uncertainty(monkeypatch, uncertain_answer):
    monkeypatch.setattr(rag_synthesis, 'check_claims', lambda *args: {
        'accepted': True, 'coverage_verified': True, 'jev_calls': 0})
    before = deepcopy(uncertain_answer['evidence'])
    result = rag_synthesis.compose('Quelle puissance ?', uncertain_answer)
    assert '48 ch' in result['answer']
    assert 'non vérifi' not in result['answer'] and 'pas pu être vérifiée' not in result['answer']
    assert 'Preuves manquantes' not in result['answer']
    assert result['evidence'] == before  # Keep uncertainty in the audit trace.


def test_uncertain_coverage_has_one_notice_without_claiming_missing_data(monkeypatch, uncertain_answer):
    monkeypatch.setattr(rag_synthesis, 'check_claims', lambda *args: {
        'accepted': True, 'coverage_verified': False, 'jev_calls': 0})
    result = rag_synthesis.compose('Quelle puissance ?', uncertain_answer)
    assert 'Preuves manquantes' not in result['answer']
    assert result['answer'].count('vérifi') == 1
    assert '48 ch' in result['answer']


def test_real_missing_fact_survives_verified_prose(monkeypatch, uncertain_answer):
    uncertain_answer['evidence']['missing'].append({'kind': 'field', 'object_id': 'bike',
        'field': 'weight_dry_kg', 'message': 'Poids sec non documenté dans cette fiche'})
    monkeypatch.setattr(rag_synthesis, 'check_claims', lambda *args: {
        'accepted': True, 'coverage_verified': True, 'jev_calls': 0})
    result = rag_synthesis.compose('Puissance et poids sec ?', uncertain_answer)
    assert 'Poids sec non documenté' in result['answer']


def test_source_fallback_does_not_repeat_rendered_gap(monkeypatch, uncertain_answer):
    message = 'Poids sec non documenté dans cette fiche'
    uncertain_answer['answer'] += '\n' + message
    uncertain_answer['evidence']['missing'].append({'kind': 'field', 'object_id': 'bike',
        'field': 'weight_dry_kg', 'message': message})
    monkeypatch.setattr(rag_synthesis, 'generate', Mock(side_effect=TimeoutError))
    result = rag_synthesis.compose('Puissance et poids sec ?', uncertain_answer)
    assert result['answer'].count(message) == 1


def test_all_claims_verified_does_not_call_prose_unverified(monkeypatch, uncertain_answer):
    monkeypatch.setattr(rag_synthesis, 'check_claims', lambda *args: {
        'accepted': False, 'verified_claim_indices': [0], 'coverage_verified': False, 'jev_calls': 0})
    result = rag_synthesis.compose('Quelle puissance ?', uncertain_answer)
    assert '48 ch' in result['answer']
    assert 'une partie de la proposition' not in result['answer']
    assert 'Complément' in result['answer']


def test_table_gap_is_not_repeated_but_other_identity_gap_remains(monkeypatch, uncertain_answer):
    uncertain_answer['answer'] = '| Caractéristique | Honda Example (2022) |\n|---|---|\n| Poids à sec (kg) | Non documenté dans cette fiche |'
    uncertain_answer['evidence']['missing'] = [
        {'kind': 'field', 'object_id': 'bike', 'field': 'weight_dry_kg',
         'message': 'Non documenté dans les passages de cette fiche Couverture non établie de l’ensemble des détails demandés : « poids sec ».'},
        {'kind': 'identity', 'message': 'Fiche 1990 manquante'}]
    monkeypatch.setattr(rag_synthesis, 'generate', Mock(side_effect=TimeoutError))
    result = rag_synthesis.compose('Poids sec ?', uncertain_answer)
    assert result['answer'].count('Non documenté') == 1
    assert 'Fiche 1990 manquante' in result['answer']


def test_table_unknown_on_other_bike_cannot_hide_a_missing_fact(uncertain_answer):
    uncertain_answer['answer'] = '| Caractéristique | Honda Example (2021) | Honda Example (2022) |\n|---|---|---|\n| Poids à sec (kg) | Non documenté dans cette fiche | 200 kg |'
    uncertain_answer['evidence']['missing'] = [{'kind': 'field', 'object_id': 'bike',
        'field': 'weight_dry_kg', 'message': 'Non documenté dans les passages de cette fiche'}]
    notice = rag_synthesis.missing_notices(uncertain_answer, already_rendered=uncertain_answer['answer'])
    assert 'Honda Example (2022)' in notice


@pytest.mark.parametrize('heading,body,duplicate', [
    ('Honda Example (2022)', '- **Mention A2 :** non retrouvée dans cette fiche.', True),
    ('Honda Example (2021)', '- **Mention A2 :** non retrouvée dans cette fiche.', False),
    ('Honda Example (2022)', '- **Mention A2 :** documentée.', False),
    ('', '- **Mention A2 :** non retrouvée dans cette fiche.', False),
])
def test_a2_gap_deduplicates_only_in_same_source_section(uncertain_answer, heading, body, duplicate):
    uncertain_answer['plan']['a2_context'] = True
    uncertain_answer['evidence']['missing'] = [{'kind': 'field', 'object_id': 'bike',
        'field': 'a2_mention', 'message': 'Mention A2 non retrouvée'}]
    answer = f'### {heading}\n\n{body}\n\n### Honda Other (2023)\nAutre fiche.'
    notice = rag_synthesis.missing_notices(uncertain_answer, already_rendered=answer)
    assert ('Informations non documentées' not in notice) == duplicate
    assert 'Limite des preuves' in notice


@pytest.mark.parametrize('question,show_dry_gap', [
    ('Donne le poids tous pleins faits.', False),
    ('Et le poids sec ?', True),
    ('Donne le poids sec et tous pleins faits.', True),
    ('Quel poids ?', True)])
def test_unasked_weight_category_does_not_add_a_warning(uncertain_answer, question, show_dry_gap):
    uncertain_answer['plan']['source_question'] = question
    uncertain_answer['evidence']['missing'] = [{'kind': 'field', 'object_id': 'bike',
        'field': 'weight_dry_kg', 'message': 'Poids sec non documenté'}]
    assert ('Poids sec non documenté' in rag_synthesis.missing_notices(uncertain_answer)) == show_dry_gap
