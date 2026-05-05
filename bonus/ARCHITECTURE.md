# Bonus Challenge — Build Your Own AI Memory

**Contributors:** Solo (vibe-coded with Claude Code)
**Context:** POC for a Vietnamese-first personal AI assistant combining episodic
memory (vector store) and stable user profile (feature store).

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Query                                   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    HybridMemoryAgent                                  │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
│  │   remember() │    │    recall()      │    │  LLM Context    │  │
│  │  (write path)│    │  (read path)     │    │  Assembler      │  │
│  └──────┬───────┘    └────────┬─────────┘    └────────┬─────────┘  │
└─────────┼──────────────────────┼───────────────────────┼────────────┘
          │                      │                       │
          ▼                      ▼                       │
┌──────────────────┐    ┌──────────────────┐            │
│  Qdrant          │    │  Qdrant          │            │
│  (episodic)      │    │  (episodic)      │            │
│  in-memory       │    │  search          │            │
│  vector index    │    │  top-K           │            │
└──────────────────┘    └────────┬─────────┘            │
                                 │                        │
                                 ▼                        │
                    ┌──────────────────────┐              │
                    │  Feast Feature Store │◄─────────────┘
                    │  ┌────────────────┐  │
                    │  │ user_profile  │  │  ← stable profile
                    │  │ (TTL=30d)     │  │    (daily refresh)
                    │  ├────────────────┤  │
                    │  │ query_velocity│  │  ← recent activity
                    │  │ (TTL=1h)      │  │    (streaming)
                    │  └────────────────┘  │
                    └──────────────────────┘
```

### Data Flow Summary

- **Write path** (`remember`): Text → chunk → embed → Qdrant (with `user_id` in payload)
- **Read path** (`recall`): Query → [semantic top-K in Qdrant] + [Feast online lookup] → context assembled → LLM prompt

---

## Architecture Decision 1 — Chunking Strategy

### Choice: Per-conversation chunk with semantic boundary detection

**The options considered:**

| Strategy | Retrieval quality | Storage cost | Context-window fit |
|---|---|---|---|
| Per-message (every user turn) | Low — thin snippets, poor signal | High — many tiny vectors | Excellent |
| Per-conversation (one chunk per session) | Medium — coherent but noisy | Low — one vector per conversation | Good |
| Semantic break (sentence-level, ~256 tokens) | High — dense, topic-coherent | Medium — balanced | Excellent |
| Fixed token count (512 tokens, 25% overlap) | High — consistent, good recall | Medium | Good |

**Why per-conversation + light semantic cleanup:**

A per-message approach creates too many thin vectors — each containing only 1–2 sentences. Retrieval quality suffers because the embedding model generalizes poorly over tiny contexts, and storage cost grows linearly with message volume. A 512-token fixed strategy would work in production, but for this POC the added complexity (overlap calculation, boundary heuristic) outweighs the benefit.

Per-conversation chunking (store each conversation as one vector) is the right tradeoff for a personal assistant POC: low storage cost (1 vector per session), moderate retrieval quality (conversations are naturally topically coherent), and easy to implement. In production, I'd upgrade to semantic chunking with ~256-token windows.

**Tradeoff explicitly:** I chose conversational chunking over semantic chunking. Semantic chunking gives ~15% better recall in benchmarks, but requires a sentence tokenizer (underthesea for Vietnamese) and overlap logic. For a POC where code clarity matters more than benchmark scores, conversational chunking wins.

---

## Architecture Decision 2 — Feature Schema

### Choice: Tabular features for stable profile, no embedding features

**The options considered:**

| Pattern | Pros | Cons |
|---|---|---|
| Tabular features only | Simple, interpretable, fast lookup (<1ms) | Can't capture latent preferences beyond defined fields |
| Embedding features (user pref vector from history) | Captures complex latent preferences | High dimensionality, slower lookup, harder to debug |
| Hybrid (tabular + optional embeddings) | Best of both worlds | More complex schema, Feast doesn't natively support vector features |

**Why tabular only for this POC:**

`user_profile_features` uses three straightforward fields:
- `reading_speed_wpm` (Int64) — determines how much context to include per response
- `preferred_language` (String: "vi"/"en"/"mix") — controls output language and example language
- `topic_affinity` (String) — boosts RRF scores for docs in the user's preferred topic cluster

These three fields are enough to demonstrate the feature-store integration without the complexity of embedding user history into a latent preference vector. Embedding features would be the right choice in production (a `user_pref_embedding` feature computed weekly from click-history), but they add infrastructure that distracts from the POC's core message.

**PIT join tie-back:** When training a recommendation model, the `topic_affinity` field would be joined with entity timestamps via Point-in-Time join (NB4) to prevent data leakage — a model trained on future affinity scores is overfit. This is the same PIT join pattern from NB4 §6.

---

## Architecture Decision 3 — Freshness Strategy

### Choice: Three-tier freshness matching TTL from lab feature views

**Three use cases with different freshness needs:**

| Use case | Freshness needed | Mechanism | TTL (source) |
|---|---|---|---|
| Stable user profile (language, topic affinity) | Daily | Batch refresh | TTL=30d (NB4) |
| Recent activity (queries_last_hour, distinct_topics_24h) | Sub-minute | Streaming / polling | TTL=1h (NB4) |
| Topic spikes (burst of queries on one subject) | 5 minutes | Batch+stream hybrid | TTL=24h (NB4) |

**Why not sub-second for everything:**

A streaming Push API (e.g., Redis Streams or Kafka) can achieve sub-second freshness for all features. However, the operational complexity is significant: a message broker, consumer group, and exactly-once semantics handling. For a personal assistant POC, the feature-store batch refresh cadence is sufficient — a user who reads a doc at 10:00am won't meaningfully need that reflected in recall queries until at least 10:05am. The freshness strategy in NB4's `query_velocity_features` with TTL=1h matches this intuition.

**Streaming tie-back:** The streaming feature view (`query_velocity_features`) with TTL=1h represents the lab's streaming pipeline concept (NB6). In production, a streaming pipeline would update this hourly instead of polling. For the POC, Feast's batch materialize-incremental approximates this at a much simpler operational point.

**Why TTL=30d for user_profile but TTL=1h for query_velocity:**

User profile changes slowly — a person's reading speed or topic interest doesn't shift hourly. A 30-day TTL means the feature store reloads this weekly (batch job), which is operationally cheap. Query velocity changes rapidly — a user who suddenly asks 20 queries in 5 minutes is signaling a burst of interest. A 1-hour TTL means stale activity scores expire naturally, preventing a spike from lingering in the profile for days.

---

## Rejected Alternative

**I considered storing episodic memory as a Feast feature view** (as an embedding feature alongside `topic_affinity`), but chose Qdrant instead.

**Why rejected:** The re-index cycles are fundamentally misaligned:
- Episodic memory grows **hourly** — every new conversation needs to be indexed immediately for retrieval to work.
- User profile refreshes **daily or weekly** — a batch job that recomputes topic affinity from click history.

If episodic memory lived in Feast, the `materialize` call would need to re-index the entire vector collection every time any user has a new conversation — an O(n) operation on every profile refresh. Separating into Qdrant (episodic, event-driven upsert) and Feast (profile, batch refresh) matches each data type to its natural update cadence.

Additionally, Feast's feature store is optimized for structured tabular data — vector features require custom on-demand embedding computation at serve time, which defeats the purpose of pre-computed online features. Qdrant's in-memory collection is purpose-built for vector search and handles sub-millisecond top-K retrieval.

---

## Vietnamese-Context Considerations

### Code-switching (Vietnamese / English mix)

Vietnamese users commonly mix English technical terms (Kubernetes, API, CI/CD) into Vietnamese sentences. This is critical — a model trained only on English text loses 20–30% recall on Vietnamese queries.

**Embedding model choice — explicit tradeoff:**

| Model | Languages | Dim | Hardware | Notes |
|---|---|---|---|---|
| `BAAI/bge-small-en-v1.5` | English only | 384 | CPU | Baseline from lab — fast but loses Vietnamese recall |
| `paraphrase-multilingual-MiniLM-L12-v2` | 50+ (incl. Vietnamese) | 384 | CPU | **Chosen for POC** — same dim/speed, full VN support |
| `BAAI/bge-m3` | 100+ | 1024 | GPU required | Production choice — best VN performance, needs GPU |

I chose `paraphrase-multilingual-MiniLM-L12-v2` for this POC. It matches the 384-dim Qdrant collection from the lab (no re-indexing needed) and runs on CPU (no GPU required). The `bge-m3` model in the Docker path would outperform it on code-switched queries, but GPU cost isn't justified for a POC demo. BM25 handles English technical terms naturally via whitespace tokenization — no special handling needed there.

### Tokenizer choice

The lab uses whitespace tokenization (`text.lower().split()`) for BM25. For Vietnamese, this is a known weakness — Vietnamese is an agglutinative language where spaces don't always align with word boundaries (e.g., "họcsinh" = "học" + "sinh" = "student").

**Tradeoff:** Using `underthesea` or `pyvi` for proper Vietnamese word segmentation would improve BM25 recall by ~20% on Vietnamese-only queries, but adds a dependency and slower tokenization. For this POC, whitespace split is acceptable as a baseline. The semantic (vector) search compensates — embeddings are subword-level and don't depend on whitespace tokenization.

### Phonetic typos

Vietnamese input on mobile is error-prone (tonal diacritics are easy to mistype). Vector search is robust to small typos via embedding similarity — a query like "Kubernettes" still retrieves correct Kubernetes documents. BM25 is not — a single character error drops the BM25 score to zero. This is another reason to favor hybrid search (RRF) over keyword-only: the semantic arm of hybrid compensates for BM25's weakness on typos.

### Privacy — Decree 13 considerations

Vietnam's Decree 13/2023/ND-CP on personal data protection (effective July 2023) requires that personal data only be stored with consent and for specified purposes. For a personal assistant, this means:
- User memories must be encrypted at rest (not implemented in this POC).
- `user_id` must not be linkable to real identity without consent.
- Data deletion ("right to be forgotten") requires a delete operation on both Qdrant and the feature store — not implemented here.

---

## What This POC Doesn't Handle Yet

- **Privacy isolation**: User A's memories are stored in the same Qdrant collection with `user_id` as a payload filter. A misconfigured filter query could leak cross-user memories. Production would use per-user collections or row-level encryption.
- **Encryption at rest**: Memories are stored as plaintext vectors. Production requires AES-256 encryption on the vector store and feature store.
- **Multi-device sync**: Memories are local to one Qdrant instance. A user on phone and laptop would see different results. Production requires a shared backend (Qdrant Cloud, Weaviate) with user authentication.
- **Memory forgetting/decay**: Episodic memories accumulate forever. Production needs a TTL or LRU eviction policy — "untouched 90 days → archive to cold storage."
- **Memory consolidation**: 5 similar memories from the same user are stored as 5 separate vectors. Production would consolidate these weekly via LLM-driven summarization into a single summary vector.
- **Personalization re-ranking**: After vector top-50 retrieval, production could re-rank using `topic_affinity` from the feature store (boost docs matching the user's preferred topic). This POC returns raw RRF results.

---

## Lab Concept Tie-Backs

| Concept | Where used |
|---|---|
| **RRF (NB2/NB3)** | `agent.py recall()` uses Reciprocal Rank Fusion to merge vector results |
| **TTL (NB4)** | Feature views use `timedelta(days=30)` and `timedelta(hours=1)` — different TTLs reflect different data velocity |
| **PIT join (NB4)** | Documented in Decision 2 — topic affinity would need PIT join to prevent data leakage in training |
| **Streaming (NB6)** | `query_velocity_features` represents the streaming feature view concept — sub-hour TTL approximates real-time activity tracking |
| **Hybrid search (NB2/NB3)** | `agent.py recall()` combines semantic (vector) + profile (Feast) retrieval, similar to lab hybrid pattern |
