"""Real SQL checks in an isolated schema; enable with RUN_CATALOG_INTEGRATION=1."""
import hashlib
import json
import os
import sqlite3
import uuid

import pytest
from psycopg import sql
from bikefinder_rag.catalog import enriched
from bikefinder_rag.agent.tools import execute_tool

pytestmark=pytest.mark.skipif(os.getenv('RUN_CATALOG_INTEGRATION')!='1',reason='Requires local PostgreSQL')

@pytest.fixture
def catalog(tmp_path):
    from bikefinder_rag.db.client import get_connection
    conn=get_connection();name='test_catalog_'+uuid.uuid4().hex
    with conn.cursor() as cur:
        cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        cur.execute(sql.SQL('SET search_path TO {},public').format(sql.Identifier(name)))
    path=tmp_path/'catalog.sqlite3';db=sqlite3.connect(path)
    db.executescript('CREATE TABLE objects(id,url,brand,model,year,source_sha256,record);CREATE TABLE equipment(object_id,equipment,status,decision);')
    for i,year,status in [('n',2000,'standard'),('s',2000,'optional'),('future',2001,'standard'),('unknown',2000,'unknown')]:
        record={'identity':{'market':None},'spec_rows':[{'section':'Performances','label':'Autonomie','value':'400 km calculée mais non vérifiée'},{'section':'Moteur','label':'Couple','value':'10 Nm'},{'section':'Moteur','label':'Couple','value':'1 mkg'}],
            'technical_sections':[{'section':'Performances','text':'400 km calculée mais non vérifiée'}], 'collection':{'requested_url':'https://source/'+i}}
        raw=json.dumps(record,ensure_ascii=False,sort_keys=True)
        db.execute('INSERT INTO objects VALUES(?,?,?,?,?,?,?)',(i,'https://source/'+i,'Honda','Test '+i.upper(),year,hashlib.sha256(raw.encode()).hexdigest(),raw))
        db.execute('INSERT INTO equipment VALUES(?,?,?,?)',(i,'ABS',status,json.dumps({'passages':[{'text':'ABS en option' if status=='optional' else 'ABS'}]})))
    db.commit();db.close()
    enriched.import_catalog(conn,path)
    try:
        yield conn,path
    finally:
        with conn.cursor() as cur:
            cur.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
        conn.close()

def test_exact_year_and_option_are_not_standard(catalog):
    conn,_=catalog
    rows=execute_tool(conn,'filter_catalog',{'equipment':'ABS','min_year':2000,'max_year':2000})
    assert [r['id'] for r in rows]==['n']
    optional=execute_tool(conn,'filter_catalog',{'equipment':'ABS','equipment_status':'optional','min_year':2000,'max_year':2000})
    assert [r['id'] for r in optional]==['s']

def test_unknown_and_explicit_absence_stay_separate(catalog):
    conn,_=catalog
    assert execute_tool(conn,'filter_catalog',{'equipment':'ABS','equipment_status':'explicitly_absent'})==[]
    assert [r['id'] for r in execute_tool(conn,'filter_catalog',{'equipment':'ABS','equipment_status':'unknown'})]==['unknown']
    assert execute_tool(conn,'filter_catalog',{'equipment':'airbag','equipment_status':'unknown','count_only':True})==[{'matching_motorcycles':4}]

def test_details_preserve_duplicate_labels_and_autonomy(catalog):
    conn,_=catalog
    result=execute_tool(conn,'get_catalog_details',{'model':'Test N','year':2000})
    assert len(result)==1
    assert result[0]['spec_rows'][0]['value']=='400 km calculée mais non vérifiée'
    assert [r['value'] for r in result[0]['spec_rows'][1:]]==['10 Nm','1 mkg']
    assert result[0]['market'] is None
    assert execute_tool(conn,'get_catalog_details',{'model':'Test N','year':1999})==[]
    assert len(execute_tool(conn,'get_catalog_details',{'model':'Honda Test N','year':2000}))==1
    bounded=execute_tool(conn,'get_catalog_details',{'model':'Honda Test N','year':2000,'characteristic':'autonomy'})
    assert len(bounded[0]['spec_rows'])==1
    assert bounded[0]['spec_rows'][0]['value']=='400 km calculée mais non vérifiée'

def test_simple_details_do_not_need_a_generator(catalog):
    from bikefinder_rag.agent.catalog_fast_path import answer_catalog_question
    conn,_=catalog
    answer=answer_catalog_question(conn,"Quelle est l'autonomie de la Honda Test N de 2000 ?")
    assert '400 km calculée mais non vérifiée' in answer and 'https://source/n' in answer
    answer=answer_catalog_question(conn,"Donne l'ABS et l'autonomie de la Honda Test S de 2000, avec la source.")
    assert 'en option' in answer and 'https://source/s' in answer
    assert answer_catalog_question(conn,"Quelle est l'autonomie de la Honda Test N de 2000 et de 2001 ?") is None
    answer=answer_catalog_question(conn,"Compare l'autonomie documentée de la Honda Test N de 2000 et de la Honda Test Future de 2001. Explique les limites de cette comparaison.")
    assert answer.count('400 km calculée mais non vérifiée')==2
    assert 'estimations de catalogue' in answer and 'https://source/future' in answer

def test_unsupported_and_injected_constraints_are_not_ignored(catalog):
    conn,_=catalog
    assert 'error' in execute_tool(conn,'filter_catalog',{'market':'France'})[0]
    assert 'error' in execute_tool(conn,'filter_catalog',{'min_year':2001,'max_year':2000})[0]
    assert execute_tool(conn,'filter_catalog',{'brand':"Honda' OR TRUE --"})==[]

def test_import_is_idempotent(catalog):
    conn,path=catalog
    enriched.import_catalog(conn,path)
    assert execute_tool(conn,'filter_catalog',{'count_only':True})==[{'matching_motorcycles':4}]

def test_scoped_bge_retrieval_and_cache(catalog,monkeypatch):
    conn,_=catalog
    from bikefinder_rag.embeddings import embedder
    calls=[]
    def encode(texts):
        calls.append(texts);return [[1.0]+[0.0]*1023 for _ in texts]
    monkeypatch.setattr(embedder,'embed_texts',encode)
    monkeypatch.setattr(embedder,'embed_text',lambda text:[1.0]+[0.0]*1023)
    rows=execute_tool(conn,'search_technical',{'query':'autonomie','model':'Test N','year':2000})
    assert len(rows)==1 and rows[0]['source_url']=='https://source/n'
    assert rows[0]['text']=='400 km calculée mais non vérifiée'
    execute_tool(conn,'search_technical',{'query':'distance','model':'Test N','year':2000})
    assert len(calls)==1
    assert execute_tool(conn,'search_technical',{'query':'distance','model':'Test N','year':1999})==[]

def test_price_power_filters_are_strict_and_exclude_stale_projections(catalog):
    from bikefinder_rag.catalog.measures import rebuild,filtered
    from psycopg.types.json import Jsonb
    conn,_=catalog
    for id,price,power in [('n',9999,100),('s',10000,110),('future',9500,125),('unknown',9000,None)]:
        with conn.cursor() as cur:
            cur.execute('SELECT record FROM technical_fiches WHERE id=%s',[id]);record=cur.fetchone()[0]
            record['spec_rows']+=[{'section':'Tarifs','label':'France — Version de base','value':f'{price} € *'}]
            if power is not None:record['spec_rows']+=[{'section':'Moteur','label':'','value':f'{power} ch'}]
            cur.execute('UPDATE technical_fiches SET record=%s WHERE id=%s',[Jsonb(record),id])
    rebuild(conn)
    conditions=[{'field':'price_eur','op':'<','value':10000},{'field':'power_ch','op':'>=','value':100}]
    assert [r['id'] for r in filtered(conn,conditions,{'year':2000})]==['n']
    with conn.cursor() as cur:cur.execute("UPDATE technical_fiches SET source_sha256='new-version' WHERE id='n'")
    assert filtered(conn,conditions,{'year':2000})==[]
