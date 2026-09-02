from pathlib import Path

from bikefinder_rag.scraper.motoplanete_reviews import declared_review_count, parse_reviews

FIXTURE = Path(__file__).parent / "fixtures" / "motoplanete_mt07_avis.html"


def test_parses_every_declared_review_plus_replies():
    page = FIXTURE.read_text(encoding="utf-8")
    reviews = parse_reviews(page)
    roots = [r for r in reviews if not r["is_reply"]]
    # The page header says "29 avis" while the markup holds 26 root reviews
    # and 12 replies (38 blocks, 29 distinct conversation ids): the site's
    # counter is neither, so the header is recorded as a cross-check only.
    assert declared_review_count(page) == 29
    assert len(roots) == 26
    assert len(reviews) == 38
    assert all(r["reply_to"] and r["comment_id"].startswith(r["reply_to"] + "-r") for r in reviews if r["is_reply"])
    assert len({r["comment_id"] for r in reviews}) == len(reviews)


def test_first_review_fields():
    reviews = parse_reviews(FIXTURE.read_text(encoding="utf-8"))
    first = reviews[0]
    assert first["comment_id"] == "41865"
    assert first["author"] == "Jep"
    assert first["reviewer_model_year"] == 2016
    assert first["rating"] == 4
    assert first["posted_at"] == "2025-06-02"
    assert first["text"] == "D'une fiabilité incomparable.\nPas top pour les grands."
    assert first["is_reply"] is False


def test_apostrophes_and_titles_are_clean():
    reviews = parse_reviews(FIXTURE.read_text(encoding="utf-8"))
    assert not any("\\" in r["text"] or "&#039;" in r["text"] for r in reviews)
    titles = {r["comment_id"]: r["title"] for r in reviews}
    assert titles["30741"] == "Il manque qques litres"
    assert titles["27201"] == "C'est simple: elle est presque parfaite"
    orphee = next(r for r in reviews if r["comment_id"] == "27201")
    assert orphee["author"] == "orphee" and orphee["rating"] == 5 and orphee["reviewer_model_year"] == 2014


def test_empty_page_yields_nothing():
    assert parse_reviews("<html><body>Dites nous ce que vous pensez</body></html>") == []
    assert declared_review_count("<html></html>") is None
