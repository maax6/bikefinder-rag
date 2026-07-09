from pathlib import Path

from bikefinder_rag.scraper.detail_scraper import (
    _comments_from_thread,
    _thread_urls,
    parse_spec_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_spec_page_typed_fields():
    html = (FIXTURES / "xadv_spec.html").read_bytes()
    detail = parse_spec_page(html)

    assert detail.typed_fields["displacement_ccm"] == 745.0
    assert detail.typed_fields["weight_kg"] == 236.0
    assert detail.typed_fields["power_hp"] == 57.8
    assert detail.typed_fields["seat_height_mm"] == 820.0
    assert detail.discussion_url == "https://bikez.com/models/honda-x-adv-discussions.php"
    assert detail.raw_specs["Model name"] == "Honda X-Adv"


def test_thread_urls_extracted():
    html = (FIXTURES / "xadv_discussion.html").read_bytes()
    urls = _thread_urls(html)

    assert len(urls) == 2
    assert all("msg.php?str_id=" in u for u in urls)


def test_comments_from_thread():
    html = (FIXTURES / "xadv_thread.html").read_bytes()
    comments = _comments_from_thread(html)

    assert len(comments) == 1
    assert comments[0].author == "Sand"
    assert comments[0].posted_at.startswith("2020-05-15")
    assert "shock travel" in comments[0].text.lower()
