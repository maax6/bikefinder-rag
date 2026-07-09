"""Local, multilingual embeddings via BGE-M3.

Chosen so queries typed in French can retrieve English-language forum
comments without a second translation step, and so nobody running this
project needs an embeddings API key — only the agent's Claude key.
"""

from functools import lru_cache

MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_DIM = 1024


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
