"""Conservative SQL answers for complete, unambiguous ABS/year questions."""
import re
from bikefinder_rag.catalog.enriched import folded, filter_catalog, get_catalog_details


def parse_abs_question(question):
    text=re.sub(r"[^a-z0-9 ]",' ',folded(question))
    text=' '.join(text.split())
    patterns=[
        r'(quelles|combien de) motos (?:ont|avec)(?: l)? abs(?: (de serie|en option))? (?:en|de) (\d{4})',
        r'(quelles|combien de) motos (?:de|en) (\d{4}) (?:ont|avec)(?: l)? abs(?: (de serie|en option))?',
    ]
    for i,pattern in enumerate(patterns):
        match=re.fullmatch(pattern,text)
        if match:
            kind,second,third=match.groups()
            qualifier,year=(second,third) if i==0 else (third,second)
            year=int(year)
            if not 1800<=year<=2199:
                return None
            return {'min_year':year,'max_year':year,'equipment':'ABS',
                'equipment_status':'optional' if qualifier=='en option' else 'standard',
                'count_only':kind=='combien de'}
    return None


def answer_abs_question(conn,question):
    arguments=parse_abs_question(question)
    if arguments is None:
        return None
    counts=filter_catalog(conn,**{**arguments,'count_only':True})
    count=counts[0]['matching_motorcycles']
    year=arguments['min_year'];status='en option' if arguments['equipment_status']=='optional' else 'de série'
    introduction=f"Le catalogue documente **{count} fiches de {year} avec ABS {status}**. Les mentions inconnues ne sont pas comptées."
    if arguments['count_only']:
        return introduction
    rows=filter_catalog(conn,**{**arguments,'count_only':False,'limit':10})
    if not rows:
        return introduction+' Cela ne prouve pas qu’aucune autre moto ne disposait de cet équipement.'
    output=[introduction,'','| Moto | Millésime | ABS | Source |','|---|---:|---|---|']
    for row in rows:
        name=(row['brand']+' '+row['model']).replace('|','\\|')
        output.append(f"| {name} | {row['year']} | {status} | [Fiche]({row['source_url']}) |")
    if count>len(rows):
        output+=['',f'Sélection de {len(rows)} fiches sur {count}.']
    return '\n'.join(output)


def answer_catalog_question(conn,question):
    answer=answer_abs_question(conn,question)
    if answer is not None:
        return answer
    text=re.sub(r"[^a-z0-9 -]",' ',folded(question))
    text=' '.join(text.split())
    comparison=re.fullmatch(r"compare l autonomie(?: documentee)? de (?:la |le |l )?(.+) de (\d{4}) et de (?:la |le |l )?(.+) de (\d{4})(?: explique les limites de cette comparaison)?",text)
    if comparison:
        first,y1,second,y2=comparison.groups()
        if any(re.search(r'\b(et|ou|sans|moins|plus|france)\b',m) for m in [first,second]):
            return None
        matches=[get_catalog_details(conn,m,int(y),characteristic='autonomy') for m,y in [(first,y1),(second,y2)]]
        if any(len(rows)!=1 or 'id' not in rows[0] for rows in matches):
            return None
        rows=[r[0] for r in matches]
        names=[(r['brand']+' '+r['model']+f" ({r['year']})").replace('|','\\|') for r in rows]
        values=[' ; '.join(s['value'] for s in r['spec_rows']) or 'Non documentée' for r in rows]
        values=[v.replace('|','\\|') for v in values]
        output=[f'| Caractéristique | {names[0]} | {names[1]} |','|---|---|---|',f'| Autonomie documentée | {values[0]} | {values[1]} |',f"| Source | [Fiche]({rows[0]['source_url']}) | [Fiche]({rows[1]['source_url']}) |"]
        if all('calculee mais non verifiee' in folded(v) for v in values):
            output+=['','Les deux valeurs sont calculées mais non vérifiées. Cette comparaison porte sur des estimations de catalogue, pas sur des autonomies mesurées.']
        return '\n'.join(output)
    patterns=[
        r"quelle est l autonomie de (?:la |le |l )?(.+) (?:de|en) (\d{4})(?: avec (?:la )?source)?",
        r"donne l abs et l autonomie de (?:la |le |l )?(.+) (?:de|en) (\d{4})(?: avec (?:la )?source)?",
    ]
    for n,pattern in enumerate(patterns):
        match=re.fullmatch(pattern,text)
        if not match:
            continue
        model,year=match.groups()
        # Conjunctions or additional constraints need interpretation, never ignore them.
        if re.search(r'\b(et|ou|sans|moins|plus|france)\b',model):
            return None
        rows=get_catalog_details(conn,model,int(year))
        if len(rows)!=1 or 'id' not in rows[0]:
            return None
        row=rows[0]
        autonomy=[r for r in row['spec_rows'] if 'autonomie' in folded(r['label'])]
        name=(row['brand']+' '+row['model']).replace('|','\\|')
        output=[f"**{name} — {row['year']}**",'', '| Caractéristique | Valeur documentée |','|---|---|']
        if n==1:
            equipment=next((e for e in row['equipment'] if e['equipment']=='ABS'),None)
            labels={'standard':'de série','optional':'en option','explicitly_absent':'absence explicitement documentée','unknown':'inconnu / non établi'}
            status=labels[equipment['status']] if equipment else labels['unknown']
            output.append(f'| ABS | {status} |')
        if autonomy:
            for r in autonomy:
                label=r['label'].replace('|','\\|');value=r['value'].replace('|','\\|')
                output.append(f'| {label} | {value} |')
        else:
            output.append('| Autonomie | Non documentée dans cette fiche |')
        output.append(f"| Source | [Fiche Motoplanète]({row['source_url']}) |")
        return '\n'.join(output)
    return None
