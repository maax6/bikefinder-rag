"""Literal language helpers: preserve user constraints without generation."""
import re
from functools import lru_cache
from bikefinder_rag.catalog.enriched import folded


def language(text):
    text=folded(text)
    for pattern,replacement in [(r'\b(?:balles|boules)\b','euros'),(r'\b(?:bourrins|canassons)\b','chevaux'),(r'\bregulateur\b(?! de vitesse)','regulateur de vitesse'),(r'\ba(?:vec)?\s+un plein\b','avec un plein')]:
        text=re.sub(pattern,replacement,text)
    amounts={'trois':'3','cinq':'5','dix':'10','vingt':'20'}
    for word,value in amounts.items():text=re.sub(r'\b(les|top|montre moi|donne moi)\s+'+word+r'\b',lambda m:m[1]+' '+value,text)
    return text


def aliases(brand,model):
    compact=lambda s:re.sub(r'[^a-z0-9]','',folded(s))
    short=re.sub(r'^\d+(?:[.,]\d+)?\s+','',model)
    names={model,short}
    tail=re.sub(r'\s+\d{3,}(?:[.,]\d+)?$','',model)
    if len(compact(tail))>=4:names.add(tail)
    prefix=re.match(r'^(\d+(?:[.,]\d+)?)\s+(.+)$',model)
    if prefix:names.add(prefix[2]+' '+prefix[1])
    words=model.split()
    # A named suffix such as Africa Twin remains a candidate family, never
    # proof that every variant in that family has the same specification.
    for i in range(1,len(words)-1):
        suffix=' '.join(words[i:])
        if re.search(r'[a-zA-Z]',suffix):names.add(suffix)
    for name in list(names):
        numbered=re.match(r'^(\d+(?:[.,]\d+)?)\s+(.+)$',name)
        if numbered:
            words=numbered[2].split()
            for position in range(1,len(words)+1):names.add(' '.join([*words[:position],numbered[1],*words[position:]]))
    generic={'rally','classic','standard','pure','sport','adventure','nouvelle','touring','racing','custom','roadster'}
    result={compact(brand+' '+name) for name in names if name==model or len(compact(name))>=4}
    result.update(compact(name) for name in names if len(compact(name))>=4 and compact(name) not in generic and re.search('[a-z]',compact(name)))
    return result


@lru_cache(maxsize=128)
def span_context(text):
    positions=[i for i,c in enumerate(text) if re.match('[a-z0-9]',c)]
    return positions,''.join(text[i] for i in positions)


def spans(text,alias):
    positions,simple=span_context(text);result=[]
    if alias not in simple:return result
    for match in re.finditer(re.escape(alias),simple):
        start,end=positions[match.start()],positions[match.end()-1]+1
        if (start and text[start-1].isalnum()) or (end<len(text) and text[end].isalnum()):continue
        result.append((start,end))
    return result


def equipment_status(text,equipment):
    name=folded(equipment);text=folded(text)
    at=text.find(name)
    region=text[max(0,at-55):at+len(name)+60] if at>=0 else text
    if at>=0:
        left=text[:at].rsplit(' et ',1)[-1][-55:];right=text[at+len(name):].split(' et ',1)[0][:60]
        region=left+name+right
    before=region.split(name)[0]
    if re.search(r'(?:\bsans|\baucun[es]?|\bpas\s+(?:de|d[’\'])?|\bn[’\']?ont\s+pas\s+(?:de|d[’\'])?)\s*$',before):return 'explicitly_absent'
    if re.search(r'(?<!pas )\binconnu\b|\bnon documente',region):return 'unknown'
    if re.search(r'serie.*\bou\b.*option|option.*\bou\b.*serie',region):return 'present'
    if re.search(r'\ben option\b|\boptionnel|payer.*(?:en plus|supplement)',region):return 'optional'
    if re.search(r'\bde serie\b|\bd.origine\b|\bmonte d.origine\b',region):return 'standard'
    return None


def merge_conditions(previous,current,replace=False):
    """A new lower bound must not erase an existing upper bound."""
    direction=lambda op:'lower' if op in ['>','>='] else 'upper' if op in ['<','<='] else 'exact'
    keys={(c['field'],direction(c['op'])) for c in current}
    fields={c['field'] for c in current}
    old=[c for c in previous if not (c['field'] in fields and (replace or direction(c['op'])=='exact' or (c['field'],direction(c['op'])) in keys))]
    return old+current


def negated_mention(text,start):
    before=folded(text[max(0,start-45):start])
    return bool(re.search(r"\b(?:pas|ni|sans|sauf|hors|exclure)\s+(?:de\s+)?(?:(?:la|le|les)\s+|l[’']\s*)?$",before))
