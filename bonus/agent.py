"""HybridMemoryAgent — personal AI assistant with hybrid memory.

Combines:
  - Vector store (Qdrant in-memory) for episodic memory (conversations/documents)
  - Feature store (Feast) for stable user profile + recent activity

Follows lab patterns from app/search.py (Searcher class, RRF, fastembed)
and notebooks/04_feast_feature_store.py (Feast online lookup, PIT join).
"""
from __future__ import annotations

import warnings

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastembed import TextEmbedding
from feast import FeatureStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

# Suppress fastembed mean-pooling warning (affects only this model in this POC).
warnings.filterwarnings("ignore", ".*now uses mean pooling.*")

# Use multilingual model — critical for Vietnamese-first assistant.
# bge-small-en-v1.5 (English-only) loses ~20-30% recall on Vietnamese
# paraphrases. paraphrase-multilingual-MiniLM-L12-v2 supports 50+ languages
# including Vietnamese, 384-dim, CPU-friendly, same latency profile as bge-small.
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384
COLLECTION = "bonus_memory"


@dataclass
class Memory:
    text: str
    user_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HybridMemoryAgent:
    """Personal AI memory — episodic (vector) + profile (feature store)."""

    def __init__(self, feast_repo: str | Path) -> None:
        self._embedder = TextEmbedding(model_name=EMBED_MODEL)
        self._client = QdrantClient(":memory:")
        self._client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        self._feast = FeatureStore(repo_path=str(feast_repo))
        self._memories: list[Memory] = []

    def remember(self, text: str, user_id: str = "u_001") -> str:
        """Store a new episodic memory for this user.

        Chunks per conversation — each call adds one vector to the collection.
        For this POC, no chunking logic; one text = one vector.
        In production, semantic chunking (~256 tokens) would improve recall.
        """
        mem = Memory(text=text, user_id=user_id)
        self._memories.append(mem)

        vec = next(self._embedder.embed([text])).tolist()
        self._client.upsert(
            collection_name=COLLECTION,
            points=[
                PointStruct(
                    id=hash(text + str(mem.timestamp)) % 1_000_000,
                    vector=vec,
                    payload={
                        "user_id": user_id,
                        "text": text,
                        "timestamp": mem.timestamp.isoformat(),
                    },
                )
            ],
        )
        return f"Stored memory (id={len(self._memories)})"

    def recall(
        self,
        query: str,
        user_id: str = "u_001",
        top_k: int = 5,
        rrf_k: int = 60,
    ) -> str:
        """Retrieve top-K memories + user profile features → assembled context.

        Hybrid retrieval:
          1. Semantic search in Qdrant (top-50 candidates, deeper than top_k)
          2. RRF fusion: score += 1/(rrf_k + rank) per retriever
          3. Feast online lookup: user_profile + query_velocity features
          4. Assemble into LLM-ready context string

        RRF is 1-based (rank starts at 1), following lab NB2 pattern.
        """
        # Step 1: Semantic top-K from vector store
        q_vec = next(self._embedder.embed([query])).tolist()
        query_filter = (
            Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])
            if self._has_user_filter(user_id)
            else None
        )
        result = self._client.query_points(
            collection_name=COLLECTION,
            query=q_vec,
            limit=max(top_k * 5, 50),
            query_filter=query_filter,
        )

        hits = list(result.points)

        # Step 2: RRF — score(d) = sum_r 1/(rrf_k + rank_r(d)), 1-based
        rrf_scores: dict[str, float] = {}
        meta: dict[str, dict] = {}
        for rank, hit in enumerate(hits, start=1):
            doc_id = hit.payload.get("text", "")[:50]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
            meta.setdefault(doc_id, hit.payload)

        ordered = sorted(rrf_scores.items(), key=lambda kv: -kv[1])[:top_k]

        # Step 3: Feast online lookup — stable profile + recent activity
        profile_features = self._feast.get_online_features(
            features=[
                "user_profile_features:reading_speed_wpm",
                "user_profile_features:preferred_language",
                "user_profile_features:topic_affinity",
                "query_velocity_features:queries_last_hour",
                "query_velocity_features:distinct_topics_24h",
            ],
            entity_rows=[{"user_id": user_id}],
        ).to_dict()

        # Step 4: Assemble context
        ctx = []
        ctx.append("=== EPISODIC MEMORIES (vector top-K + RRF) ===")
        for doc_id, score in ordered:
            text = meta[doc_id]["text"]
            ts = meta[doc_id].get("timestamp", "unknown")
            ctx.append(f"  [score={score:.4f}] {text[:120]}... (at {ts})")
        if not ordered:
            ctx.append("  (no memories yet)")

        ctx.append("")
        ctx.append("=== USER PROFILE (Feast online lookup) ===")
        ctx.append(f"  reading_speed_wpm:    {profile_features['reading_speed_wpm'][0]}")
        ctx.append(f"  preferred_language:  {profile_features['preferred_language'][0]}")
        ctx.append(f"  topic_affinity:       {profile_features['topic_affinity'][0]}")
        ctx.append(f"  queries_last_hour:    {profile_features['queries_last_hour'][0]}")
        ctx.append(f"  distinct_topics_24h:  {profile_features['distinct_topics_24h'][0]}")

        return "\n".join(ctx)

    def _has_user_filter(self, user_id: str) -> bool:
        """Check if we have any memories for this user to filter on."""
        return any(m.user_id == user_id for m in self._memories)