"""Observed chat failures, with providers stubbed and the real routing/rendering.

Live Gradio re-evaluation is separate; these deterministic checks do not measure
model quality. The numeric examples deliberately differ from the benchmark.
"""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from bikefinder_rag.agent import jev_router as router, loop
from bikefinder_rag.catalog import aggregates


def fiche(model, year=2022, power=48, displacement=500):
    return {"id": f"{model}-{year}", "brand": "Honda", "model": model,
            "year": year, "source_url": f"https://source.test/{model}/{year}",
            "source_sha256": "source", "record": {"spec_rows": [
                {"section": "Moteur", "label": "", "value": f"{power} ch"},
                {"section": "Moteur", "label": "", "value": f"{displacement} cc"}]}}


@pytest.fixture
def chat(monkeypatch):
    monkeypatch.setenv("BIKEFINDER_JEV_ROUTER", "1")
    monkeypatch.setenv("BIKEFINDER_JEV_RAG", "0")
    catalog = [fiche("Example", y, power=p) for y, p in [(2020, 45), (2021, 48), (2022, 51)]]
    monkeypatch.setattr(router, "_identities", {"groups": [
        {"brand": "Honda", "model": "Example", "years": {2020, 2021, 2022},
         "aliases": router.aliases("Honda", "Example")}], "brands": ["Honda"]})

    def classify(q, models, brands, numbers, previous=None):
        choices = {"identity_binding": "recognized" if models else "none",
                   "operation": "details" if models else "filter", "scope": "supported",
                   "equipment": "none", "status": "standard",
                   **{"field_" + key: "no" for key in router.TOPICS}}
        for n in numbers:
            choices[n["id"] + "_field"] = n["role"] if n["role"] in router.FIELDS else "ignore"
            choices[n["id"] + "_op"] = n["explicit_operator"] or "ignore"
        return {"answers": {k: {"choice": v, "confidence": .99} for k, v in choices.items()}}, 0, False

    monkeypatch.setattr(router, "classify", classify)
    rows = lambda conn, sql, params: [deepcopy(r) for r in catalog
                        if not any(isinstance(p, int) for p in params) or r["year"] in params]
    monkeypatch.setattr(router, "_rows", rows)
    monkeypatch.setattr(aggregates, "_rows", rows)
    monkeypatch.setattr(aggregates, "filtered", lambda *args, **kwargs: deepcopy(catalog))
    monkeypatch.setattr(router, "render_list", lambda *args: "ordinary list")
    monkeypatch.setattr(loop, "_run_agent_ollama", Mock(side_effect=AssertionError("Unexpected writer")))
    return catalog


@pytest.mark.parametrize("value", ["≈ 62 ch à 9 000 tr/min", "environ 63 ch", "~ 64 cv"])
def test_source_power_keeps_approximation_instead_of_claiming_missing(value):
    row = {"section": "Moteur", "label": "", "value": value}
    assert router.selected_rows({"spec_rows": [row]}, "power_ch") == [row]


def test_suspension_includes_electronic_adjustment_from_equipment_section():
    row = {"section": "Équipement de série", "label": "Suspensions",
           "value": "Réglage électronique des suspensions"}
    assert router.selected_rows({"spec_rows": [row]}, "suspension") == [row]


def test_maximum_is_an_aggregation_not_a_truncated_list(chat, monkeypatch):
    render = Mock(return_value="ordinary list")
    monkeypatch.setattr(router, "render_list", render)
    result = router.route_question(None, "Quelle cylindrée maximale chez Honda en 2022 ?")
    assert result["plan"].get("aggregate") == {"operation": "max", "fields": ["displacement_ccm"]}
    render.assert_not_called()


def test_mean_uses_every_explicit_year_and_source(chat):
    result = router.route_question(None, "Puissance moyenne de la Honda Example sur les millésimes 2020, 2021 et 2022.")
    assert result["route"] == "aggregate"
    assert "48 ch" in result["answer"] and "45" in result["answer"] and "51" in result["answer"]
    assert {m["year"] for m in result["plan"]["models"]} == {2020, 2021, 2022}


def test_year_answer_completes_pending_model_question(chat):
    first, history = loop.run_agent(None, None, "Quelle puissance pour la Honda Example ?", [], provider="ollama")
    assert "millésime" in first
    answer, history = loop.run_agent(None, None, "Celle de 2022.", history, provider="ollama")
    assert "51 ch" in answer and "2022" in answer
    assert history[-1]["_catalog_plan"]["models"][0]["model"] == "Example"


def test_pagination_keeps_scope_and_advances_offset(chat, monkeypatch):
    monkeypatch.setattr(router, "render_list", lambda conn, plan: "page")
    first = router.route_question(None, "Montre les cinq premières fiches Honda de 2022.")
    result = router.route_question(None, "Les cinq suivantes, avec les mêmes critères.",
                                  [{"role": "assistant", "_catalog_plan": first["plan"]}])
    assert result["plan"]["identity"] == {"brand": "Honda", "year": 2022}
    assert result["plan"]["limit"] == 5 and result["plan"]["offset"] == 5
    assert first["plan"].get("offset", 0) == 0


def test_mean_without_population_keeps_known_model_and_year(chat):
    _, history = loop.run_agent(None, None, "Puissance de la Honda Example de 2020 ?", [], provider="ollama")
    answer, history = loop.run_agent(None, None, "Donne la puissance moyenne de la Honda Example.", history, provider="ollama")
    assert "2020" in answer and "moyenne" in answer.lower()
    assert "population" in answer.lower() or "quels millésimes" in answer.lower()


def test_inclusive_bounds_accept_french_prepositions():
    numbers = router.literals("Selle au plus à 800 mm et poids tous pleins faits au plus de 200 kg en 2022", [])
    assert [(n["role"], n["explicit_operator"]) for n in numbers[:2]] == [
        ("seat_height_mm", "<="), ("weight_wet_kg", "<=")]


def test_manufacturer_identity_does_not_require_year(chat):
    result = router.route_question(None, "Quel constructeur fabrique Example ?")
    assert result["route"] == "identity" and "Honda" in result["answer"]
    assert "millésime souhaites" not in result["answer"]


def test_all_extremum_ties_beyond_first_page_and_missing_count(monkeypatch):
    rows = [fiche(f"Bike{i}", displacement=500) for i in range(21)]
    rows += [fiche("LastWinner", displacement=1234), fiche("OtherWinner", displacement=1234)]
    unknown = fiche("Unknown"); unknown["record"]["spec_rows"] = []
    rows.append(unknown)
    fetch = Mock(return_value=rows)
    monkeypatch.setattr(aggregates, "filtered", fetch)
    plan = {"models": [], "identity": {"brand": "Honda", "year": 2022}, "conditions": [],
            "aggregate": {"operation": "max", "fields": ["displacement_ccm"]}}
    answer = aggregates.render_aggregate(None, plan)
    assert "1234 cc" in answer and "2 fiche(s) ex æquo" in answer
    assert "LastWinner" in answer and "OtherWinner" in answer and "23/24" in answer
    assert fetch.call_args.kwargs["limit"] > 24


def test_means_keep_weight_types_and_missing_denominators_separate(monkeypatch):
    rows = [fiche("A"), fiche("B"), fiche("C")]
    for row, dry, wet in zip(rows, [100, 120, None], [None, 140, 160]):
        row["record"]["spec_rows"] = [
            {"section": "Châssis", "label": label, "value": f"{value} kg"}
            for label, value in [("Poids à sec", dry), ("Poids tous pleins faits", wet)] if value is not None]
    monkeypatch.setattr(aggregates, "filtered", lambda *a, **kw: rows)
    plan = {"identity": {"year": 2022}, "aggregate": {"operation": "mean", "fields": ["weight_dry_kg", "weight_wet_kg"]}}
    answer = aggregates.render_aggregate(None, plan)
    assert "110 kg" in answer and "150 kg" in answer and answer.count("2/3") == 2


def test_average_price_uses_only_documented_france_base_prices(monkeypatch):
    rows = [fiche('A'), fiche('B'), fiche('Unknown')]
    rows[0]['record']['spec_rows'] = [
        {'section': 'Tarifs', 'label': 'France — Version de base', 'value': '8 000 € *'},
        {'section': 'Tarifs', 'label': 'France — Version ABS', 'value': '10 000 €'},
        {'section': 'Tarifs', 'label': 'Belgique — Version de base', 'value': '7 000 €'}]
    rows[1]['record']['spec_rows'] = [{'section': 'Tarifs', 'label': 'France — Version de base', 'value': '9 000 €'}]
    rows[2]['record']['spec_rows'] = [{'section': 'Tarifs', 'label': 'France — Version de base', 'value': 'non communiqué'}]
    monkeypatch.setattr(aggregates, 'filtered', lambda *a, **kw: rows)
    answer = aggregates.render_aggregate(None, {'identity': {'year': 2022},
        'aggregate': {'operation': 'mean', 'fields': ['price_eur']}})
    assert '8500 €' in answer and '2/3' in answer and 'Prix France de base' in answer
    assert '10 000' not in answer and '7 000' not in answer


@pytest.mark.parametrize('question', ["Prix moyen d’occasion des Honda de 2022 ?", 'Prix moyen actuel des Honda de 2022 ?'])
def test_average_current_or_used_price_never_becomes_catalogue_mean(chat, question):
    result = router.route_question(None, question)
    assert result['route'] == 'clarification' and 'catalogue' in result['answer']


def test_approximate_value_is_readable_but_not_an_exact_numeric_projection():
    from bikefinder_rag.catalog.measures import project
    row = {"section": "Moteur", "label": "", "value": "≈ 62 ch"}
    assert router.selected_rows({"spec_rows": [row]}, "power_ch") == [row]
    assert project({"spec_rows": [row]})[0]["power_ch"] is None


def test_numeric_threshold_is_not_reinterpreted_as_aggregation():
    assert aggregates.requested_aggregate("Honda 2022 : puissance minimum de 100 ch") is None
    assert aggregates.requested_aggregate("Selle au maximum à 800 mm") is None


@pytest.mark.parametrize('word', ['moyen', 'MOYEN', 'moyens', 'moyenne', 'moyennes'])
def test_average_adjective_keeps_all_french_inflections(word):
    assert aggregates.requested_aggregate(f'Poids {word} à sec et poids tous pleins faits') == {
        'operation': 'mean', 'fields': ['weight_dry_kg', 'weight_wet_kg']}


def test_next_page_without_valid_previous_scope_is_clarified(chat):
    result = router.route_question(None, "Les cinq suivantes.", [
        {"role": "assistant", "_catalog_plan": {"identity": {"brand": "Honda"}, "operation": "filter"}},
        {"role": "assistant", "_catalog_plan": None}])
    assert result["route"] == "clarification" and result["plan"] is None


def test_ambiguous_average_can_be_completed_with_years(chat):
    _, history = loop.run_agent(None, None, "Puissance moyenne de Honda Example ?", [], provider="ollama")
    answer, history = loop.run_agent(None, None, "2020, 2021 et 2022.", history, provider="ollama")
    assert "48 ch" in answer and history[-1]["_catalog_route"] == "aggregate"


def test_unknown_requested_year_is_not_substituted_in_mean(chat):
    result = router.route_question(None, "Puissance moyenne Honda Example sur les millésimes 1990 et 2022")
    assert "incomplète" in result["answer"] and "1990" in result["answer"]
    assert "51 ch" in result["answer"] and "48 ch" not in result["answer"]


def test_next_page_sql_offset_and_total_have_same_scope(monkeypatch):
    from bikefinder_rag.catalog import enriched, measures
    calls = []
    def rows(conn, sql, params):
        calls.append((sql, params))
        return [{"count": 12}] if "count(*)" in sql else []
    monkeypatch.setattr(enriched, "_rows", rows)
    conditions = [{"field": "power_ch", "op": ">", "value": 80}]
    measures.filtered(None, conditions, {"brand": "Honda", "year": 2022}, count=True)
    measures.filtered(None, conditions, {"brand": "Honda", "year": 2022}, offset=5, limit=5)
    assert calls[0][1] == calls[1][1][:-2]
    assert "OFFSET %s" in calls[1][0] and calls[1][1][-2:] == [5, 5]


def test_year_clarification_removes_only_other_generations_of_same_mention(chat, monkeypatch):
    names = [('Example Sport 500', {2020, 2021, 2022}), ('Nouvelle Example Sport 500', {2026})]
    monkeypatch.setattr(router, '_identities', {'brands': ['Honda'], 'groups': [
        {'brand': 'Honda', 'model': name, 'years': years, 'aliases': router.aliases('Honda', name)}
        for name, years in names]})
    models = [{'brand': 'Honda', 'model': name} for name, _ in names]
    monkeypatch.setattr(router, 'entities', lambda conn, q: (deepcopy(models), ['Honda']) if 'Example' in q else ([], []))
    for row in chat:
        row['model'] = 'Example Sport 500'
    _, history = loop.run_agent(None, None, 'Quelle puissance pour la Honda Example Sport 500 ?', [], provider='ollama')
    answer, history = loop.run_agent(None, None, 'Celle de 2022.', history, provider='ollama')
    assert history[-1]['_catalog_plan']['models'] == [{'brand': 'Honda', 'model': 'Example Sport 500'}]
    assert '51 ch' in answer


def test_unbound_classifier_aggregate_never_crashes_or_invents_field(chat, monkeypatch):
    original = router.classify
    def misclassified(*args):
        raw, calls, cached = original(*args)
        raw['answers']['operation']['choice'] = 'aggregate'
        return raw, calls, cached
    monkeypatch.setattr(router, 'classify', misclassified)
    result = router.route_question(None, 'Une statistique sur les Honda de 2022 ?')
    assert result['route'] == 'clarification' and result['answer']
