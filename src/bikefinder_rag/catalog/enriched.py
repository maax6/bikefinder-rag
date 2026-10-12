"""Sourced technical catalog: exact SQL filters and scoped BGE-M3 retrieval."""
import hashlib
import json
import re
import unicodedata

from psycopg.types.json import Jsonb

SCHEMA = """
CREATE TABLE IF NOT EXISTS technical_fiches (
 id TEXT PRIMARY KEY, source_url TEXT NOT NULL UNIQUE, brand TEXT NOT NULL,
 model TEXT NOT NULL, year INTEGER NOT NULL, record JSONB NOT NULL,
 source_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS technical_identity ON technical_fiches(year,brand,model);
CREATE TABLE IF NOT EXISTS technical_equipment (
 object_id TEXT REFERENCES technical_fiches(id), equipment TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('standard','optional','explicitly_absent','unknown')),
 decision JSONB NOT NULL, PRIMARY KEY(object_id,equipment)
);
CREATE INDEX IF NOT EXISTS technical_equipment_status ON technical_equipment(equipment,status);
CREATE TABLE IF NOT EXISTS technical_passages (
 id TEXT PRIMARY KEY, object_id TEXT REFERENCES technical_fiches(id),
 section TEXT NOT NULL, text TEXT NOT NULL, text_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS technical_passage_scope ON technical_passages(object_id);
CREATE TABLE IF NOT EXISTS technical_embeddings (
 text_sha256 TEXT PRIMARY KEY, model TEXT NOT NULL, embedding vector(1024) NOT NULL
);
"""


def folded(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c)).casefold()


def _rows(conn, sql, params):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        names = [d.name for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def scope(brand=None, model=None, year=None, min_year=None, max_year=None):
    clauses, params = ['TRUE'], []
    for column, value in [('brand',brand),('model',model)]:
        if value:
            # Each model word must match; short variant tokens require word boundaries.
            words = value.split() if column == 'model' else [value]
            for word in words:
                expression="(f.brand || ' ' || f.model)" if column=='model' else 'f.brand'
                clauses.append(f"{expression} ~* %s")
                pattern=r'[\s-]*'.join(re.escape(p) for p in re.split(r'[\s-]+',word)) if column=='brand' else re.escape(word)
                params.append(r'\m' + pattern + r'\M')
    for column, op, value in [('year','=',year),('year','>=',min_year),('year','<=',max_year)]:
        if value is not None:
            clauses.append(f'f.{column} {op} %s'); params.append(value)
    return clauses, params


def evidence_rows(conn, rows):
    if not rows:
        return rows
    decisions = _rows(conn, 'SELECT object_id,equipment,status,decision FROM technical_equipment WHERE object_id=ANY(%s)', [[r['id'] for r in rows]])
    grouped = {}
    for d in decisions:
        grouped.setdefault(d['object_id'], []).append({'equipment':d['equipment'],'status':d['status'],
            'proof':d['decision'].get('passages',[]),'reasons':d['decision'].get('reasons',[])})
    for row in rows:
        record = row.pop('record')
        row['spec_rows'] = record['spec_rows']
        row['equipment'] = grouped.get(row['id'], [])
        row['market'] = record.get('identity',{}).get('market')
        row['collection'] = record.get('collection',{})
    return rows


def filter_catalog(conn, brand=None, model=None, min_year=None, max_year=None,
                   equipment=None, equipment_status='standard', count_only=False, limit=10):
    clauses, params = scope(brand,model,min_year=min_year,max_year=max_year)
    if equipment:
        if equipment_status=='unknown':
            clauses.append("NOT EXISTS (SELECT 1 FROM technical_equipment e WHERE e.object_id=f.id AND lower(e.equipment)=lower(%s) AND e.status!='unknown')")
            params.append(equipment)
        else:
            clauses.append('EXISTS (SELECT 1 FROM technical_equipment e WHERE e.object_id=f.id AND lower(e.equipment)=lower(%s) AND e.status=%s)')
            params += [equipment,equipment_status]
    where = ' AND '.join(clauses)
    if count_only:
        return _rows(conn,f'SELECT count(*) AS matching_motorcycles FROM technical_fiches f WHERE {where}',params)
    rows = _rows(conn,f'SELECT f.* FROM technical_fiches f WHERE {where} ORDER BY year DESC,brand,model,id LIMIT %s',params+[limit])
    result = evidence_rows(conn,rows)
    # Keep listing evidence bounded. Full source rows remain available through details.
    for r in result:
        r.pop('spec_rows');r['equipment']=[e for e in r['equipment'] if not equipment or folded(e['equipment'])==folded(equipment)]
    return result


def get_catalog_details(conn, model, year, brand=None, characteristic=None):
    clauses, params = scope(brand,model,year)
    rows = _rows(conn,'SELECT f.* FROM technical_fiches f WHERE '+' AND '.join(clauses)+' ORDER BY brand,model,id LIMIT 4',params)
    exact = [r for r in rows if folded(r['model'])==folded(model) or folded(r['brand']+' '+r['model'])==folded(model)]
    rows = exact or rows
    result = evidence_rows(conn,rows[:3])
    if characteristic=='autonomy':
        for row in result:
            row['spec_rows']=[r for r in row['spec_rows'] if 'autonomie' in folded(r['label'])]
            row.pop('equipment',None)
            row['requested_characteristic']='autonomy'
    if len(rows)>3:
        result.append({'truncated':True,'info':'Plus de trois variantes : préciser le modèle. Ne pas fusionner les fiches.'})
    return result


def search_technical(conn, query, model, year, brand=None, limit=5):
    """Scope identity before similarity; never retrieve a nearby year on failure.

    Embeddings are cached by exact source text, in PostgreSQL. Missing vectors
    are computed locally for this scope only; first search can be slower.
    """
    from bikefinder_rag.embeddings.embedder import embed_text, embed_texts, MODEL_NAME
    details = get_catalog_details(conn,model,year,brand)
    if any(r.get('truncated') for r in details) or len(details)>1:
        return [{'error':'Préciser une variante unique avant la recherche sémantique.'}]
    if not details:
        return []
    ids = [r['id'] for r in details]
    missing = _rows(conn,'SELECT DISTINCT p.text_sha256,p.text FROM technical_passages p LEFT JOIN technical_embeddings e ON e.text_sha256=p.text_sha256 AND e.model=%s WHERE p.object_id=ANY(%s) AND e.text_sha256 IS NULL',[MODEL_NAME,ids])
    if missing:
        vectors = embed_texts([r['text'] for r in missing])
        with conn.cursor() as cur:
            cur.executemany('INSERT INTO technical_embeddings VALUES(%s,%s,%s) ON CONFLICT(text_sha256) DO UPDATE SET model=excluded.model,embedding=excluded.embedding',[(r['text_sha256'],MODEL_NAME,v) for r,v in zip(missing,vectors)])
    vector = embed_text(query)
    return _rows(conn,'SELECT f.brand,f.model,f.year,f.source_url,p.section,p.text,e.embedding <=> %s::vector AS distance FROM technical_passages p JOIN technical_fiches f ON f.id=p.object_id JOIN technical_embeddings e ON e.text_sha256=p.text_sha256 AND e.model=%s WHERE p.object_id=ANY(%s) ORDER BY distance,p.id LIMIT %s',[vector,MODEL_NAME,ids,limit])


def import_catalog(conn, sqlite_path):
    """Transactional upsert; keep other sources and the collector unchanged."""
    import sqlite3
    source=sqlite3.connect('file:'+str(sqlite_path)+'?mode=ro',uri=True)
    try:
        objects=source.execute('SELECT id,url,brand,model,year,source_sha256,record FROM objects').fetchall()
        equipment=source.execute('SELECT object_id,equipment,status,decision FROM equipment').fetchall()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.executemany('INSERT INTO technical_fiches VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET source_url=excluded.source_url,brand=excluded.brand,model=excluded.model,year=excluded.year,record=excluded.record,source_sha256=excluded.source_sha256',
                [(i,u,b,m,y,Jsonb(json.loads(raw)),sha) for i,u,b,m,y,sha,raw in objects])
            ids=[r[0] for r in objects]
            cur.execute('DELETE FROM technical_equipment WHERE object_id=ANY(%s)',[ids])
            cur.executemany('INSERT INTO technical_equipment VALUES(%s,%s,%s,%s)',[(i,e,s,Jsonb(json.loads(d))) for i,e,s,d in equipment])
            cur.execute('DELETE FROM technical_passages WHERE object_id=ANY(%s)',[ids])
            passages=[]
            for i,u,b,m,y,sha,raw in objects:
                for n,p in enumerate(json.loads(raw)['technical_sections']):
                    passages.append((f'{i}:section:{n}',i,p['section'],p['text'],hashlib.sha256(p['text'].encode()).hexdigest()))
            cur.executemany('INSERT INTO technical_passages VALUES(%s,%s,%s,%s,%s)',passages)
        return {'objects':len(objects),'equipment':len(equipment),'passages':len(passages)}
    finally:
        source.close()
