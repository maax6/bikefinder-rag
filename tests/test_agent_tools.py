from copy import deepcopy
from unittest.mock import Mock

import pytest

from bikefinder_rag.agent import tools


def test_long_review_is_bounded_without_mutating_the_ranked_result(monkeypatch):
    text = ("The brakes feel good. Maintenance is straightforward. " * 1500)[:65_536]
    reviews = [{
        "brand": "Aprilia", "model_family": "RS 125",
        "family_year_min": 1992, "family_year_max": 2024,
        "author": "owner", "posted_at": "2009-05-12",
        "source": "bikez", "lang": "en", "rating": None,
        "distance": 0.2, "rrf": 0.03, "rerank_score": 0.9,
        "comment_text": text,
    }]
    original = deepcopy(reviews)
    search = Mock(return_value=reviews)
    monkeypatch.setattr(tools, "search_reviews", search)

    results = tools.execute_tool(None, "search_reviews", {"query": "RS 125 reliability"})

    search.assert_called_once_with(None, query="RS 125 reliability")
    assert reviews == original
    assert results[0] is not reviews[0]
    assert len(results[0]["comment_text"]) <= 2000
    assert results[0]["comment_text"].endswith("…")
    assert text.startswith(results[0]["comment_text"][:-1])
    assert results[0]["text_truncated"] is True
    assert results[0]["original_text_chars"] == 65_536
    assert "partial excerpt" in results[0]["excerpt_note"].lower()
    for key, value in original[0].items():
        if key != "comment_text":
            assert results[0][key] == value


def test_long_review_stops_at_a_nearby_sentence_boundary(monkeypatch):
    first_sentence = "Une moto agréable. "
    text = first_sentence + "a" * 1700 + ". " + "Le commentaire continue " * 100
    monkeypatch.setattr(tools, "search_reviews", Mock(return_value=[{"comment_text": text}]))

    result = tools.execute_tool(None, "search_reviews", {"query": "confort"})[0]

    assert result["comment_text"] == first_sentence + "a" * 1700 + ".…"


def test_long_review_without_sentences_stops_between_words(monkeypatch):
    text = "problème " * 400
    monkeypatch.setattr(tools, "search_reviews", Mock(return_value=[{"comment_text": text}]))

    result = tools.execute_tool(None, "search_reviews", {"query": "fiabilité"})[0]

    assert len(result["comment_text"]) <= 2000
    assert result["comment_text"].endswith("problème…")
    assert text.startswith(result["comment_text"][:-1])


def test_long_review_without_whitespace_still_has_a_hard_character_cap(monkeypatch):
    monkeypatch.setattr(tools, "search_reviews", Mock(return_value=[{"comment_text": "x" * 65_536}]))

    result = tools.execute_tool(None, "search_reviews", {"query": "reliability"})[0]

    assert len(result["comment_text"]) == 2000
    assert result["comment_text"] == "x" * 1999 + "…"


@pytest.mark.parametrize("text", ["", "Un avis bref sur la moto.", "x" * 2000])
def test_short_reviews_are_unchanged(monkeypatch, text):
    reviews = [{"comment_text": text, "source": "motoplanete", "lang": "fr"}]
    monkeypatch.setattr(tools, "search_reviews", Mock(return_value=reviews))

    assert tools.execute_tool(None, "search_reviews", {"query": "avis"}) == reviews


def test_excerpting_preserves_ranking_and_existing_argument_repair_notes(monkeypatch):
    reviews = [
        {"model_family": "First", "comment_text": "premier " * 1000},
        {"model_family": "Second", "comment_text": "Un commentaire bref."},
    ]
    monkeypatch.setattr(tools, "search_reviews", Mock(return_value=reviews))

    results = tools.execute_tool(None, "search_reviews", {"model_family": "RS 125"})

    assert "notes" in results[0]
    assert [row["model_family"] for row in results[1:]] == ["First", "Second"]
    assert results[1]["text_truncated"] is True
    assert results[2] == reviews[1]


@pytest.mark.parametrize("tool_name", ["filter_specs", "get_bike_details"])
def test_other_tools_do_not_trim_fields_or_add_excerpt_metadata(monkeypatch, tool_name):
    results = [{"specs": {"Description": "x" * 65_536}, "comment_text": "x" * 3000}]
    original = deepcopy(results)
    call = Mock(return_value=results)
    monkeypatch.setattr(tools, tool_name, call)

    returned = tools.execute_tool(None, tool_name, {"model": "RS 125"} if tool_name == "get_bike_details" else {})

    assert returned == original
    assert returned is results


def test_empty_review_result_remains_empty(monkeypatch):
    monkeypatch.setattr(tools, "search_reviews", Mock(return_value=[]))

    assert tools.execute_tool(None, "search_reviews", {"query": "unknown model"}) == []
