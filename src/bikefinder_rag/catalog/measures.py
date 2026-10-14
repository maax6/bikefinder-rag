"""Conservative numeric projections; original rows remain the evidence."""
import re
from bikefinder_rag.catalog.enriched import folded

VERSION='motoplanete-measures-v1'
FIELDS=('price_eur','power_ch','torque_nm','displacement_ccm','seat_height_mm','weight_dry_kg','weight_wet_kg','autonomy_km')
EQUIPMENT_STATUSES={'standard','optional','present','explicitly_absent','unknown'}

def number(text):
    value=re.sub(r'\s','',text)
    if ',' in value:
        value=value.replace('.','').replace(',','.')
    elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+',value):
        value=value.replace('.','')
    return float(value)

def project(record):
    candidates={key:[] for key in FIELDS}
    for row in record.get('spec_rows',[]):
        section,label,value=row['section'],folded(row['label']),row['value']
        text=folded(value);key=match=None
        if section=='Tarifs' and label=='france — version de base':
            match=re.fullmatch(r'\s*([\d\s.,]+)\s*€\s*\*?\s*',value);key='price_eur'
        elif section=='Moteur' and not label.startswith('rapport'):
            for field,pattern in [('power_ch',r'^([\d\s.,]+)\s*ch\b'),('displacement_ccm',r'^([\d\s.,]+)\s*cc\b'),('torque_nm',r'(?:^|\()([\d\s.,]+)\s*nm\b')]:
                match=re.search(pattern,text)
                if match:key=field;break
        elif label=='hauteur de selle':
            match=re.fullmatch(r'\s*([\d\s.,]+)\s*mm\s*',text);key='seat_height_mm'
        elif 'poids a sec' in label or 'poids tous pleins faits' in label or 'poids en ordre de marche' in label:
            match=re.fullmatch(r'\s*([\d\s.,]+)\s*kg\s*',text)
            key='weight_dry_kg' if 'a sec' in label else 'weight_wet_kg'
        elif 'autonomie' in label:
            match=re.match(r'^([\d\s.,]+)\s*km\b',text);key='autonomy_km'
        if key and match:
            candidates[key].append({'value':number(match.group(1)),'row':row})
    result={key:None for key in FIELDS};proof={}
    for key,values in candidates.items():
        if values and len({v['value'] for v in values})==1:
            result[key]=values[0]['value'];proof[key]=[v['row'] for v in values]
    return result,proof

def rebuild(conn):
    from psycopg.types.json import Jsonb
    with conn.transaction(),conn.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS technical_measures (
            object_id TEXT PRIMARY KEY REFERENCES technical_fiches(id),
            price_eur DOUBLE PRECISION,power_ch DOUBLE PRECISION,torque_nm DOUBLE PRECISION,
            displacement_ccm DOUBLE PRECISION,seat_height_mm DOUBLE PRECISION,
            weight_dry_kg DOUBLE PRECISION,weight_wet_kg DOUBLE PRECISION,autonomy_km DOUBLE PRECISION,
            proof JSONB NOT NULL,version TEXT NOT NULL,source_sha256 TEXT)''')
        cur.execute('ALTER TABLE technical_measures ADD COLUMN IF NOT EXISTS source_sha256 TEXT')
        cur.execute('SELECT id,record,source_sha256 FROM technical_fiches');rows=cur.fetchall()
        output=[]
        for id,record,source_sha in rows:
            values,proof=project(record)
            output.append((id,*[values[key] for key in FIELDS],Jsonb(proof),VERSION,source_sha))
        assignments=','.join(f'{key}=excluded.{key}' for key in [*FIELDS,'proof','version','source_sha256'])
        cur.executemany('INSERT INTO technical_measures VALUES('+','.join(['%s']*12)+') ON CONFLICT(object_id) DO UPDATE SET '+assignments,output)
        cur.execute('CREATE INDEX IF NOT EXISTS technical_price_power ON technical_measures(price_eur,power_ch)')
    return {'objects':len(output),'version':VERSION}

def filtered(conn,conditions,identity=None,equipment=None,status='standard',count=False,limit=10,order_by=None,secondary=None,equipment_filters=None,object_ids=None,unknown_fields=None,missing_only=False):
    from bikefinder_rag.catalog.enriched import scope,_rows
    identity=identity or {};clauses,params=scope(**identity)
    if object_ids is not None:
        if not isinstance(object_ids,list) or any(not isinstance(value,str) or not value for value in object_ids):
            raise ValueError('Object scope must be a list of nonempty IDs')
        clauses.append('f.id = ANY(%s)');params.append(list(dict.fromkeys(object_ids)))
    if unknown_fields is None:unknown_fields=[]
    if not isinstance(unknown_fields,list) or any(not isinstance(value,str) or value not in FIELDS for value in unknown_fields):
        raise ValueError('Unsupported unknown numeric field')
    unknown_fields=list(dict.fromkeys(unknown_fields))
    if not isinstance(missing_only,bool) or (missing_only and not unknown_fields):
        raise ValueError('Missing-only requires explicit numeric fields')
    for condition in conditions:
        key,op,value=condition['field'],condition['op'],condition['value']
        if key not in FIELDS or op not in ['<','<=','>','>=','=']:
            raise ValueError('Unsupported numeric filter')
        clause=f'm.{key} {op} %s'
        if key in unknown_fields:clause='('+clause+f' OR m.{key} IS NULL)'
        clauses.append(clause);params.append(value)
    if missing_only:
        clauses.append('('+' OR '.join(f'm.{key} IS NULL' for key in unknown_fields)+')')
    requested_equipment=[{'equipment':equipment,'status':status}] if equipment else []
    if equipment_filters is not None:
        if not isinstance(equipment_filters,list):raise ValueError('Equipment filters must be a list')
        requested_equipment.extend(equipment_filters)
    if len(requested_equipment)>4:raise ValueError('At most four equipment filters are supported')
    for criterion in requested_equipment:
        if not isinstance(criterion,dict):raise ValueError('Invalid equipment filter')
        name,criterion_status=criterion.get('equipment'),criterion.get('status')
        if not isinstance(name,str) or not name.strip() or not isinstance(criterion_status,str) or criterion_status not in EQUIPMENT_STATUSES:
            raise ValueError('Unsupported equipment filter')
        if criterion_status=='unknown':
            clauses.append("NOT EXISTS (SELECT 1 FROM technical_equipment e WHERE e.object_id=f.id AND lower(e.equipment)=lower(%s) AND e.status!='unknown')");params.append(name)
        elif criterion_status=='present':
            clauses.append("EXISTS (SELECT 1 FROM technical_equipment e WHERE e.object_id=f.id AND lower(e.equipment)=lower(%s) AND e.status IN ('standard','optional'))");params.append(name)
        else:
            clauses.append('EXISTS (SELECT 1 FROM technical_equipment e WHERE e.object_id=f.id AND lower(e.equipment)=lower(%s) AND e.status=%s)');params.extend([name,criterion_status])
    if secondary:
        patterns={'cardan':'cardan','courroie':'courroie','chaine':'cha[îi]ne'}
        if secondary not in patterns:raise ValueError('Unsupported secondary transmission')
        clauses.append("EXISTS (SELECT 1 FROM jsonb_array_elements(f.record->'spec_rows') s WHERE s->>'section'='Transmission' AND s->>'value' ~* %s)")
        params.append(r'^Secondaire\s+par\s+'+patterns[secondary]+r'\M')
    ordering='f.year DESC,f.brand,f.model,f.id'
    if order_by:
        field=order_by.lstrip('-')
        if field not in FIELDS:raise ValueError('Unsupported sort')
        clauses.append(f'm.{field} IS NOT NULL')
        ordering=f'm.{field} '+('DESC' if order_by.startswith('-') else 'ASC')+',f.brand,f.model,f.id'
    # Identity/equipment queries must keep fiches without a current projection.
    # Numeric constraints and ranking still require values from the exact source.
    join='JOIN' if conditions or order_by or missing_only else 'LEFT JOIN'
    base=' FROM technical_fiches f '+join+' technical_measures m ON m.object_id=f.id AND m.source_sha256=f.source_sha256 WHERE '+' AND '.join(clauses)
    if count:return _rows(conn,'SELECT count(*) AS count'+base,params)[0]['count']
    rows=_rows(conn,'SELECT f.id,f.brand,f.model,f.year,f.source_url,f.record,m.*'+base+' ORDER BY '+ordering+' LIMIT %s',params+[limit])
    for row in rows:
        if row.get('proof') is None:row['proof']={}
    return rows
