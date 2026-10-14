"""Offline, revision-pinned evidence reranking for the small-model experiment."""
from functools import lru_cache

MODEL = "BAAI/bge-reranker-v2-m3"
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


@lru_cache(maxsize=1)
def model():
    import torch
    from sentence_transformers import CrossEncoder
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    result = CrossEncoder(MODEL, revision=REVISION, local_files_only=True, device=device, max_length=512)
    if device == "mps":
        result.model.half()
    return result


def rank(query, texts):
    return [float(v) for v in model().predict([(query, text) for text in texts], show_progress_bar=False, batch_size=16)]
