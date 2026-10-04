"""One-time build step: puts the pinned embedding model in the local cache.

The only part of the submission that uses the network. run.py never downloads anything.
Run from the repo root:  uv run python submission/build_model.py
"""
from sentence_transformers import SentenceTransformer

from matcher.embedding_stage import MODEL_NAME, MODEL_REVISION

if __name__ == "__main__":
    SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION)
    print(f"{MODEL_NAME} @ {MODEL_REVISION[:8]} is in the local cache")
