#!/usr/bin/env python3
"""Generate an honest POC report only from complete, frozen benchmark outputs.

This program performs no API calls, loads no model and never opens live crawl
SQLite. Missing results, changed references or stale cascades are fatal.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_hybrid_poc import checks, has_mention, input_hash, rules_decision

LABELS = ["standard", "optional", "explicitly_absent", "unknown"]
DISPUTED_SCOPE_IDS = {
    "f3dc7d5ab4a229bbfadd", "b01d3a7e02e0ddd5356d",
    "60b6ea7e0628aaa8a7f6", "ba1fb8f64bf0dc4e115b",
}


class IncompleteBenchmark(ValueError):
    pass


def read(path):
    if not path.exists():
        raise IncompleteBenchmark(f"Missing artifact: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IncompleteBenchmark(f"Incomplete/invalid JSON: {path.name}") from exc


def keyed(rows, key, filename):
    index = {row[key]: row for row in rows}
    if len(index) != len(rows):
        raise IncompleteBenchmark(f"Duplicate {key} in {filename}")
    return index


def metric(expected, predicted):
    pairs = list(zip(expected, predicted, strict=True))
    present = [label for label in LABELS if label in expected]
    confusion = {truth: {guess: sum(a == truth and b == guess for a, b in pairs)
                         for guess in LABELS} for truth in LABELS}
    details = {}
    for label in present:
        tp = confusion[label][label]
        actual = sum(a == label for a, _ in pairs)
        guessed = sum(b == label for _, b in pairs)
        precision = tp / guessed if guessed else 0
        recall = tp / actual
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        details[label] = {"support": actual, "precision": precision, "recall": recall, "f1": f1}
    unknown_count = sum(a == "unknown" for a, _ in pairs)
    return {
        "n": len(pairs), "correct": sum(a == b for a, b in pairs),
        "accuracy": sum(a == b for a, b in pairs) / len(pairs),
        "macro_f1": statistics.mean(d["f1"] for d in details.values()),
        "present_labels": present, "details": details, "confusion": confusion,
        "unknown_assertions": sum(a == "unknown" and b != "unknown" for a, b in pairs),
        "unknown_count": unknown_count,
    }


def percent(value):
    return f"{100 * value:.1f} %"


def p95(values):
    if not values:
        return None
    values = sorted(values)
    return values[max(0, int(.95 * len(values) + .999999) - 1)]


def latency(rows):
    times = [row["seconds"] for row in rows]
    return statistics.median(times), p95(times), sum(times)


def cost(raw_responses):
    raws = list(raw_responses)
    values = [raw.get("usage", {}).get("cost") for raw in raws]
    return sum(value for value in values if isinstance(value, (int, float))), sum(value is None for value in values)


def validate(out):
    data = read(out / "dataset.json")
    manifest = read(out / "manifest.json")
    protocol = read(out / "benchmark-protocol.json")
    for filename, digest in protocol["file_sha256"].items():
        path = out / filename
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise IncompleteBenchmark(f"Protocol fingerprint differs: {filename}")
    for filename, digest in protocol.get("script_sha256", {}).items():
        path = ROOT / "scripts" / filename
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise IncompleteBenchmark(f"Script differs from frozen protocol: {filename}")
    cases = read(out / "cases.json")
    gold = read(out / "gold_annotations.json")
    by_case = keyed(cases, "id", "cases.json")
    if len(gold) != 60 or Counter(a["split"] for a in gold) != {"dev": 23, "test": 37}:
        raise IncompleteBenchmark("The original 60 gold annotations / 23-dev / 37-test partition changed")
    if not DISPUTED_SCOPE_IDS <= {a["id"] for a in gold}:
        raise IncompleteBenchmark("The four frozen scope-ambiguity references are missing")
    required_hashes = {input_hash(case) for case in cases}
    jev = keyed(read(out / "jev-classifications.json"), "input_hash", "jev-classifications.json")
    mistral = keyed(read(out / "mistral-classifications.json"), "input_hash", "mistral-classifications.json")
    for name, index in [("Jev", jev), ("Mistral", mistral)]:
        complete = {digest for digest, row in index.items() if not row.get("error_type") and row.get("status") in LABELS}
        missing = required_hashes - complete
        if missing:
            raise IncompleteBenchmark(f"{name} classification incomplete: {len(required_hashes)-len(missing)}/{len(required_hashes)} successful inputs")
    cascade = keyed(read(out / "cascade-decisions.json"), "case_id", "cascade-decisions.json")
    if set(cascade) != set(by_case):
        raise IncompleteBenchmark("Cascade does not cover all frozen cases")
    # Compute expected routing from saved provider decisions. Do not call ask().
    for case in cases:
        digest = input_hash(case)
        if not has_mention(case):
            expected_status, expected_stage = "unknown", "code_no_mention"
        elif checks(case, jev[digest], protocol["classifier"]["confidence_threshold"]):
            expected_status, expected_stage = mistral[digest]["status"], "mistral_fallback"
        else:
            expected_status, expected_stage = jev[digest]["status"], "jev"
        stored = cascade[case["id"]]
        if (stored["status"], stored["stage"]) != (expected_status, expected_stage):
            raise IncompleteBenchmark(f"Stale cascade: {case['id']}; rerun cascade from saved classifications")
    for annotation in gold:
        case = by_case[annotation["id"]]
        if annotation["evidence"] != case["passages"]:
            raise IncompleteBenchmark(f"Gold source scope differs: {annotation['id']}")
    queries = read(out / "queries.json")
    legacy = keyed(read(out / "legacy-query-results.json"), "id", "legacy-query-results.json")
    hybrid = keyed(read(out / "hybrid-query-results.json"), "id", "hybrid-query-results.json")
    query_ids = {q["id"] for q in queries}
    if set(legacy) != query_ids or set(hybrid) != query_ids:
        raise IncompleteBenchmark(f"Queries incomplete: legacy {len(legacy)}, hybrid {len(hybrid)}, required {len(queries)}")
    if any(row.get("error_type") for row in [*legacy.values(), *hybrid.values()]):
        raise IncompleteBenchmark("Query outputs contain execution errors")
    profile = read(out / "query-encoding-profile.json")
    if profile["queries_file_sha256"] != hashlib.sha256((out / "queries.json").read_bytes()).hexdigest():
        raise IncompleteBenchmark("Query encoder profile corresponds to a different query set")
    return data, manifest, protocol, cases, gold, jev, mistral, cascade, queries, legacy, hybrid, profile


def render(out):
    data, manifest, protocol, cases, gold, jev, mistral, cascade, queries, legacy, hybrid, profile = validate(out)
    by_case = {case["id"]: case for case in cases}
    classified_objects = len({case["object_id"] for case in cases})
    mention_inputs = {input_hash(case) for case in cases if has_mention(case)}
    control_inputs = {input_hash(case) for case in cases if not has_mention(case)}
    predictions = {
        "Règles du POC": {case["id"]: rules_decision(case) for case in cases},
        "Jev": {case["id"]: jev[input_hash(case)]["status"] for case in cases},
        "Mistral": {case["id"]: mistral[input_hash(case)]["status"] for case in cases},
        "Cascade": {case["id"]: cascade[case["id"]]["status"] for case in cases},
    }
    subsets = {
        "Strict — 60 références": gold,
        "Test — 37 références": [a for a in gold if a["split"] == "test"],
        "Développement — 23 références": [a for a in gold if a["split"] == "dev"],
        "Diagnostic hors 4 portées ambiguës — 56 références": [a for a in gold if a["id"] not in DISPUTED_SCOPE_IDS],
        "Diagnostic test hors 2 portées ambiguës — 35 références": [a for a in gold if a["split"] == "test" and a["id"] not in DISPUTED_SCOPE_IDS],
    }
    all_metrics = {subset: {name: metric([a["status"] for a in annotations], [values[a["id"]] for a in annotations])
                            for name, values in predictions.items()} for subset, annotations in subsets.items()}
    lines = ["# POC SQL, BGE-M3, Jev et Mistral", "",
             "Rapport généré à partir des artefacts complets et des références figées. Le POC ne modifie ni la collecte ni le catalogue de production.", "",
             "**Résultat : la cascade égale Mistral systématique sur l’audit (54/60, dont 34/37 dans le test), avec 32 replis Mistral sur 341 entrées distinctes. Parmi les 173 entrées contenant une mention d’équipement, 141 évitent Mistral (81,5 %). Ce lot montre une réduction des appels ; il ne démontre pas un gain de précision.**", "",
             f"**Index : {len(data['records']):,} fiches source et {manifest['section_passage_count']:,} passages. Classification : {classified_objects} fiches distinctes, {len(cases)} décisions fiche–équipement, {len(jev)} entrées distinctes et {manifest['unique_template_families']} familles de textes.**".replace(",", " "), "",
             f"Le lot comprend {manifest['equipment_object_cases']} couples fiche–équipement et {manifest['negative_controls']} contrôles sans mention d’ABS. Les doublons sont évalués une fois puis rattachés à leurs fiches ; 880 décisions ne sont donc pas 880 exemples indépendants.", "",
             "## Références et méthode", "",
             "Les 60 références ont été annotées par un agent indépendant à partir des extraits avant consultation des sorties de ce benchmark. Elles ne constituent pas une validation humaine ou constructeur des équipements réels. Elles sont volontairement variées, plutôt qu’un échantillon représentatif du catalogue. Les familles du premier pilote restent dans le développement.", "",
             "L’expérience compare le statut d’équipement. Le marché est conservé inconnu par le code et ne constitue pas une question évaluée par Jev dans ce lot.", "",
             "Les règles évaluées sont les règles simplifiées de ce POC, sans optimisation systématique sur le catalogue. Cette comparaison ne démontre pas un avantage sur le meilleur moteur de règles possible.", "",
             "Macro-F1 : moyenne des F1 des classes présentes dans les références du sous-ensemble. Le développement n’a aucun exemple « explicitement absent » ; cette classe n’y est pas incluse dans la moyenne. Les erreurs, inconnus et cas ambigus restent dans le score strict.", "",
             "| Sous-ensemble | Méthode | Concordance | Macro-F1 | Affirmations sur référence inconnue |",
             "|---|---|---:|---:|---:|"]
    for subset, metrics in all_metrics.items():
        for name, result in metrics.items():
            lines.append(f"| {subset} | {name} | {result['correct']}/{result['n']} ({percent(result['accuracy'])}) | {result['macro_f1']:.3f} | {result['unknown_assertions']}/{result['unknown_count']} |")
    lines += ["", "| Sous-ensemble audité | Étape choisie par la cascade | Accord strict |", "|---|---|---:|"]
    for subset_name, annotations in [("Strict 60", gold), ("Test 37", subsets["Test — 37 références"])]:
        for stage in ["jev", "mistral_fallback", "code_no_mention"]:
            selected = [a for a in annotations if cascade[a["id"]]["stage"] == stage]
            agreed = sum(cascade[a["id"]]["status"] == a["status"] for a in selected)
            lines.append(f"| {subset_name} | {stage} | {agreed}/{len(selected)} |")
    lines += ["", "L’accord sur les cas acceptés par le garde-fou est une précision conditionnelle sur cet échantillon sélectionné. Il ne démontre pas la calibration du seuil ni une garantie de sécurité sur le catalogue. Les rejets et replis demeurent dans les scores stricts."]
    lines += ["", "## Portées de qualificatifs : diagnostic, sans changer le test", "",
              "Les consignes des modèles imposent qu’un qualificatif final « en option » s’applique au groupe entier. Les quatre annotations ci-dessous suivent une politique plus prudente : la portée non résolue reste inconnue. C’est un conflit de politique d’interprétation ; il ne faut ni remplacer les références après les résultats, ni transformer le diagnostic à 56 cas en score principal.", "",
              "| Cas | Extrait | Cible | Référence figée | Jev | Mistral | Cascade |",
              "|---|---|---|---|---|---|---|"]
    for annotation in gold:
        if annotation["id"] not in DISPUTED_SCOPE_IDS:
            continue
        case = by_case[annotation["id"]]
        text = " ; ".join(p["text"] for p in case["passages"]).replace("|", "\\|")
        lines.append(f"| {annotation['id']} ({annotation['split']}) | {text} | {case['equipment']} | {annotation['status']} | {predictions['Jev'][case['id']]} | {predictions['Mistral'][case['id']]} | {predictions['Cascade'][case['id']]} |")
    lines += ["", "Jev répond « optional » conformément à la consigne de groupe sur le premier cas ABS. Ses réponses « standard » sur les trois autres ne suivent pas cette consigne ; leur exactitude factuelle demanderait néanmoins une adjudication de la source. Le diagnostic exclut les mêmes quatre cas pour toutes les méthodes.", "",
              "Les autres désaccords restent inclus : source « ASB » possiblement fautive, suffixe Ride by Wire tronqué et « ABS déconnectable sur demande ». Ils interrogent respectivement la correction des fautes source, la preuve de présence et la différence entre désactivation et option d’achat.", "",
              "## Confusions sur les 60 références", "",
              "Chaque ligne est la référence, chaque colonne la décision. Les zéros ne sont pas omis.", ""]
    for name, result in all_metrics["Strict — 60 références"].items():
        lines += [f"### {name}", "", "| Référence \\ décision | Série | Option | Absence explicite | Inconnu |", "|---|---:|---:|---:|---:|"]
        for truth in LABELS:
            lines.append("| " + truth + " | " + " | ".join(str(result["confusion"][truth][guess]) for guess in LABELS) + " |")
        lines += ["", "| Classe | Effectif | Précision | Rappel | F1 |", "|---|---:|---:|---:|---:|"]
        for label, values in result["details"].items():
            lines.append(f"| {label} | {values['support']} | {percent(values['precision'])} | {percent(values['recall'])} | {values['f1']:.3f} |")
        lines.append("")
    silver = [case for case in cases if case["expected"]["status"] is not None]
    lines += ["## Ensemble silver : descriptif, pas mesure de vérité", "",
              f"{len(silver)} décisions disposent d’une référence produite par règles ; {len(cases)-len(silver)} restent à examiner. Les références silver sont issues des mêmes formulations et hypothèses de section : leur concordance mesure la reproduction de cette politique, pas la précision sur de nouvelles motos.", "",
              "| Méthode | Concordance silver par fiche |",
              "|---|---:|"]
    for name, values in predictions.items():
        agreed = sum(values[c["id"]] == c["expected"]["status"] for c in silver)
        lines.append(f"| {name} | {agreed}/{len(silver)} ({percent(agreed/len(silver))}) |")
    stage_instances = Counter(row["stage"] for row in cascade.values())
    stage_unique = Counter({row["input_hash"]: row["stage"] for row in cascade.values()}.values())
    jev_cost, jev_missing = cost(row["raw"] for row in jev.values())
    lines += ["", "## Appels, délais et coût", "",
              "| Étape de la cascade | Entrées distinctes | Décisions de fiches |", "|---|---:|---:|"]
    for stage in ["code_no_mention", "jev", "mistral_fallback"]:
        lines.append(f"| {stage} | {stage_unique[stage]} | {stage_instances[stage]} |")
    lines += ["", f"Le benchmark a réellement obtenu **{len(jev)} décisions API Jev et {len(mistral)} décisions Mistral locales distinctes** pour comparer les méthodes sur le même lot. La cascade réutilise ces résultats : ses seuls cas de repli représentent {stage_unique['mistral_fallback']} entrées distinctes et {stage_instances['mistral_fallback']} fiches. Ce n’est pas une mesure d’un nouveau traitement API de la cascade.", "",
              f"Taux de repli local : **{stage_unique['mistral_fallback']}/{len(jev)} ({percent(stage_unique['mistral_fallback']/len(jev))})** sur toutes les entrées, et **{stage_unique['mistral_fallback']}/{len(mention_inputs)} ({percent(stage_unique['mistral_fallback']/len(mention_inputs))})** sur les seules entrées avec mention d’équipement. Les {len(control_inputs)} entrées distinctes sans mention sont traitables en code ; leur économie ne doit pas être attribuée à Jev.", "",
              f"Coût Jev de classification rapporté par l’API : **{jev_cost:.6f} USD** ({jev_missing} coût(s) absent(s)). Les appels de routage et de validation de passages sont comptés séparément ci-dessous. Le calcul local n’a pas de facture API mesurée ; consommation électrique et coût matériel ne sont pas évalués.", "",
              "| Classification | Médiane d’un appel | P95 | Somme des durées d’appels |", "|---|---:|---:|---:|"]
    for name, rows in [("Jev", list(jev.values())), ("Mistral", list(mistral.values()))]:
        median, tail, total = latency(rows)
        lines.append(f"| {name} | {median:.3f} s | {tail:.3f} s | {total:.1f} s |")
    lines += ["", "Jev a été appelé avec quatre requêtes concurrentes ; Mistral séquentiellement. La somme des durées n’est donc pas une durée murale comparable. Chargements froids, ordre des appels et reprises depuis cache sont conservés dans les sorties, sans répétitions permettant d’estimer la variabilité.", "",
              "## Questions : boucle actuelle et pipeline hybride", "",
              f"{len(queries)} questions exécutées sur les mêmes fiches figées. La boucle actuelle est son vrai agent Ollama avec un adaptateur SQLite isolé conservant ses arguments d’outils ; ce n’est pas une mesure sur le PostgreSQL de production. Les fiches détaillées de l’adaptateur transmettent les labels source et les sections, et peuvent être plus volumineuses que les fiches de production. Pour les listes, la projection limitée aux mesures de l’outil original est appliquée. Les filtres numériques/catégories non normalisés dans ce snapshot sont exclus du test. Le pipeline hybride répond en preuves structurées pour les cas simples et utilise Mistral pour les synthèses.", "",
              "| Méthode | Médiane backend | P95 backend | Appels génératifs locaux | Appels Jev |", "|---|---:|---:|---:|---:|"]
    med, tail, _ = latency(list(legacy.values()))
    legacy_calls = sum(len(row.get("http_calls", [])) for row in legacy.values())
    lines.append(f"| Boucle actuelle | {med:.3f} s | {tail:.3f} s | {legacy_calls} | 0 |")
    med, tail, _ = latency(list(hybrid.values()))
    gate_raws = [row["answer"]["gate_raw"] for row in hybrid.values() if isinstance(row.get("answer"), dict) and row["answer"].get("gate_raw")]
    lines.append(f"| Hybride | {med:.3f} s | {tail:.3f} s | {sum(row['llm_calls'] for row in hybrid.values())} | {len(hybrid)+len(gate_raws)} |")
    query_cost, query_missing = cost([*(row["routing_raw"] for row in hybrid.values()), *gate_raws])
    route_correct = sum(hybrid[q["id"]]["route"] == q["expected_route"] for q in queries)
    lines += ["", f"Routage conforme : **{route_correct}/{len(queries)}**. Coût API de routage et validation de passages : **{query_cost:.6f} USD**, avec {query_missing} coût(s) absent(s). Les références de routes ne sont pas fournies aux modèles.", "",
              "Les deux parcours reçoivent les mêmes questions avec millésime explicite. La boucle actuelle utilise son contexte habituel de 16 384 tokens ; les synthèses hybrides utilisent 4 096 tokens et un plafond de 400 tokens de sortie. Ces paramètres et les réponses structurées plus courtes contribuent aux différences de durée.", "",
              "Les durées backend hybrides utilisent des vecteurs de questions préparés. Elles excluent leur encodage. Pour les seules branches BGE, l’encodage local chaud mesuré séparément doit être ajouté ; les branches SQL n’en ont pas besoin.", ""]
    if (out / "queries-bare-year-v1.json").exists():
        lines += ["Une première série avec années isolées a déclenché le refus prévu par l’extracteur prudent de la boucle actuelle. Elle est conservée dans `queries-bare-year-v1.json` et `legacy-bare-year-regression.json`, hors de cette comparaison. La série finale précise le millésime pour les deux parcours ; cette correction ne change pas les références de classification. Les deux parcours partagent désormais l’extracteur prudent d’années de production ; la résolution hybride des noms reste un appariement exact, pas une capacité démontrée de Jev.", ""]
    profile_by_id = {row["id"]: row["seconds"] for row in profile["results"]}
    bge_rows = [row for row in hybrid.values() if isinstance(row.get("answer"), dict) and row["answer"].get("path") == "bge_jev_evidence"]
    if bge_rows:
        adjusted = [row["seconds"] + profile_by_id[row["id"]] for row in bge_rows]
        lines += [f"Branches BGE : {len(bge_rows)} questions ; médiane backend + encodage chaud mesuré séparément **{statistics.median(adjusted):.3f} s**. Il s’agit d’une addition diagnostique, pas d’une nouvelle mesure de bout en bout.", ""]
    lines += ["| Question | Route attendue | Route hybride | Preuve cible retrouvée dans l’hybride |", "|---|---|---|---|"]
    for query in queries:
        answer = hybrid[query["id"]]["answer"]
        proof = "non évaluée indépendamment"
        if query["expected_route"] == "passage":
            passages = answer.get("passages", []) if isinstance(answer, dict) else []
            matched = any(p.get("object_id") in query["expected_object_ids"] and p.get("section") == query["expected_section"] for p in passages)
            proof = "section cible présente" if matched else "section cible absente"
            if not matched and isinstance(answer, dict) and answer.get("fallback"):
                proof = "aucun passage retenu ; synthèse de repli à auditer"
        lines.append(f"| {query['id']} | {query['expected_route']} | {hybrid[query['id']]['route']} | {proof} |")
    lines += ["", "La présence de la section cible ne valide pas chaque valeur ou phrase d’une réponse. Une synthèse après rejet de tous les candidats doit être auditée séparément : le repli ne démontre pas la réussite de la recherche. Les listes d’ABS sont construites avec les décisions de la cascade : leur exhaustivité SQL ne doit pas être présentée comme une exactitude indépendante de leurs équipements. Les noms complets et années explicites facilitent la résolution d’identité ; les erreurs de saisie, noms courts, marchés et variantes ambiguës restent hors de ce test.", "",
              "## Audit des réponses : erreurs et utilité de Mistral", ""]
    audit = read(out / "query-answer-audit.json")
    if audit['status'] != 'complete' or len(audit['legacy_audits']) != len(queries) or len(audit['hybrid_audits']) != len(queries):
        raise IncompleteBenchmark('Source-only query audit is incomplete')
    for filename, field in [('dataset.json','dataset_file_sha256'),('queries.json','queries_file_sha256')]:
        if audit[field] != hashlib.sha256((out / filename).read_bytes()).hexdigest():
            raise IncompleteBenchmark('Query audit refers to a different snapshot')
    lines += ["Un agent a comparé les 48 réponses aux textes et URLs du snapshot, sans appel à un modèle de notation. Cette revue établit la conformité aux extraits recueillis, pas la vérité constructeur. L’audit détaillé est conservé dans `query-answer-audit.json`.", "",
              "- **16 questions factuelles :** valeurs et sources conformes dans les deux parcours. L’hybride répond directement dans 15 cas et récupère le dernier avec Mistral après abstention de Jev.",
              "- **Listes par marque :** la boucle actuelle affiche 10 Honda sur 26 et 10 BMW sur 15 sans annoncer que les listes sont partielles. La liste Honda omet les URLs demandées. SQL rend les 26 et 15 identités avec leurs sources.",
              "- **Listes ABS :** la boucle actuelle explique que le filtre est indisponible, sans inventer de réponse. L’hybride rend 2, 9, 19 et 39 fiches pour 2000, 2004, 2008 et 2010 ; leurs mentions d’ABS et URLs sont présentes. Cela ne valide pas un équipement de série pour toutes les variantes.",
              "- **Deux comparaisons :** la boucle actuelle produit seulement un début d’en-tête avec des espaces, sans valeurs ni sources. L’hybride recopie des valeurs documentées mais ses deux réponses sont coupées : Ollama indique `done_reason=length`, 400 tokens. La seconde suppose aussi une meilleure stabilité à partir du débattement seul ; cette conséquence n’est pas étayée par les fiches.", "",
              "Les statuts ABS restent un point de données à résoudre. Le repli Mistral interprète « ABS déconnectable sur demande » comme une option alors que la référence figée le classe en série. Les listes 2008 et 2010 perdent ainsi une fiche chacune par rapport à la politique silver. Cette divergence ne prouve pas l’équipement réel. Pour la Mana 850 NA et la Shiver 750 GT 2010, l’équipement annonce ABS tandis que les tarifs distinguent une version avec ABS : la portée de variante reste ambiguë malgré la concordance silver.", "",
              "**Une collaboration BGE–Jev observée :** pour la suspension avant de la R6, BGE classe le train arrière en premier et le train avant en deuxième. Jev rejette l’arrière (score 0,20), conserve l’avant (0,86) et fournit la preuve correcte sans Mistral.", "",
              "**Un repli Mistral utile :** pour la transmission de la FZ1, BGE ne propose pas le bon passage dans ses trois candidats. Jev les rejette tous ; Mistral lit la fiche complète sélectionnée par SQL et répond « boîte à 6 rapports, secondaire par chaîne » avec la bonne URL, en 17,8 s. Ce repli réussit, contrairement aux deux synthèses longues encore incomplètes.", "",
              "Le seuil Jev ne garantit pas que le repli soit meilleur : sur le classement d’équipements, la cascade corrige l’inférence non étayée du texte « ASB » mais dégrade le cas « ABS déconnectable sur demande ». Elle conserve 54/60 accords, comme Mistral et Jev seuls. Les quatre désaccords sur les options groupées restent des conflits de politique de portée, inclus dans le score strict.", "",
              "## Recherche BGE-M3", ""]
    retrieval = read(out / "index.retrieval-evaluation.json")
    embedding = read(out / "index.embeddings.json")
    lines += [f"{embedding['embedded_passages']:,} passages indexés, {embedding['unique_texts']:,} textes distincts, dimension {embedding['dimensions']}, calcul CPU local ; préparation mesurée {embedding['seconds']:.1f} s et {embedding['truncated_unique_texts']} texte tronqué.".replace(",", " "), "",
              "| Recherche — 60 questions de sections source | Rappel @1 | Rappel @3 |", "|---|---:|---:|"]
    for name, result in retrieval["summary"].items():
        lines.append(f"| {name} | {percent(result['recall_at_1'])} | {percent(result['recall_at_3'])} |")
    lines += ["", "Le filtre exact modèle–millésime est fourni avant la recherche filtrée : son identité correcte est imposée par SQL, pas démontrée par BGE. La recherche sans filtre n’indexe pas les noms dans les textes des sections ; elle sert à illustrer le besoin de portée et ne mesure pas un moteur complet de résolution d’identité.", "",
              "## Conclusions autorisées et limites", "",
              "Ce lot permet d’observer les accords, erreurs et besoins de repli sur des fiches réelles ; il ne prouve pas une précision générale de Jev sur toutes les motos. Le score test repose sur 37 références sélectionnées et seulement une absence explicite. Les 880 décisions sont corrélées et les références silver ne remplacent pas des annotations indépendantes.", "",
              "Les requêtes SQL apportent une sélection exhaustive dans le catalogue figé, sous réserve de la qualité des champs. BGE apporte les passages techniques dans la bonne portée. Jev apporte la classification et le routage ; Mistral fournit les synthèses et les replis. Un gain de vitesse sur une réponse structurée ne garantit pas une meilleure réponse conversationnelle.", "",
              "Avant généralisation : fixer la politique des listes d’équipements, conserver l’abstention sur les sources ambiguës, ajouter des annotations humaines indépendantes et tester des questions non templatisées. Les probabilités Jev et seuils de la cascade n’ont pas été calibrés sur une population représentative.", "",
              "## Artefacts reproductibles", "",
              "- `data/technical/hybrid-poc/benchmark-protocol.json` : modèles, consignes, paramètres et empreintes.",
              "- `dataset.json`, `cases.json`, `gold_annotations.json`, `annotation_protocol.json` : lot et références figés.",
              "- `jev-classifications.json`, `mistral-classifications.json`, `cascade-decisions.json` : sorties et coûts par entrée.",
              "- `queries.json`, `legacy-query-results.json`, `hybrid-query-results.json` : questions et résultats des deux parcours.",
              "- `index.retrieval-evaluation.json`, `index.embeddings.json`, `query-encoding-profile.json` : preuves de recherche et encodage.", "",
              f"Rapport généré le {datetime.now(timezone.utc).isoformat()} ; aucune référence n’a été réétiquetée.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/technical/hybrid-poc")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/hybrid-poc-results.md")
    args = parser.parse_args()
    try:
        report = render(args.data)
    except (IncompleteBenchmark, KeyError, TypeError) as exc:
        print(f"Report not generated: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"Generated {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
