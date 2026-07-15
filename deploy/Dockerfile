# Hugging Face Docker Space: Postgres+pgvector and the Gradio app in one
# container. The database ships as a PGDATA tarball (deploy/pgdata.tar.gz,
# LFS) so cold boots untar and start instead of pg_restore-ing 108k
# vectors and rebuilding the HNSW index. BGE-M3 is baked into the image at
# build time so the Space never downloads it at runtime.
FROM pgvector/pgvector:pg17

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first: the default pip wheel drags the CUDA stack (~5 GB)
# into an image that will only ever see Spaces CPU hardware.
# Pinned +cpu build: skips the ~5 GB CUDA stack PyPI's torch drags in.
# --extra-index (not --index): the pytorch index doesn't host torch's own
# dependencies (typing-extensions & co), those must come from PyPI — and
# the +cpu local-version pin is what stops pip preferring PyPI's torch.
# >=2.6 required by transformers' torch.load guard (CVE-2025-32434).
# x86_64 only, like HF Spaces hardware; local test builds must use
# --platform linux/amd64 (Rosetta).
RUN python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir "torch==2.9.1+cpu" --extra-index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml ./
COPY src ./src
RUN /venv/bin/pip install --no-cache-dir -e .

ENV HF_HOME=/opt/hf-cache \
    EMBEDDER_DEVICE=cpu
RUN /venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

COPY deploy/pgdata.tar.gz /opt/pgdata.tar.gz
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# RERANKER_ENABLED=0: cross-encoder reranking is on by default in the
# codebase, but scoring ~50 (query, comment) pairs per search takes tens
# of seconds on Spaces-class CPUs — the hosted demo trades the last bit
# of cross-lingual ranking quality for responsiveness.
ENV HF_HUB_OFFLINE=1 \
    PYTHONPATH=/app/src \
    GRADIO_HOST=0.0.0.0 \
    AGENT_BACKEND=anthropic \
    POSTGRES_HOST=localhost \
    RERANKER_ENABLED=0

EXPOSE 7860
ENTRYPOINT ["/entrypoint.sh"]
