"""Public-wording regressions: exercise the router, not an LLM quality simulation."""
from unittest.mock import Mock
import pytest
from bikefinder_rag.agent import rag_router

@pytest.fixture
def catalog(monkeypatch):
    legacy = rag_router.legacy
    names = [('Yamaha', 'XJ6 600 Naked', {2011, 2012}), ('Yamaha', 'XJ6 600 Diversion', {2011, 2012}),
             ('Yamaha', 'XJ6 600 Diversion F', {2011, 2012}), ('Honda', 'CB 500 F', {2018, 2019}),
             ('Can-Am', 'Spyder RT', {2019}), ('Moto-Guzzi', 'V 85 TT', {2020}),
             ('Moto-Guzzi', 'V 85 TT Travel', {2020}), ('Moto-Guzzi', 'V 85 Strada', {2024})]
    groups = [dict(brand=b,model=m,years=y,aliases=legacy.aliases(b,m),primary_aliases=legacy.aliases(b,m,False)) for b,m,y in names]
    monkeypatch.setattr(legacy,'_identities',{'groups':groups,'brands':sorted({b for b,_,_ in names})})
    monkeypatch.setenv('BIKEFINDER_JEV_RAG','1');monkeypatch.setenv('BIKEFINDER_CATALOG_RESEARCH','0');monkeypatch.setenv('BIKEFINDER_CATALOG_EXPERIMENT','0')
    # Reproduce the pre-fix classifier-driven generic clarification. The tests
    # require a useful boundary/candidate response BEFORE that unsafe fallback.
    old = Mock(return_value={'answer':'Précise les modèles et un millésime explicite.', 'route':'clarification','plan':None,'jev_calls':0})
    monkeypatch.setattr(legacy,'route_question',old)
    return old

def test_english_can_is_not_the_brand_can_am(catalog):
    models, brands = rag_router.legacy.entities(None, 'Can I check that the CB500F 2019 has ABS as standard? I’m based in the UK.')
    assert models == [{'brand':'Honda','model':'CB 500 F'}]
    assert 'Can-Am' not in brands


def test_restriction_family_without_a2_keeps_year_and_variants(catalog):
    result=rag_router.route_question(None,'xj6 de 2012 bridable à 35 ou 47 ch?')
    assert all(n in result['answer'] for n in ['Naked','Diversion','2012'])
    assert result['plan']['variant_pending']
    catalog.assert_not_called()

@pytest.mark.parametrize('question,required',[
    ('65 000 km pour une CB500F de 2018, est-ce convenable ?', ['entretien','inspection']),
    ('How does the V85 handle 80 on the highway? Vibration wise.', ['vibration','V 85','unité']),
    ('Vos conseils de 1ere moto pour les petits gabarits ? (1m61)', ['hauteur de selle','poids','budget']),
    ('Plusieurs renfoncements sur mon réservoir CB500 PC39 : carrossier spécialisé ? Combien à refaire ?', ['devis','réparation']),
    ('Le bridage change-t-il le poids, la consommation ou le comportement, ou juste la puissance ?', ['type de bridage','millésime']),
])
def test_scope_response_is_specific_and_does_not_invent_facts(catalog,question,required):
    result=rag_router.route_question(None,question)
    assert all(term.lower() in result['answer'].lower() for term in required)
    assert not result.get('evidence',{}).get('retrieval_executed')
    catalog.assert_not_called()


def test_full_can_am_brand_is_still_recognized(catalog):
    models, brands = rag_router.legacy.entities(None, 'Can-Am Spyder RT 2019')
    assert models == [{'brand':'Can-Am','model':'Spyder RT'}] and brands==['Can-Am']


@pytest.mark.parametrize('question', [
    'Donne le prix moyen de Yamaha en 2020.',
    'CB500F 2018 : quelle autonomie en km ?',
    'Je mesure 1m61, donne seulement la hauteur de selle de la CB500F 2019.',
    'Liste les motos avec hauteur de selle sous 800 mm.',
    'Une selle confort est-elle documentée sur la fiche ?',
    'Donne la puissance de la XJ6 Naked 2011.',
])
def test_scope_guards_do_not_steal_catalogue_facts(question):
    from bikefinder_rag.agent.catalog_scope import scope_response
    assert scope_response(question) is None


@pytest.mark.parametrize('question,topic', [
    ('Une ER6 qui a 72000 kilomètres est-elle trop kilométrée pour acheter ?', 'condition'),
    ('Quel devis pour réparer les bosses du réservoir de ma Triumph ?', 'repair'),
    ('Je mesure 1m58, quelle première moto choisir ?', 'rider_fit'),
    ('Quels effets du bridage sur la consommation de cette Ducati ?', 'restriction_effects'),
])
def test_scope_detection_is_not_tied_to_benchmark_models(question,topic):
    from bikefinder_rag.agent.catalog_scope import scope_response
    assert scope_response(question)[0] == topic
