"""Text embeddings for plan-memory retrieval.

Two backends, selected automatically and lazily:

* **sentence-transformers** — used when the package (and its torch backend) are
  importable. Produces a semantic embedding; the model is loaded once.
* **deterministic hashing / TF-IDF-ish fallback** — pure stdlib. Hashes word
  unigrams + bigrams into a fixed-dimension vector and L2-normalises it. No
  dependencies, no downloads, fully offline and deterministic.

Both return a list of ``embedding_dim`` floats so they are interchangeable for
cosine similarity and for the pgvector column. The whole feature is optional and
non-blocking: if anything fails, the caller skips plan memory gracefully.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _module_available(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


class Embedder:
    """Lazily picks the best available embedding backend; caches it."""

    def __init__(self, settings: Any) -> None:
        self.dim = int(getattr(settings, "embedding_dim", 384))
        self.model_id = getattr(
            settings, "embedding_model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        self._lock = threading.Lock()
        self._st_model: Any | None = None
        self._tried_st = False
        self._st_importable: bool | None = None

    # -- backend selection ---------------------------------------------------

    def _st_can_import(self) -> bool:
        """Whether sentence-transformers actually IMPORTS (cached).

        ``find_spec`` only proves the package is installed; a broken transitive
        dependency (e.g. a jax/jaxlib mismatch) makes the import itself raise — so
        we probe the real import, not just its presence, to report honestly.
        """
        if self._st_importable is None:
            if not _module_available("sentence_transformers"):
                self._st_importable = False
            else:
                try:
                    import sentence_transformers  # noqa: F401
                except Exception as exc:  # not just ImportError (jax → RuntimeError)
                    logger.warning(
                        "sentence-transformers is installed but not importable "
                        "(%s); using the hashing embedder",
                        exc,
                    )
                    self._st_importable = False
                else:
                    self._st_importable = True
        return self._st_importable

    def backend(self) -> str:
        """The embedding backend that will ACTUALLY be used (not just installed)."""
        if self._tried_st:
            # We've attempted a real load — report the live result.
            return "sentence-transformers" if self._st_model is not None else "hashing"
        return "sentence-transformers" if self._st_can_import() else "hashing"

    def _load_st(self) -> Any | None:
        if self._st_model is not None or self._tried_st:
            return self._st_model
        with self._lock:
            if self._tried_st:
                return self._st_model
            self._tried_st = True
            if not self._st_can_import():
                return None
            try:  # pragma: no cover - heavy optional dep / network
                from sentence_transformers import SentenceTransformer

                self._st_model = SentenceTransformer(self.model_id)
                # Align reported dim with the model so callers/DB stay consistent.
                model_dim = self._st_model.get_sentence_embedding_dimension()
                if model_dim:
                    self.dim = int(model_dim)
            except Exception as exc:  # pragma: no cover - download/runtime errors
                logger.warning("sentence-transformers unavailable (%s); using hashing embedder", exc)
                self._st_model = None
        return self._st_model

    # -- embedding -----------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Return a unit-norm embedding for ``text`` (never raises)."""

        model = self._load_st()
        if model is not None:  # pragma: no cover - heavy optional dep
            try:
                vec = model.encode([text], normalize_embeddings=True)[0]
                return [float(x) for x in vec]
            except Exception as exc:
                logger.warning("embedding encode failed (%s); using hashing fallback", exc)
        return self._hash_embed(text)

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic hashing embedding over unigrams + bigrams."""

        dim = self.dim
        vec = [0.0] * dim
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return vec
        grams = list(tokens)
        grams += [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for gram in grams:
            h = hashlib.sha1(gram.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % dim
            sign = 1.0 if h[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec
