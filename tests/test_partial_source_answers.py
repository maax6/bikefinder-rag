from unittest.mock import Mock
from bikefinder_rag.agent import jev_router as router


def fiche(model,power,weight_label,weight):
    return {'id':model,'brand':'Triumph','model':model,'year':2023,'source_url':'https://example.org/'+model.replace(' ','-'),
            'record':{'spec_rows':[{'section':'Moteur','label':'','value':f'{power} ch à 10000 tr/min'},
                                 {'section':'Châssis','label':weight_label,'value':f'{weight} kg'}]}}


def test_ambiguous_generation_still_shows_separate_source_values(monkeypatch):
    rows=[fiche('765 Street Triple R',118,'Poids à sec',168),fiche('nouvelle 765 Street Triple R',120,'Poids tous pleins faits',189)]
    monkeypatch.setattr(router,'_rows',Mock(side_effect=[[r] for r in rows]))
    plan={'models':[{'brand':r['brand'],'model':r['model']} for r in rows],'identity':{'year':2023},'fields':['power_ch','weight_dry_kg','weight_wet_kg'],'source_question':'Street Triple 765 R 2023 : puissance et poids','calculation_question':''}
    output=router.render_details(None,plan)
    assert '118 ch' in output and '120 ch' in output and '168 kg' in output and '189 kg' in output
    assert 'présentées séparément' in output and output.count('[Fiche](')==2
    assert 'Non documenté' in output


def test_ratio_for_all_candidates_keeps_the_weight_type_visible(monkeypatch):
    rows=[fiche('765 Street Triple RS',123,'Poids à sec',166),fiche('nouvelle 765 Street Triple RS',130,'Poids tous pleins faits',188),fiche('Z 900',125,'Poids tous pleins faits',212)]
    rows[-1]['brand']='Kawasaki'
    monkeypatch.setattr(router,'_rows',Mock(side_effect=[[r] for r in rows]))
    plan={'models':[{'brand':r['brand'],'model':r['model']} for r in rows],'identity':{'year':2023},'fields':['power_ch'],'source_question':'Ratio ch par kilo Street Triple RS 2023 et Z900 2023','calculation_question':'ratio ch par kilo'}
    output=router.render_details(None,plan)
    assert '0,741 ch/kg (à sec)' in output and '0,691 ch/kg (tous pleins' in output and '0,590 ch/kg (tous pleins' in output
    assert 'aucun classement' in output


def test_direct_topics_use_only_their_preserved_rows():
    rows=[{'section':'Châssis','label':'Réservoir','value':'15 litres'},
          {'section':'Châssis','label':'Largeur','value':'790 mm'},
          {'section':'Châssis','label':'Hauteur de selle','value':'810 mm'},
          {'section':'Coloris','label':'Coloris','value':'non défini'},
          {'section':'Train avant','label':'Roue avant','value':'120 / 70 - 17'},
          {'section':'Train avant','label':'Freinage','value':'2 disques'}]
    r={'spec_rows':rows}
    assert router.selected_rows(r,'reservoir')==rows[:1]
    assert router.selected_rows(r,'dimensions')==rows[1:2]
    assert router.selected_rows(r,'colors')==rows[3:4]
    assert router.selected_rows(r,'wheels')==rows[4:5]

def test_missing_one_year_does_not_erase_the_other_models_available_data(monkeypatch):
    r=fiche('765 Street Triple R',118,'Poids à sec',168)
    monkeypatch.setattr(router,'_rows',Mock(side_effect=[[r],[]]))
    plan={'models':[{'brand':'Triumph','model':'765 Street Triple R','year':2023},{'brand':'Triumph','model':'765 Street Triple R','year':1990}], 'identity':{},'fields':['power_ch'],'source_question':'Compare les deux années'}
    out=router.render_details(None,plan)
    assert '118 ch' in out and 'Comparaison partielle' in out and 'Fiche non disponible' in out
    assert '[Fiche](None)' not in out

def test_launch_price_caveat_is_retained_when_a_followup_adds_models(monkeypatch):
    r=fiche('765 Street Triple R',118,'Poids à sec',168)
    r['record']['spec_rows'].append({'section':'Tarifs','label':'France — Version de base','value':'9 995 €'})
    monkeypatch.setattr(router,'_rows',Mock(return_value=[r]))
    plan={'models':[{'brand':'Triumph','model':r['model']}],'identity':{'year':2023},'fields':['price_eur'],'source_notes':['launch_price'],'source_question':'Ajoute la RS pour les mêmes données'}
    out=router.render_details(None,plan)
    assert '9 995' in out and 'prix au lancement' in out and 'ne sont pas établis' in out


def test_explicit_abs_source_does_not_repeat_unknown_derived_presence(monkeypatch):
    r=fiche('410 Himalayan',24,'Poids tous pleins faits',199)
    r['record']['spec_rows'].append({'section':'Équipement','label':'Assistance au freinage','value':'A.B.S. disconnectable'})
    evidence=[{'equipment':'ABS','status':'unknown','decision':{'passages':[{'text':'A.B.S. disconnectable'}]}}]
    monkeypatch.setattr(router,'_rows',Mock(side_effect=[[r],evidence]))
    plan={'models':[{'brand':r['brand'],'model':r['model']}],'identity':{'year':2023},'fields':['equipment'],'requested_equipment':['ABS']}
    out=router.render_details(None,plan)
    assert 'A.B.S. disconnectable' in out and 'présence documentée' in out
    assert 'ABS : inconnu' not in out and 'de série' not in out


def test_unconfirmed_named_variant_keeps_its_values_qualified(monkeypatch):
    r=fiche('750 S FORMULA',92,'Poids à sec',185)
    monkeypatch.setattr(router,'_rows',Mock(return_value=[r]))
    model={'brand':r['brand'],'model':r['model']}
    plan={'models':[model],'identity':{'year':2023},'fields':['power_ch'],'candidate_variants':[model]}
    out=router.render_details(None,plan)
    assert 'Variante à confirmer' in out and '92 ch' in out and 'uniquement à ces variantes' in out


def test_missing_ground_clearance_quotes_a_separate_exact_source(monkeypatch):
    r=fiche('Z 750',110,'Poids à sec',195)
    monkeypatch.setattr(router,'_rows',Mock(return_value=[r]))
    extra=Mock(return_value=[{'label':'Ground clearance','value':'165 mm (6.5 inches)','source_url':'https://bikez.com/motorcycles/kawasaki_z_750_2004.php'}])
    monkeypatch.setattr(router,'get_supplemental_rows',extra)
    plan={'models':[{'brand':r['brand'],'model':r['model']}],'identity':{'year':2023},'fields':['dimensions'],'source_question':'garde au sol'}
    out=router.render_details(None,plan)
    assert 'fiche Motoplanète' in out and 'Complément Bikez' in out and '165 mm (6.5 inches)' in out
    extra.assert_called_once_with(None,{'brand':r['brand'],'model':r['model'],'year':2023},'ground_clearance')


def test_missing_cruise_control_quotes_source_without_claiming_standard_fitment(monkeypatch):
    r=fiche('RS 660',100,'Poids à sec',169)
    monkeypatch.setattr(router,'_rows',Mock(side_effect=[[r],[]]))
    extra=Mock(return_value=[{'label':'Comments','value':'ACC (cruise control)','source_url':'https://bikez.com/motorcycles/aprilia_rs_660_2021.php','qualifier':'Statut série/option non établi.'}])
    monkeypatch.setattr(router,'get_supplemental_rows',extra)
    plan={'models':[{'brand':r['brand'],'model':r['model']}],'identity':{'year':2023},'fields':['equipment'],'requested_equipment':['régulateur de vitesse']}
    out=router.render_details(None,plan)
    assert 'ACC (cruise control)' in out and 'Statut série/option non établi' in out and 'de série' not in out


def test_known_primary_cruise_control_does_not_trigger_a_supplement(monkeypatch):
    r=fiche('RS 660',100,'Poids à sec',169)
    evidence=[{'equipment':'régulateur de vitesse','status':'standard','decision':{'passages':[{'text':'régulateur de vitesse de série'}]}}]
    monkeypatch.setattr(router,'_rows',Mock(side_effect=[[r],evidence]))
    extra=Mock();monkeypatch.setattr(router,'get_supplemental_rows',extra)
    plan={'models':[{'brand':r['brand'],'model':r['model']}],'identity':{'year':2023},'fields':['equipment'],'requested_equipment':['régulateur de vitesse']}
    out=router.render_details(None,plan)
    assert 'de série' in out and 'Complément Bikez' not in out
    extra.assert_not_called()

def test_count_keeps_requested_missing_values_separate(monkeypatch):
    seen=[]
    def count(conn,conditions,**kw):seen.append(kw);return 2 if kw.get('missing_only') else 3
    monkeypatch.setattr(router,'filtered',count)
    plan={'operation':'count','identity':{'year':2020},'conditions':[{'field':'price_eur','op':'<','value':9000}],'include_unknown_fields':['price_eur']}
    out=router.render_list(None,plan)
    assert '3 fiches' in out and '2 fiches complémentaires' in out
    assert seen[1]['unknown_fields']==['price_eur']
