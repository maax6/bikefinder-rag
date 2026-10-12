from bikefinder_rag.catalog.measures import project

def record(rows):
    return {'spec_rows':[{'section':s,'label':l,'value':v} for s,l,v in rows]}

def test_explicit_ch_and_france_base_price_only():
    r=record([('Moteur','','105 ch à 9 000 tr/min'),('Tarifs','France — Version de base','9 999 € *'),('Tarifs','France — Version ABS','10 499 €'),('Moteur','Rapport poids / puissance','2 kg/ch')])
    values,proof=project(r)
    assert values['power_ch']==105 and values['price_eur']==9999
    assert proof['price_eur'][0]['value']=='9 999 € *'

def test_unknowns_conflicts_and_units_never_turn_into_values():
    r=record([('Moteur','','100 HP'),('Tarifs','France — Version de base','à partir de 9 000 €'),('Châssis','Poids à sec','180 kg'),('Châssis','Poids tous pleins faits','200 kg'),('Moteur','','10 mkg')])
    values,_=project(r)
    assert values['power_ch'] is None and values['price_eur'] is None and values['torque_nm'] is None
    assert values['weight_dry_kg']==180 and values['weight_wet_kg']==200
    assert project(record([('Moteur','','100 ch'),('Moteur','','110 ch')]))[0]['power_ch'] is None

def test_autonomy_keeps_qualification_and_explicit_nm():
    r=record([('Performances','Autonomie estimée','440 km calculée mais non vérifiée'),('Moteur','','10,50 mkg (103 Nm) à 6000 tr/min')])
    values,proof=project(r)
    assert values['autonomy_km']==440 and values['torque_nm']==103
    assert proof['autonomy_km'][0]['value']=='440 km calculée mais non vérifiée'
