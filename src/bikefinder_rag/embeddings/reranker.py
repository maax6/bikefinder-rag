"""Optional cross-encoder reranking via bge-reranker-v2-m3.

The bi-encoder (BGE-M3) is what makes search fast — one vector per
comment, cosine over an HNSW index — but it scores query and comment
independently, and the layer-1 eval showed that hurts the hardest
cross-lingual pairs (a French query and its English equivalent didn't
always surface the same comments). A cross-encoder reads query and
comment *together*, so it ranks much more precisely — but only ~50
candidates' worth per query on CPU, which is why it reranks the dense
top-K instead of replacing it.

Same model family as the embedder (both are BGE-M3 backbones), so the
multilingual behaviour is consistent. RERANKER_ENABLED=0 turns it off
(e.g. on hardware where an extra 2 GB model hurts); the device knob is
shared with the embedder (EMBEDDER_DEVICE).
"""

import os
from functools import lru_cache

MODEL_NAME = "BAAI/bge-reranker-v2-m3"


def enabled() -> bool:
    return os.environ.get("RERANKER_ENABLED", "1") != "0"


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import CrossEncoder

    # max_length 512: forum comments run up to 65 KB and the M3 backbone
    # would happily attend over 8k tokens — seconds per pair for signal
    # that lives in the first paragraphs anyway.
    return CrossEncoder(MODEL_NAME, max_length=512,
                        device=os.environ.get("EMBEDDER_DEVICE") or None)


def rerank(query: str, texts: list[str]) -> list[float]:
    """One relevance score per text (higher = more relevant)."""
    if not texts:
        return []
    return [float(s) for s in _get_model().predict([(query, t) for t in texts],
                                                   show_progress_bar=False)]
