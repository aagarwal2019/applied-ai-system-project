"""
rag.py — TF-IDF retrieval module for the Glitchy Guesser hint system.

Loads 15 strategy tip documents from knowledge_base/strategy_tips.json,
fits a TF-IDF vectorizer once at import time, and exposes two public
functions:

    build_query(strategy, intensity, remaining_count) -> str
    retrieve(query, top_k=2) -> list[dict]

Retrieved tips are injected into the Claude prompt by ai_agent.py so hints
are grounded in domain-specific strategy guidance, not just game state data.
This is the RAG (Retrieval-Augmented Generation) component of the system.
"""

import json
import logging
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache — fitted once, reused on every retrieve() call
# ---------------------------------------------------------------------------

_DOCS: list[dict] = []
_VECTORIZER: TfidfVectorizer | None = None
_MATRIX = None  # sparse TF-IDF matrix: shape (n_docs, n_features)

_KB_PATH = Path(__file__).parent / "knowledge_base" / "strategy_tips.json"


def _load_and_fit() -> None:
    """
    Load the knowledge base and fit the TF-IDF vectorizer.

    Called once at module import time. Subsequent calls are no-ops because
    _VECTORIZER is checked first.
    """
    global _DOCS, _VECTORIZER, _MATRIX

    if _VECTORIZER is not None:
        return

    try:
        with open(_KB_PATH, encoding="utf-8") as fh:
            _DOCS = json.load(fh)
    except FileNotFoundError:
        logger.error("Knowledge base not found at %s — RAG disabled", _KB_PATH)
        return
    except json.JSONDecodeError as exc:
        logger.error("Knowledge base JSON parse error: %s — RAG disabled", exc)
        return

    # Corpus: topic + tags + content so tag vocabulary participates in scoring
    corpus = [
        f"{doc['topic']} {' '.join(doc['tags'])} {doc['content']}"
        for doc in _DOCS
    ]

    _VECTORIZER = TfidfVectorizer(
        ngram_range=(1, 2),  # unigrams + bigrams: "binary search", "Too High", etc.
        min_df=1,
        max_df=0.85,         # suppress terms appearing in >85% of docs (near-zero IDF)
        sublinear_tf=True,   # log(1+tf) dampens high-frequency terms
    )
    _MATRIX = _VECTORIZER.fit_transform(corpus)
    logger.info("RAG: TF-IDF fitted on %d documents from %s", len(_DOCS), _KB_PATH)


_load_and_fit()  # Run at import time


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_query(strategy: str, intensity: str, remaining_count: int) -> str:
    """
    Build a retrieval query string from the agent tool outputs.

    Maps the discrete labels returned by evaluate_strategy() and
    get_hint_intensity() to natural-language phrases that match the
    vocabulary in the knowledge base documents.

    Parameters
    ----------
    strategy : str
        One of: "binary_search", "semi_systematic", "random", "just_started"
    intensity : str
        One of: "gentle", "moderate", "strong"
    remaining_count : int
        Number of valid candidates remaining (from calculate_valid_range)

    Returns
    -------
    str
        A natural-language query ready for TF-IDF cosine similarity retrieval.
    """
    strategy_phrase = {
        "binary_search":   "binary search midpoint optimal convergence",
        "semi_systematic": "systematic midpoint calibrate range narrowing",
        "random":          "random guessing arbitrary inefficient pitfall",
        "just_started":    "early game exploration patience gentle strategy",
    }.get(strategy, strategy.replace("_", " "))

    intensity_phrase = {
        "gentle":   "early game patience exploration familiarise",
        "moderate": "midgame systematic calibrate remaining budget",
        "strong":   "urgent critical final attempt direct precious",
    }.get(intensity, intensity)

    if remaining_count <= 10:
        range_phrase = "small range narrow enumerate trivial"
    elif remaining_count >= 80:
        range_phrase = "large range scale magnitude vast logarithm"
    else:
        range_phrase = "range narrowing bounds constraint contiguous"

    query = f"{strategy_phrase} {intensity_phrase} {range_phrase}"
    logger.debug("RAG query: %r", query)
    return query


def retrieve(query: str, top_k: int = 2) -> list[dict]:
    """
    Return the top_k most relevant strategy tip documents for the given query.

    Uses cosine similarity between the query and the TF-IDF document matrix
    fitted at import time.

    Parameters
    ----------
    query : str
        Free-text retrieval query (typically from build_query()).
    top_k : int
        Number of documents to return. Default 2.

    Returns
    -------
    list[dict]
        Each element has: id, topic, content, score (cosine similarity 0–1).
        Ordered by descending score. Returns [] if the vectorizer is not fitted.
    """
    if _VECTORIZER is None or _MATRIX is None:
        logger.warning("RAG: vectorizer not fitted — returning empty results")
        return []

    try:
        query_vec = _VECTORIZER.transform([query])
        scores = cosine_similarity(query_vec, _MATRIX)[0]

        # argsort ascending; slice last top_k and reverse for descending order
        top_indices = np.argsort(scores)[-top_k:][::-1]

        results = []
        for idx in top_indices:
            doc = _DOCS[idx]
            results.append({
                "id":      doc["id"],
                "topic":   doc["topic"],
                "content": doc["content"],
                "score":   round(float(scores[idx]), 4),
            })

        logger.info(
            "RAG: retrieved %d docs | query=%r | scores=%s",
            len(results), query[:60], [r["score"] for r in results],
        )
        return results

    except Exception as exc:
        logger.error("RAG retrieval failed: %s", exc)
        return []
