"""Freeze source annotations before the first real-chat submission (exploratory lot)."""
import hashlib,json,re,sqlite3,unicodedata
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'eval_results/technical/chat-baseline-20261015'
DB=ROOT/'data/technical/enrichment-full-20261012/pass2/catalogue.enriched.sqlite3'
c=sqlite3.connect(f'file:{DB}?mode=ro',uri=True)
records={r[0]:json.loads(r[1]) for r in c.execute('select id,record from objects')}
cases=[]
def ids(b,m,y):
 return [i for i,r in records.items() if r['brand']==b and r['model']==m and r['year']==y]
def ref(b,m,y):
 a=ids(b,m,y);assert len(a)==1,(b,m,y,a);return a[0]
def add(i,q,expected,keys=(),category='lecture',group='unseen'):
 cases.append({'id':i,'group':group,'category':category,'turns':[{'question':q,'expected':expected,'object_ids':list(keys)}]})
def val(i,label=None,unit=None):
 rows=records[i]['spec_rows']
 for r in rows:
  if label and r['label']!=label:continue
  if unit:
   z=re.match(r'^([\d ,]+)\s*'+unit+r'\b',r['value'])
   if z:return float(z[1].replace(' ','').replace(',','.'))
 return None
A=ref('Honda','CRF 450 R',2022);B=ref('Royal-Enfield','Classic 350',2022);C=ref('Moto-Guzzi','V 100 Mandello',2022);D=ref('Kawasaki','W 800',2022);E=ref('Triumph','Tiger Sport 660',2022);F=ref('Suzuki','SV 650',2022);G=ref('KTM','390 Adventure',2022);H=ref('Benelli','500 Leoncino',2022);I=ref('Honda','NT 1100',2022);J=ref('Moto-Guzzi','V 100 Mandello S',2022)
add('Q01','Pour la Honda CRF 450 R de 2022, quelle puissance annonce la fiche ? Garde son éventuel caractère approximatif.','Reprendre ≈ 62 ch, avec approximation et source.',[A])
add('Q02','Sur la Royal Enfield Classic 350 de 2022, indique la hauteur de selle et le volume du réservoir.','Deux valeurs, unités et lien exact ; vérifier les lignes sources.',[B])
add('Q03','La Moto Guzzi V 100 Mandello de 2022 transmet-elle par chaîne ou par cardan ? Et comment est refroidi son moteur ?','Transmission secondaire et refroidissement, sans déduction.',[C])
add('Q04','Quelles dimensions de pneus avant et arrière sont indiquées pour la Kawasaki W 800 de 2022 ?','Les deux dimensions distinctes et la bonne fiche.',[D])
add('Q05','Décris les suspensions avant et arrière de la Triumph Tiger Sport 660 de 2022, avec les débattements documentés.','Fourche, amortisseur et deux débattements ; ne pas inventer les réglages.',[E])
add('Q06','Pour la Suzuki SV 650 de 2022, donne séparément le poids sec et le poids tous pleins faits ; marque inconnu ce que la fiche ne donne pas.','Conserver chaque type ; sec non documenté, wet sourcé.',[F])
add('Q07','Pour la KTM 390 Adventure de 2022, compare le frein avant et le frein arrière : diamètre et étriers.','Diamètres et pistons de chaque essieu, liens.',[G])
add('Q08','Quel couple et quel régime sont annoncés pour la Benelli 500 Leoncino de 2022 ?','Conserver mkg/Nm et régime source sans conversion implicite.',[H])
add('Q09','La Honda NT 1100 de 2022 mentionne-t-elle des poignées chauffantes et un régulateur de vitesse ? Distingue série, option et inconnu.','Lire les mentions exactes des équipements, statut uniquement si explicite.',[I],category='equipement')
add('Q10','Compare les suspensions de la Moto Guzzi V 100 Mandello de 2022 et de la Moto Guzzi V 100 Mandello S de 2022.','Deux fiches exactes, différences de suspensions documentées, sans mélanger les variantes.',[C,J],category='comparaison')
K=ref('Royal-Enfield','Meteor 350',2021);L=ref('Royal-Enfield','Meteor 350',2022)
add('Q11','Le poids tous pleins faits de la Royal Enfield Meteor 350 change-t-il entre 2021 et 2022 ? Donne les deux valeurs.','Deux valeurs wet sourcées, variante standard uniquement.',[K,L],category='comparaison')
M=ref('Kawasaki','Z 900',2022);N=ref('Kawasaki','Z 900 RS',2022)
add('Q12','Combien de chevaux séparent la Kawasaki Z 900 de 2022 et la Kawasaki Z 900 RS de 2022 ? Affiche les valeurs puis la différence.','Calculer la différence absolue : '+str(abs(val(M,unit='ch')-val(N,unit='ch')))+' ch.',[M,N],category='calcul')
for i,b,y,kind,label,unit,q in [
 ('Q13','Kawasaki',2021,'max',None,'cc','Quelle est la plus grosse cylindrée documentée chez Kawasaki pour 2021 ? Donne toutes les fiches ex æquo, dans ce catalogue seulement.'),
 ('Q14','Suzuki',2022,'min','Hauteur de selle','mm','Chez Suzuki en 2022, quelle est la selle la plus basse du catalogue ? Donne les éventuels ex æquo.')]:
 population=[k for k,r in records.items() if r['brand']==b and r['year']==y];v={k:val(k,label,unit) for k in population};available={k:x for k,x in v.items() if x is not None};best=(max if kind=='max' else min)(available.values());winners=[k for k,x in available.items() if x==best]
 add(i,q,json.dumps({'value':best,'unit':unit,'winners':[records[k]['name'] for k in winners],'documented':len(available),'total':len(population)},ensure_ascii=False),population,category='agregation')
cs=[ref('Honda','CB 500 F',y) for y in (2020,2021,2022)];vs=[val(k,unit='ch') for k in cs]
add('Q15','Calcule la puissance moyenne de la Honda CB 500 F sur les trois millésimes 2020, 2021 et 2022, une fiche standard par année.','Valeurs '+str(vs)+' ; moyenne arithmétique '+str(sum(vs)/3)+' ch. Ne pas demander un seul millésime.',cs,category='agregation')
pop=[k for k,r in records.items() if r['brand']=='Triumph' and r['year']==2022]
add('Q16','Combien de fiches Triumph portent le millésime 2022 dans notre catalogue ? Je compte les fiches, pas les familles.','Compte exact : '+str(len(pop))+' ; périmètre catalogue.',pop,category='compte')
pop=[k for k,r in records.items() if r['brand']=='Yamaha' and r['year']==2022];eq={r[0] for r in c.execute("select object_id from equipment where lower(equipment)='abs' and status='standard'")};sel=[k for k in pop if k in eq]
add('Q17','Combien de fiches Yamaha de 2022 documentent un ABS de série ?','Compte exact : '+str(len(sel))+' ; absence de mention pas absence réelle.',sel,category='compte')
pop=[k for k,r in records.items() if r['brand']=='Honda' and r['year']==2022];sel=[k for k in pop if (val(k,'Hauteur de selle','mm') or 1e9)<=800 and (val(k,'Poids tous pleins faits','kg') or 1e9)<=200]
add('Q18','Liste les Honda de 2022 avec une selle au plus à 800 mm et un poids tous pleins faits au plus de 200 kg.','Liste exacte : '+', '.join(records[k]['name'] for k in sel)+' ; garder les deux bornes inclusives.',sel,category='filtre')
add('Q19','Quelle marque fabrique l’Interceptor 650 ?','Royal-Enfield. Pas de millésime nécessaire pour cette identité stable dans le catalogue.',[ref('Royal-Enfield','Interceptor 650',2022)],category='identite')
add('Q20','Les chevaux fiscaux et les chevaux du moteur, est-ce la même mesure ?','Question pédagogique adjacente. Répondre distinction sourcée si possible ou limite pertinente ; ne pas demander une valeur à convertir.',category='hors_catalogue')
add('Q21','Je regarde une Royal Enfield Classic 350 de 2022 pour le permis A2 : quelles mentions de permis et de puissance figurent réellement dans sa fiche ?','Lire puissance et permis mentionnés ; absence mention A2 si telle ; aucune certification individuelle.',[B],category='limite_sources')
add('Q22','Donne le couple de la Kawasaki W 800 édition Nebula de 2022.','Édition fictive : pas de substitution silencieuse de la W 800 standard.',category='absence')
add('Q23','Quelle est la capacité du réservoir de la Honda NT 1100 de 2007 ?','Aucune fiche exacte dans corpus ; pas de valeur empruntée à 2022.',category='absence')
add('Q24','La présence de l’ABS sur la Honda NT 1100 de 2022 garantit-elle que je ne peux pas tomber ?','Pas de garantie de sécurité déduite de présence ABS ; la fiche ne démontre pas cette affirmation.',[I],category='limite_sources')
def dialog(i,category,turns):
 cases.append({'id':i,'group':'unseen','category':category,'turns':[{'question':q,'expected':e,'object_ids':ks} for q,e,ks in turns]})
dialog('D01','contexte',[('Donne la puissance et la cylindrée de la Benelli 500 Leoncino de 2022.','Bonne fiche, valeurs et unités.',[H]),('Et son couple, au régime annoncé ?','Reprendre Benelli 500 Leoncino 2022 ; couple et régime source.',[H])])
dialog('D02','clarification',[('Quel volume de réservoir pour la Triumph Tiger Sport 660 ?','Demander année sans inventer.',[]),('Celle de 2022.','Résoudre clarification : même modèle, réservoir de 2022.',[E])])
dialog('D03','pagination',[('Montre les cinq premières fiches Royal Enfield de 2022 du catalogue, puis je demanderai la suite.','Cinq fiches, ordre explicite/stable, annoncer pagination.',[k for k,r in records.items() if r['brand']=='Royal-Enfield' and r['year']==2022]),('Les cinq suivantes, avec les mêmes critères.','Suite sans doublons ni hors-marque/année.',[k for k,r in records.items() if r['brand']=='Royal-Enfield' and r['year']==2022])])
dialog('D04','contexte',[('Liste les Suzuki de 2022 de plus de 100 ch.','Conserver >100ch, Suzuki,2022.',[k for k,r in records.items() if r['brand']=='Suzuki' and r['year']==2022 and (val(k,unit='ch') or 0)>100]),('Et combien de fiches cela représente-t-il ?','Compter exactement la sélection précédente, pas toutes les Suzuki.',[k for k,r in records.items() if r['brand']=='Suzuki' and r['year']==2022 and (val(k,unit='ch') or 0)>100])])
dialog('D05','contexte',[('Pour la Kawasaki W 800 de 2022, donne le poids tous pleins faits.','Valeur wet exacte, source.',[D]),('Et le poids sec, est-il aussi documenté dans cette fiche ?','Pas de confusion entre wet/sec ; absence explicite si inconnu.',[D])])
dialog('D06','contexte',[('Quelle est la puissance de la Honda CB 500 F de 2020 ?','Puissance source 2020.',[cs[0]]),('Et en 2022, sur le même modèle ?','Changer année en conservant Honda CB500F.',[cs[2]])])
add('K01','constructeur de la TENERE 700','Yamaha ; demander un millésime est inutile.',category='identite',group='known')
add('K02','Comment se calcule une puissance fiscale en cv','Question adjacente hors données catalogue ; clarification catégorie/pays/source, pas conversion moteur.',category='hors_catalogue',group='known')
xj=ref('Yamaha','XJ6',2011) if ids('Yamaha','XJ6',2011) else None
add('K03','Quelle type de bridage pour un XJ6 A2 2011','Lire éventuelles mentions techniques ; type de kit/certificat non prouvé à signaler sans certification.',[xj] if xj else [],category='limite_sources',group='known')
yam=[k for k,r in records.items() if r['brand']=='Yamaha' and r['year']==2020];vv={k:val(k,unit='cc') for k in yam};best=max(x for x in vv.values() if x is not None)
add('K04','Quelle cylindrée maximale sur la marque yamaha en 2020','Maximum '+str(best)+' cc ; gagnants '+', '.join(records[k]['name'] for k,x in vv.items() if x==best),yam,category='agregation',group='known')
band=ref('Suzuki','GSF 1200 BANDIT',2000)
dialog('K05','contexte',[('Donne les poids à sec et tous pleins faits de la Suzuki GSF 1200 Bandit de 2000.','214kg sec ;244kg tous pleins.',[band]),('Donne le poids MOYEN à sec et le poids tous pleins faits de la Suzuki GSF 1200 Bandit . Garde bien les deux catégories distinctes.','Clarifier la population à moyenner tout en conservant le contexte 2000 ; pas uniquement exiger un millésime.',[band])]);cases[-1]['group']='known'
# Compare exact normalized wording with all pre-existing JSON evaluation text fields.
def norm(s):return re.sub(r'\W+',' ',unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()).strip()
history=set();files=[]
def walk(v):
 if isinstance(v,dict):
  for k,x in v.items():
   if k in ('question','query','prompt') and isinstance(x,str):history.add(norm(x))
   else:walk(x)
 elif isinstance(v,list):
  for x in v:walk(x)
for p in (ROOT/'eval_results').rglob('*.json'):
 if OUT in p.parents:continue
 try:walk(json.loads(p.read_text()));files.append(str(p.relative_to(ROOT)))
 except (ValueError,UnicodeError):pass
for case in cases:
 for t in case['turns']:
  t['exact_historical_duplicate']=norm(t['question']) in history
  if case['group']=='unseen':assert not t['exact_historical_duplicate'],t['question']
used=set(k for case in cases for t in case['turns'] for k in t['object_ids'])
evidence={k:{'identity':records[k]['identity'],'source_url':records[k]['source_url'],'spec_rows':records[k]['spec_rows'],'technical_sections':records[k].get('technical_sections',[]),'equipment':[{'equipment':e,'status':s,'decision':json.loads(d)} for e,s,d in c.execute('select equipment,status,decision from equipment where object_id=?',(k,))]} for k in sorted(used)}
report={'created_at':datetime.now(timezone.utc).isoformat(),'source_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),'protocol':{'authorship':'Agent-authored exploratory acceptance lot; no independent human annotation. New wording, not guaranteed unseen families or intents.','novelty':'Exact normalized duplicate check only; shared families and repeated followups are not independent observations.','historical_json_files':len(files),'historical_questions':len(history),'grading':'correct = satisfies all requested facts with correct identity, units and usable sources; partial = useful but missing item/precision; failure = wrong task, wrong fact, unnecessary block or lost context; justified limit = relevant safe abstention for unsupported evidence. No promotion on mean score alone.','timing':'Sequential actual Gradio /chat; latency from submit to complete result, client setup separate. No synthetic direct-router replay. First model load and warmed repeats separated.','configuration':'Fresh current-code Gradio, same rapid mode as active UI. BGE original only. Research and experiment disabled. Existing caches retained and hits observed.','planned':'24 standalone questions + 6 two-turn dialogs unseen; 5 known screenshot cases (K05 setup reconstructed); 6 predefined warmed repeat questions Q01,Q03,Q12,Q16,Q19,Q22.','references':'Original cached catalogue evidence, not independent manufacturer verification. Existing application presentation unchanged.'},'cases':cases,'reference_evidence':evidence}
OUT.mkdir(parents=True,exist_ok=True)
p=OUT/'questions-frozen.json'
if p.exists():raise SystemExit('Refuse overwrite frozen lot')
p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('FROZEN',len(cases),'cases',sum(len(x['turns']) for x in cases),'turns',len(used),'reference fiches',hashlib.sha256(p.read_bytes()).hexdigest())
print('XJ',xj)
