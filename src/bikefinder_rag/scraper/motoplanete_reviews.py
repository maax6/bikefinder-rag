"""Parse the "Avis des motards" block of a motoplanete.com fiche.

Why this exists: the review corpus was 100% English (bikez.com forums)
while the product targets a French buyer — French questions had to be
translated into English before retrieval, and the eval could never tell a
retrieval defect from a translation artefact (eval_results/retrieval/
README.md, 2026-09-01). motoplanete's fiches carry owner reviews written
in French, with a /5 rating, the reviewer's model year and a post date.

What the page looks like (verified 2026-09-02 on the MT-07 700 fiche —
two generations of markup coexist, plain spans on older reviews and
schema.org/Review itemprops on newer ones, hence the loose regexes):
every review is server-rendered — the `comments-loader` Stimulus
controller only toggles visibility by series (`n0`, `n1`...), so there
is no AJAX endpoint to paginate. A block with class `reponse` is a reply
to the preceding root review. Reviews are pooled per model, not per
model-year: the 2014 and 2016 MT-07 fiches show the same 29 reviews, so
one fiche per (brand, model) is enough and the comment id deduplicates
the rest.
"""
from __future__ import annotations

import html as htmllib
import re

# Blocks are split on their opening tag rather than matched open-to-close:
# replies carry no <div id="titre_..."> and an open-to-close regex swallowed
# the next block whenever a part was missing (14 of 29 roots parsed, 2026-09-02).
_SPLIT_RE = re.compile(r'(?=<div class="comment n\d+(?: reponse)?")')
_CLASSES_RE = re.compile(r'^<div class="comment (n\d+(?: reponse)?)"')
_DATA_ID_RE = re.compile(r'class="repondre"[^>]*data-id="(\d+)"')
_TITLE_RE = re.compile(r'id="titre_(\d+)"[^>]*>(?P<title>.*?)</div>', re.S)
_NAME_RE = re.compile(r'<div class="name">(.*?)</div>', re.S)
_MODEL_YEAR_RE = re.compile(r"Mod[èe]le\s+(\d{4})")
_MIDDLE_RE = re.compile(r'<span class="middle"[^>]*>(.*?)</span>', re.S)
# Newer blocks carry schema.org markup: the rating lives in a <meta
# itemprop="ratingValue">, older ones only in the "Note : 4/5" span.
_RATING_META_RE = re.compile(r'itemprop="ratingValue"\s+content="(\d)"')
_TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"[^>]*>([^<]*)</time>')
_NOTE_RE = re.compile(r"Note\s*:\s*(\d+)\s*/\s*5")
_COUNT_RE = re.compile(r"D[ée]poser un avis\s*-\s*(\d+)\s*avis")
_TAG_RE = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    """HTML fragment -> plain text, <br> kept as line breaks, entities
    decoded, the site's backslash-escaped apostrophes (l\\'ai) unescaped."""
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = _TAG_RE.sub("", fragment)
    fragment = htmllib.unescape(fragment).replace("\\'", "'").replace('\\"', '"')
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in fragment.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def declared_review_count(page: str) -> int | None:
    """The 'Déposer un avis - N avis' header, to cross-check the parse."""
    m = _COUNT_RE.search(page)
    return int(m.group(1)) if m else None


def parse_reviews(page: str) -> list[dict]:
    """All review blocks of a fiche, root reviews and replies alike.

    Each dict: comment_id, author, title, text, rating (1-5 or None),
    posted_at (ISO date), posted_at_display, reviewer_model_year,
    is_reply, reply_to (the root's comment_id, replies only)."""
    reviews: list[dict] = []
    reply_counts: dict[str, int] = {}
    for block in _SPLIT_RE.split(page)[1:]:
        cm = _CLASSES_RE.match(block)
        if not cm:
            continue
        is_reply = "reponse" in cm.group(1)
        idm = _DATA_ID_RE.search(block)
        tm_title = _TITLE_RE.search(block)
        data_id = idm.group(1) if idm else (tm_title.group(1) if tm_title else None)
        if not data_id:
            continue
        # A reply's data-id is its conversation's id (the root's), not its
        # own — replies get a synthetic id under that root.
        if is_reply:
            reply_counts[data_id] = reply_counts.get(data_id, 0) + 1
            comment_id, reply_to = f"{data_id}-r{reply_counts[data_id]}", data_id
        else:
            comment_id, reply_to = data_id, None
        title = _text(tm_title.group("title")) if tm_title else ""
        author, model_year = "", None
        name_block = _NAME_RE.search(block)
        if name_block:
            spans = re.findall(r'<span(?![^>]*class="model")[^>]*>(.*?)</span>', name_block.group(1), re.S)
            names = [n for n in (_text(x) for x in spans) if n]  # the flag <img> span is empty once stripped
            author = names[0] if names else ""
            ym = _MODEL_YEAR_RE.search(name_block.group(1))
            model_year = int(ym.group(1)) if ym else None
        mid = _MIDDLE_RE.search(block)
        text = _text(mid.group(1)) if mid else ""
        tm = _TIME_RE.search(block)
        nm = _NOTE_RE.search(block) or _RATING_META_RE.search(block)
        entry = {
            "comment_id": comment_id,
            "author": author,
            "title": title,
            "text": text,
            "rating": int(nm.group(1)) if nm else None,
            "posted_at": tm.group(1) if tm else None,
            "posted_at_display": tm.group(2).strip() if tm else None,
            "reviewer_model_year": model_year,
            "is_reply": is_reply,
            "reply_to": reply_to,
        }
        if text:
            reviews.append(entry)
    return reviews
