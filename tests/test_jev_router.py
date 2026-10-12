from copy import deepcopy
from unittest.mock import Mock
import pytest
from bikefinder_rag.agent import jev_router,loop

def answers(operation='filter',scope='supported'):
    choices={'identity_binding':'none','operation':operation,'scope':scope,'equipment':'none','status':'standard',**{'field_'+key:'no' for key in jev_router.TOPICS},'n0_field':'price_eur','n0_op':'<','n1_field':'power_ch','n1_op':'>='}
    return {'answers':{k:{'choice':v,'confidence':.99} for k,v in choices.items()}}

@pytest.fixture
def router(monkeypatch):
    monkeypatch.setattr(jev_router,'entities',lambda conn,q:([],[]))
    monkeypatch.setattr(jev_router,'classify',lambda *args:(answers(),1,False))
    render=Mock(return_value='9 fiches avec preuves et sources')
    monkeypatch.setattr(jev_router,'render_list',render)
    return render

def test_user_price_power_question_never_calls_mistral(router,monkeypatch):
    monkeypatch.setenv('BIKEFINDER_CATALOG_FAST_PATH','1')
    monkeypatch.setenv('BIKEFINDER_JEV_ROUTER','1')
    monkeypatch.setattr(loop,'_run_agent_ollama',Mock(side_effect=AssertionError('Mistral invoked for structured filter')))
    answer,history=loop.run_agent(None,None,'Motos en dessous de 10000 eu et minimum 100 cv en 2020',[],provider='ollama')
    assert '9 fiches' in answer
    plan=router.call_args.args[1]
    assert plan['identity']['year']==2020
    assert plan['conditions']==[{'field':'price_eur','op':'<','value':10000},{'field':'power_ch','op':'>=','value':100}]
    assert history[-1]['_catalog_plan']==plan

def test_explicit_bound_cannot_be_changed_by_jev(router,monkeypatch):
    raw=answers();raw['answers']['n0_op']['choice']='>'
    monkeypatch.setattr(jev_router,'classify',lambda *args:(raw,1,False))
    result=jev_router.route_question(None,'Motos en dessous de 10000 eu et minimum 100 cv en 2020')
    assert result['route']=='clarification' and 'aucun critère' in result['answer']
    router.assert_not_called()

@pytest.mark.parametrize('kind',['used_price','market','a2','weight_type','unsupported'])
def test_unsupported_constraint_never_disappears(router,monkeypatch,kind):
    monkeypatch.setattr(jev_router,'classify',lambda *args:(answers(scope=kind),1,False))
    result=jev_router.route_question(None,'Motos en dessous de 10000 eu et minimum 100 cv en 2020')
    assert result['route']=='clarification'
    router.assert_not_called()

def test_followup_replaces_year_without_losing_other_filters(router,monkeypatch):
    previous={'identity':{'year':2020},'conditions':[{'field':'price_eur','op':'<','value':10000}], 'models':[],'fields':[],'equipment':None,'status':'standard'}
    original=deepcopy(previous)
    result=jev_router.route_question(None,'Et en 2021 ?',[{'role':'assistant','_catalog_plan':previous}])
    assert result['plan']['identity']['year']==2021 and result['plan']['conditions']==previous['conditions']
    assert previous==original

def test_failure_of_jev_is_not_an_automatic_expensive_fallback(router,monkeypatch):
    monkeypatch.setattr(jev_router,'classify',Mock(side_effect=RuntimeError('unavailable')))
    result=jev_router.route_question(None,'Motos en dessous de 10000 eu et minimum 100 cv en 2020')
    assert result['answer'] and result['route']=='router_error'
    router.assert_not_called()

def test_current_prices_are_never_silently_treated_as_catalog_prices(router):
    result=jev_router.route_question(None,'Donne le prix neuf actuel des motos de 2025.')
    assert result['route']=='clarification' and 'pas des prix neufs actuels' in result['answer']
    router.assert_not_called()

def test_model_number_does_not_override_explicit_year():
    numbers=jev_router.literals('Kawasaki Vulcan 2000 en 2000',[{'model':'Vulcan 2000'}])
    assert [n['role'] for n in numbers]==['model_number','year']

def test_kg_without_weight_type_never_filters_wet_and_dry(router):
    result=jev_router.route_question(None,'Motos en 2020 sous 200 kg')
    assert result['route']=='clarification' and 'poids à sec' in result['answer']
    router.assert_not_called()

def test_supported_followup_keeps_count_operation(router,monkeypatch):
    previous={'operation':'count','identity':{'year':2020},'conditions':[],'models':[],'fields':[],'equipment':None,'status':'standard'}
    monkeypatch.setattr(jev_router,'classify',lambda *args:(answers(operation='filter'),1,False))
    result=jev_router.route_question(None,'Et en 2021 ?',[{'role':'assistant','_catalog_plan':previous}])
    assert result['plan']['operation']=='count'

def test_ambiguous_classifier_cannot_widen_a_known_numeric_unit(router,monkeypatch):
    raw=answers();raw['answers']['n1_field']['choice']='price_eur'
    monkeypatch.setattr(jev_router,'classify',lambda *args:(raw,1,False))
    result=jev_router.route_question(None,'Motos en dessous de 10000 eu et minimum 100 cv en 2020')
    assert result['route']=='clarification';router.assert_not_called()

def test_money_literal_formats_and_other_units_remain_distinct():
    assert router_value('budget 10.000 euros')==10000
    assert router_value('budget 10kEUR')==10000
    assert router_value('puissance 100.5 ch')==100.5

def router_value(question):
    return jev_router.literals(question,[])[0]['value']

def test_negative_numeric_bound_never_becomes_a_positive_bound(router):
    result=jev_router.route_question(None,'Motos en 2020 sous -100 euros')
    assert result['route']=='clarification' and 'Aucun filtre' in result['answer']
    router.assert_not_called()

def test_fiscal_power_is_not_metric_engine_power(router):
    result=jev_router.route_question(None,'Motos de 2020 avec 10 CV fiscaux minimum')
    assert result['route']=='clarification' and 'fiscale' in result['answer']
    router.assert_not_called()

def test_capability_example_abs_never_becomes_an_unrequested_filter(router,monkeypatch):
    raw=answers();raw['answers']['equipment']['choice']='ABS';raw['answers']['status']['choice']='unknown'
    monkeypatch.setattr(jev_router,'classify',lambda *args:(raw,1,False))
    result=jev_router.route_question(None,'Motos en dessous de 10000 eu et minimum 100 cv en 2020')
    assert result['route']=='filter' and result['plan']['equipment'] is None

def test_partial_text_filter_is_not_ignored(router,monkeypatch):
    raw=answers();monkeypatch.setattr(jev_router,'classify',lambda *args:(raw,1,False))
    result=jev_router.route_question(None,'Motos en dessous de 10000 eu et minimum 100 cv en 2020, avec un cardan')
    assert result['plan']['secondary']=='cardan'

def test_status_union_does_not_drop_optional_fitment(router,monkeypatch):
    raw=answers();raw['answers']['equipment']['choice']='ABS';raw['answers']['status']['choice']='standard'
    monkeypatch.setattr(jev_router,'classify',lambda *args:(raw,1,False))
    result=jev_router.route_question(None,'Motos de 2020 avec ABS de série ou en option')
    assert result['plan']['status']=='present'

def test_extra_unbound_numeric_feature_is_not_silently_dropped(router,monkeypatch):
    raw=answers();raw['answers']['n0_field']['choice']='ignore';raw['answers']['n0_op']['choice']='ignore'
    monkeypatch.setattr(jev_router,'classify',lambda *args:(raw,1,False))
    result=jev_router.route_question(None,'Motos de 2020 avec 4 cylindres')
    assert result['route']=='clarification';router.assert_not_called()

def test_followup_without_context_never_widens_to_all_bikes(router):
    result=jev_router.route_question(None,'Et en 2021 ?',[])
    assert result['route']=='clarification' and 'silencieusement' in result['answer']
    router.assert_not_called()

def test_ambiguous_last_turn_does_not_resurrect_an_older_filter(router):
    history=[{'role':'assistant','_catalog_plan':{'identity':{'year':2020}}},{'role':'assistant','_catalog_plan':None}]
    assert jev_router.route_question(None,'Et en 2021 ?',history)['route']=='clarification'
    router.assert_not_called()

def test_visible_history_can_restore_a_followup_after_restart(router):
    history=[{'role':'user','content':'Motos en dessous de 10000 eu et minimum 100 cv en 2020'},{'role':'assistant','content':'9 fiches'}]
    result=jev_router.route_question(None,'Et en 2021 ?',history)
    assert result['plan']['identity']['year']==2021
    assert len(result['plan']['conditions'])==2


def test_plain_has_equipment_cannot_turn_into_unknown(router,monkeypatch):
    raw=answers();raw['answers']['equipment']['choice']='ABS';raw['answers']['status']['choice']='unknown'
    monkeypatch.setattr(jev_router,'classify',lambda *args:(raw,1,False))
    result=jev_router.route_question(None,"Quelles motos ont l'ABS en 2000 ? je veux voir les 11 fiches")
    assert result['plan']['equipment']=='ABS'
    assert result['plan']['status']=='standard'
