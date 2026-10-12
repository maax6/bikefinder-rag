"""Typed tools for the enriched catalog, separate from legacy numeric specs."""
from bikefinder_rag.catalog.enriched import filter_catalog, get_catalog_details, search_technical

def schema(name, description, properties, required=()):
    return {'name':name,'description':description,'input_schema':{
        'type':'object','additionalProperties':False,'properties':properties,'required':list(required)}}

STRING={'type':'string'}
YEAR={'type':'integer','minimum':1800,'maximum':2199}
LIMIT={'type':'integer','minimum':1,'maximum':20}
IDENTITY={'brand':STRING,'model':STRING}
CATALOG_TOOLS=[
    schema('filter_catalog','Filter the enriched Motoplanete catalog by exact year bounds, brand, model and equipment availability. Silence is unknown, never absent. Standard and optional are separate statuses. No market filter: French prices do not prove technical market coverage. Counts are exact catalog counts; lists are bounded.',{
        **IDENTITY,'min_year':YEAR,'max_year':YEAR,'equipment':STRING,
        'equipment_status':{'type':'string','enum':['standard','optional','explicitly_absent','unknown']},
        'count_only':{'type':'boolean'},'limit':LIMIT}),
    schema('get_catalog_details','Sourced enriched technical fiche for an exact model and year. Retains duplicate original rows, autonomy qualifications, equipment proof/status and collection provenance. For autonomy-only questions/comparisons set characteristic=autonomy to return only relevant source rows. Prefer this tool for named motorcycles. Keep ambiguous variants separate.',{**IDENTITY,'year':YEAR,'characteristic':{'type':'string','enum':['autonomy']}},['model','year']),
    schema('search_technical','BGE-M3 semantic retrieval of verbatim technical passages within ONE exact model and year. Use for technical explanations. Does not establish equipment availability; use the classified evidence. First query may compute local embeddings for its scope.',{**IDENTITY,'year':YEAR,'query':STRING,'limit':LIMIT},['query','model','year']),
]
CATALOG_CALLS={'filter_catalog':filter_catalog,'get_catalog_details':get_catalog_details,'search_technical':search_technical}

def execute_catalog_tool(conn, name, arguments, validate):
    if not isinstance(arguments,dict):
        return [{'error':'Arguments must be an object; no search executed.'}]
    definition=next(t for t in CATALOG_TOOLS if t['name']==name)['input_schema']
    if set(arguments)-set(definition['properties']):
        return [{'error':'Unsupported catalog argument; no search executed.'}]
    if name=='filter_catalog' and 'equipment_status' in arguments and 'equipment' not in arguments:
        return [{'error':'An equipment status requires an equipment name; no search executed.'}]
    error=validate(definition,arguments)
    if error:
        return [{'error':error}]
    return CATALOG_CALLS[name](conn,**arguments)
