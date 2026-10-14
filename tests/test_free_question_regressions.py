from copy import deepcopy
from unittest.mock import Mock
import pytest
from bikefinder_rag.agent import jev_router as router

def decisions(operation='filter', equipment='none', status='standard'):
    return {'answers':{k:{'choice':v,'confidence':.99} for k,v in {
        'identity_binding':'none','operation':operation,'scope':'supported','equipment':equipment,'status':status,
        **{'field_'+key:'no' for key in router.TOPICS},'n0_field':'price_eur','n0_op':'>='}.items()}}

@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(router,'entities',lambda conn,q:([],[]))
    monkeypatch.setattr(router,'classify',lambda *args:(decisions(),1,False))
    render=Mock(return_value='source facts');monkeypatch.setattr(router,'render_list',render)
    return render

def test_negative_equipment_cannot_become_standard(stub,monkeypatch):
    raw=decisions(equipment='ABS');monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    r=router.route_question(None,"Je veux juste les bécanes de 2010 dont on sait qu'elles n'ont pas d'ABS, pas celles où t'as aucune info.")
    assert r['plan']['status']=='explicitly_absent'

def test_followup_adds_lower_bound_without_erasing_upper(stub):
    p={'identity':{'year':2024},'conditions':[{'field':'price_eur','op':'<','value':9000}], 'models':[],'fields':[],'equipment':None,'status':'standard','operation':'filter'}
    r=router.route_question(None,'Et au moins 4 000 €',[{'role':'assistant','_catalog_plan':deepcopy(p)}])
    assert r['plan']['conditions']==p['conditions']+[{'field':'price_eur','op':'>=','value':4000}]

def test_invalid_partial_plan_is_not_reusable(stub,monkeypatch):
    raw=decisions();raw['answers'].update(n1_field={'choice':'price_eur'},n1_op={'choice':'>='},n2_field={'choice':'ignore'},n2_op={'choice':'ignore'})
    monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    r=router.route_question(None,'Motos de 2024 à minimum 4000 euros et plus de 90 ch')
    assert r['route']=='clarification' and r['plan'] is None

def test_model_numbers_and_user_height_are_not_filter_thresholds():
    ns=router.literals('Quelle hauteur de selle sur la Honda CB 500 F 2020 ? Je fais 1m62, je veux juste le chiffre documenté.',[{'brand':'Honda','model':'CB 500 F'}])
    assert next(n for n in ns if n['literal']=='500')['role']=='model_number'
    assert next(n for n in ns if n['literal']=='2020')['role']=='year'
    assert next(n for n in ns if n['literal']=='1')['role']=='user_context'

def test_colloquial_units_are_literal_supported_fields():
    ns=router.literals("J'ai 9500 balles à mettre, je veux pas moins de 110 bourrins. Regarde ce qui se faisait en 2020, sur les tarifs de sortie.",[])
    assert ns[0]['role']=='price_eur' and ns[1]['role']=='power_ch'

def catalog(monkeypatch,rows):
    monkeypatch.setattr(router,'_identities',{'groups':[{'brand':b,'model':m,'years':set(y),'aliases':router.aliases(b,m)} for b,m,y in rows],'brands':sorted({r[0] for r in rows})})

def test_usual_model_name_resolves_exact_year_and_keeps_suffix_variant(monkeypatch):
    catalog(monkeypatch,[('Yamaha','700 MT-07',[2020]),('Yamaha','MT-07 700',[2024]),('Yamaha','MT-07 Pure 700',[2024])])
    m,_=router.entities(None,'Une MT-07 de 2024')
    assert m==[{'brand':'Yamaha','model':'MT-07 700'}]

def test_overlapping_names_remain_two_distinct_mentions(monkeypatch):
    catalog(monkeypatch,[('Kawasaki','Z 1000',[2020]),('Kawasaki','Z 1000 SX',[2020])])
    m,_=router.entities(None,'Compare Kawasaki Z1000 et Kawasaki Z1000 SX en 2020')
    assert {x['model'] for x in m}=={'Z 1000','Z 1000 SX'}

def test_one_model_family_mentioned_with_two_years_uses_each_years_source_identity(monkeypatch):
    catalog(monkeypatch,[('Yamaha','850 MT-09',[2020]),('Yamaha','MT-09 900',[2021])])
    monkeypatch.setattr(router,'classify',lambda *args:(decisions(operation='comparison'),1,False))
    monkeypatch.setattr(router,'render_details',lambda *args:'facts')
    r=router.route_question(None,'Compare les Yamaha MT-09 de 2020 et 2021 dans un tableau : cylindrée, puissance et poids.')
    assert {(m['model'],m['year']) for m in r['plan']['models']}=={('850 MT-09',2020),('MT-09 900',2021)}

def test_explicit_brand_and_excluded_standard_cannot_introduce_other_brands(monkeypatch):
    catalog(monkeypatch,[('Aprilia','1100 Tuono V4 Factory',[2021]),('Aprilia','1100 Tuono V4',[2021]),('Moto-Guzzi','Normale 500',[2021])])
    models,brands=router.entities(None,'Aprilia Tuono V4 Factory 2021, sans mélanger avec la Tuono V4 normale')
    assert models==[{'brand':'Aprilia','model':'1100 Tuono V4 Factory'}]

def test_short_brand_does_not_pick_another_brands_shared_numeric_suffix(monkeypatch):
    catalog(monkeypatch,[('MZ / MuZ','1000 S',[2005]),('MV-Agusta','F4 1000 S',[2005])])
    models,brands=router.entities(None,'La MZ 1000 S de 2005, type de moteur et cylindrée')
    assert models==[{'brand':'MZ / MuZ','model':'1000 S'}]

def test_brand_prefix_cannot_capture_an_ordinary_article(monkeypatch):
    catalog(monkeypatch,[('Les Triplettes de Bonneville','Saline',[2020]),('Honda','CB 500 F',[2020])])
    models,brands=router.entities(None,'Liste les motos de 2020')
    assert not models and not brands

def test_model_numeric_order_can_change_without_losing_variant_tokens(monkeypatch):
    catalog(monkeypatch,[('KTM','1290 SUPER DUKE R',[2018]),('KTM','Superduke 1290 R',[2020]),('KTM','Superduke 1290 R EVO',[2022])])
    models,_=router.entities(None,'KTM 1290 Super Duke R de 2020')
    assert models==[{'brand':'KTM','model':'Superduke 1290 R'}]


def test_marketing_family_and_acronym_order_are_catalogue_aliases(monkeypatch):
    catalog(monkeypatch,[('Suzuki','1300 GSX-R Hayabusa',[2001]),('Yamaha','600 FAZER FZS',[2000])])
    assert router.entities(None,'Suzuki Hayabusa de 2001')[0]==[{'brand':'Suzuki','model':'1300 GSX-R Hayabusa'}]
    assert router.entities(None,'Yamaha FZS600 Fazer de 2000')[0]==[{'brand':'Yamaha','model':'600 FAZER FZS'}]


def test_equipment_status_and_country_words_cannot_be_marketing_names(monkeypatch):
    catalog(monkeypatch,[('Honda','CRF 1100 L Africa Twin',[2024]),('Suzuki','1000 Katana Royal Serie',[2024]),('Suzuki','GSX-R 1000 R 100th Anniversary France',[2024])])
    assert router.entities(None,'Africa Twin 2024 : ABS de série en France')[0]==[{'brand':'Honda','model':'CRF 1100 L Africa Twin'}]


def test_model_code_ending_in_l_is_not_a_litre_filter(monkeypatch):
    catalog(monkeypatch,[('Honda','CRF 1100 L Africa Twin',[2020]),('Honda','CRF 1100 L Africa Twin Adventure Sports',[2020])])
    raw=decisions(operation='details');raw['answers']['field_suspension']['choice']='yes'
    monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    monkeypatch.setattr(router,'render_details',lambda conn,p:'source facts')
    r=router.route_question(None,'Honda Africa Twin CRF1100L standard de 2020 : diamètre de fourche')
    assert r['route']=='details' and r['plan']['models']==[{'brand':'Honda','model':'CRF 1100 L Africa Twin'}]


def test_followup_year_comparison_retains_both_source_year_bindings(stub,monkeypatch):
    previous={'operation':'details','identity':{'year':2021},'models':[{'brand':'Yamaha','model':'700 MT-07'}],'fields':['weight_wet_kg'],'conditions':[],'equipment':None,'status':'standard'}
    monkeypatch.setattr(router,'classify',lambda *args:(decisions(operation='comparison'),1,False))
    monkeypatch.setattr(router,'render_details',lambda conn,p:'source facts')
    r=router.route_question(None,'Et pour la 2018, donne-moi l’écart de poids',[{'role':'assistant','_catalog_plan':previous}])
    assert r['route']=='comparison'
    assert {m['year'] for m in r['plan']['models']}=={2018,2021}


def test_anaphoric_conversion_uses_the_previous_source_identity(stub,monkeypatch):
    previous={'operation':'details','identity':{'year':2022},'models':[{'brand':'Royal-Enfield','model':'410 Himalayan'}],'fields':['reservoir'],'conditions':[],'equipment':None,'status':'standard'}
    raw=decisions(operation='clarify');raw['answers']['scope']['choice']='unsupported'
    monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    monkeypatch.setattr(router,'render_details',lambda conn,p:'source facts')
    r=router.route_question(None,'Convertis cette capacité en gallons américains',[{'role':'assistant','_catalog_plan':previous}])
    assert r['route']=='details' and r['plan']['models']==previous['models'] and r['plan']['identity']['year']==2022

def test_equipment_intersection_preserves_individual_statuses(stub,monkeypatch):
    monkeypatch.setattr(router,'classify',lambda *args:(decisions(equipment='ABS'),1,False))
    r=router.route_question(None,'En 2024 avec ABS de série et shifter en option')
    assert r['plan']['equipment'] is None
    assert r['plan']['equipment_filters']==[{'equipment':'ABS','status':'standard'},{'equipment':'shifter','status':'optional'}]

def test_followup_from_complex_plan_does_not_crash(stub):
    p={'models':[],'identity':{'year':2024},'fields':['braking']}
    r=router.route_question(None,'Et au moins 4000 euros',[{'role':'assistant','_catalog_plan':p}])
    assert r['plan']['conditions']==[{'field':'price_eur','op':'>=','value':4000}]

def test_date_preposition_is_never_a_model_alias(monkeypatch):
    catalog(monkeypatch,[('BMW','DE 02',[1931]),('BMW','F 900 R',[2020])])
    m,b=router.entities(None,'Liste les BMW de 2020.')
    assert m==[] and b==['BMW']

def test_arithmetic_factual_question_never_calls_mistral(monkeypatch):
    from bikefinder_rag.agent import loop
    monkeypatch.setenv('BIKEFINDER_JEV_ROUTER','1')
    monkeypatch.setattr(router,'entities',lambda *args:([{'brand':'BMW','model':'F 900 R'},{'brand':'Yamaha','model':'XSR 900'}],['BMW','Yamaha']))
    raw=decisions(operation='complex');monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    monkeypatch.setattr(router,'render_details',lambda *args:'Écart documenté : 10 ch')
    monkeypatch.setattr(router,'synthesize_complex',Mock(side_effect=AssertionError('Unnecessary Mistral')))
    answer,history=loop.run_agent(None,None,'Entre BMW F900R 2020 et Yamaha XSR900 2020, laquelle a le plus de chevaux et de combien ?',[],provider='ollama')
    assert '10 ch' in answer and history[-1]['_catalog_route']=='comparison'

def test_blocked_category_context_never_executes_partial_filters(stub):
    q='Tu me sors des trails 2024, moins de 900 balles, selle sous 830 et au moins 60 ch ?'
    first=router.route_question(None,q)
    assert first['plan'] is None and first['pending']['blocked']=='category'
    second=router.route_question(None,'9000 pardon et 850 pour la selle finalement',[{'role':'assistant','_catalog_pending':first['pending']}])
    assert second['plan'] is None and q in second['answer']
    stub.assert_not_called()

def test_short_equipment_name_cannot_disappear_from_source_answer(stub,monkeypatch):
    monkeypatch.setattr(router,'entities',lambda *args:([{'brand':'Kawasaki','model':'VERSYS 650'}],['Kawasaki']))
    raw=decisions(operation='details',equipment='poignées chauffantes');monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    render=Mock(return_value='source facts');monkeypatch.setattr(router,'render_details',render)
    r=router.route_question(None,'Sur une Versys 650 2024, poignées chauffantes et régulateur : inclus, options, ou rien ?')
    assert set(r['plan']['requested_equipment'])=={'poignées chauffantes','régulateur de vitesse'}

def test_blocked_context_keeps_later_numeric_corrections(stub):
    p={'question':'trails 2024 sous 900 euros, selle 830 mm','blocked':'category','updates':[]}
    second=router.route_question(None,'9000 pardon et 850 pour la selle finalement',[{'role':'assistant','_catalog_pending':p}])
    third=router.route_question(None,'Si le prix manque mets les à part',[{'role':'assistant','_catalog_pending':second['pending']}])
    assert '9000 pardon et 850' in third['answer'] and third['plan'] is None


def test_unresolved_identity_context_keeps_year_and_rejects_extrapolation(stub,monkeypatch):
    raw=decisions();raw['answers']['identity_binding']['choice']='unresolved'
    monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    first=router.route_question(None,'Une Zero S 2024 et une S2 Del Mar 2024, en autonomie ?')
    second=router.route_question(None,'Je fais surtout de la voie rapide à 110, laquelle ira le plus loin ?',[{'role':'assistant','_catalog_pending':first['pending']}])
    assert 'Zero S 2024' in second['answer'] and '110' in second['answer'] and second['plan'] is None

def test_excluded_variant_is_not_a_second_motorcycle(monkeypatch):
    catalog(monkeypatch,[('Yamaha','700 Ténéré',[2024]),('Yamaha','700 Ténéré World Raid',[2024]),('Voge','300 Rally',[2024])])
    m,_=router.entities(None,'Yamaha Ténéré 700 standard de 2024, pas la World Raid ni la Rally')
    assert m==[{'brand':'Yamaha','model':'700 Ténéré'}]

def test_numeric_model_word_order_preserves_generation_candidates(monkeypatch):
    catalog(monkeypatch,[('Triumph','765 Street Triple R',[2023]),('Triumph','nouvelle 765 Street Triple R',[2023]),('Triumph','765 Street Triple RS',[2023])])
    m,_=router.entities(None,'La Triumph Street Triple 765 R 2023')
    assert {x['model'] for x in m}=={'765 Street Triple R','nouvelle 765 Street Triple R'}

def test_named_market_context_returns_partial_source_facts_with_caveat(stub,monkeypatch):
    monkeypatch.setattr(router,'entities',lambda *args:([{'brand':'Suzuki','model':'GSX-8S'}],['Suzuki']))
    raw=decisions(operation='details',equipment='ABS');raw['answers']['scope']['choice']='market'
    monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    monkeypatch.setattr(router,'render_details',lambda conn,p:'available facts')
    r=router.route_question(None,'Sur la Suzuki GSX-8S 2023 vendue en France, ABS et shifter sont-ils de série ?')
    assert r['answer']=='available facts' and r['plan']['market_unknown']

def test_negative_dct_reference_does_not_drop_requested_autonomy(stub,monkeypatch):
    monkeypatch.setattr(router,'entities',lambda *args:([{'brand':'Honda','model':'CRF 1100 L Africa Twin'}],['Honda']))
    raw=decisions(operation='details');monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    monkeypatch.setattr(router,'render_details',lambda conn,p:'requested source facts')
    r=router.route_question(None,"Africa Twin standard 2024 à boîte manuelle, pas de l'Adventure Sports ni de la DCT. Pour cette version, que sait-on sur l'autonomie ?")
    assert 'autonomy_km' in r['plan']['fields'] and r['plan']['variant_unknown']


def test_explicit_identity_ambiguity_question_lists_family_variants(stub,monkeypatch):
    monkeypatch.setattr(router,'entities',lambda *args:([{'brand':'Honda','model':'CRF 1100 L Africa Twin'}],['Honda']))
    catalog(monkeypatch,[('Honda','CRF 1100 L Africa Twin',[2024]),('Honda','CRF 1100 L Africa Twin Adventure Sports',[2024])])
    monkeypatch.setattr(router,'_rows',lambda *args:[{'brand':'Honda','model':'CRF 1100 L Africa Twin','year':2024,'source_url':'https://example.test/base'},{'brand':'Honda','model':'CRF 1100 L Africa Twin Adventure Sports','year':2024,'source_url':'https://example.test/adventure'}])
    r=router.route_question(None,'Africa Twin 2024 : avant de répondre dis-moi si ce nom suffit à identifier la fiche.')
    assert r['route']=='clarification' and 'Adventure Sports' in r['answer'] and r['plan']['unresolved_variant']

def test_variant_resolution_preserves_previously_pending_characteristics(stub,monkeypatch):
    monkeypatch.setattr(router,'entities',lambda *args:([{'brand':'Honda','model':'CRF 1100 L Africa Twin'}],['Honda']))
    raw=decisions(operation='details');monkeypatch.setattr(router,'classify',lambda *args:(raw,1,False))
    monkeypatch.setattr(router,'render_details',lambda conn,p:'source facts')
    previous={'operation':'details','identity':{'year':2024},'conditions':[],'models':[{'brand':'Honda','model':'CRF 1100 L Africa Twin'},{'brand':'Honda','model':'CRF 1100 L Africa Twin Adventure Sports'}],'fields':['displacement_ccm','seat_height_mm','weight_dry_kg','weight_wet_kg'],'equipment':None,'status':'standard','unresolved_variant':True}
    r=router.route_question(None,"Je parle de l'Africa Twin standard 2024 à boîte manuelle, pas de l'Adventure Sports ni de la DCT. Pour cette version, que sait-on sur l'autonomie ?",[{'role':'assistant','_catalog_plan':previous}])
    assert set(previous['fields'])<set(r['plan']['fields']) and 'autonomy_km' in r['plan']['fields']
    assert not r['plan']['unresolved_variant']
