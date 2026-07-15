"""Cross-source motorcycle name matching, shared by the enrichment loaders.

External sources never write a model name the way bikez does: motoplanete
appends displacement suffixes ('YZF-R1 1000'), marketplace listings drop
prefixes ('Bandit 1250' for 'GSF 1250 Bandit'), bikez itself adds words
('Superbike 1098 R', 'Ninja ZX-10R') and our scrape split multi-word
brands (brand='MV', model='Agusta Brutale...'). Matching therefore runs
on the concatenated brand+model, tokenized, in both directions:

1. every source token appears among the row's tokens (tightest row wins:
   fewest extra tokens);
2. same, after dropping the source's displacement-suffix-looking numeric
   tokens;
3. reverse: every row token appears among the source's tokens (rows of
   at least 3 tokens; the most specific row wins).
"""

import re
from collections import defaultdict


def tokens(s: str) -> list[str]:
    """Alternating alpha/digit tokens: 'ZX-10R 1000' -> ['zx','10','r','1000'].
    Token-level (not substring) matching is what keeps '1098 R' from
    matching 'Superbike 1098 S' via the 'r' inside 'Superbike'."""
    return re.findall(r"[a-z]+|\d+", str(s).lower())


class MotorcycleMatcher:
    """Matches a source's (brand, model, year) against the motorcycles
    table. `rows` are (payload, brand, model, year) tuples — payload is
    whatever the caller wants back (id, family_id...)."""

    def __init__(self, rows):
        self._by_year: dict[int, list] = defaultdict(list)
        for payload, brand, model, year in rows:
            self._by_year[year].append((payload, set(tokens(f"{brand} {model}"))))

    def match_year(self, source_tokens: list[str], year: int) -> tuple[list, str | None]:
        """(payloads, pass name) — pass is 'forward', 'no-suffix' or
        'reverse', useful for auditing which rule produced a match."""
        for pass_name, required in (
            ("forward", source_tokens),
            ("no-suffix", [t for t in source_tokens if not (t.isdigit() and int(t) >= 50)]),
        ):
            if not required:
                continue
            best_extra, best = None, []
            for payload, row_tokens in self._by_year.get(year, []):
                if not all(t in row_tokens for t in required):
                    continue
                extra = len(row_tokens - set(required))
                if best_extra is None or extra < best_extra:
                    best_extra, best = extra, [payload]
                elif extra == best_extra:
                    best.append(payload)
            if best:
                return best, pass_name

        # Reverse direction: the source is the verbose side.
        source_set = set(source_tokens)
        best_size, best = 0, []
        for payload, row_tokens in self._by_year.get(year, []):
            if len(row_tokens) < 3 or not row_tokens <= source_set:
                continue
            if len(row_tokens) > best_size:
                best_size, best = len(row_tokens), [payload]
            elif len(row_tokens) == best_size:
                best.append(payload)
        return best, ("reverse" if best else None)

    def match(self, brand: str, model: str, year: int,
              year_offsets: tuple[int, ...] = (0, -1, 1)) -> tuple[list, int | None]:
        """(payloads, year offset used) — offsets tried in order, since
        sources disagree on launch year vs model year by one either way."""
        payloads, dy, _ = self.match_explained(brand, model, year, year_offsets)
        return payloads, dy

    def match_explained(self, brand: str, model: str, year: int,
                        year_offsets: tuple[int, ...] = (0, -1, 1)) -> tuple[list, int | None, str | None]:
        """(payloads, year offset, pass name) — the audit-friendly variant."""
        source_tokens = tokens(f"{brand} {model}")
        for dy in year_offsets:
            payloads, how = self.match_year(source_tokens, year + dy)
            if payloads:
                return payloads, dy, how
        return [], None, None
