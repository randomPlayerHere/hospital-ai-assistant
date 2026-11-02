# Evaluation: pgvector vs TF-IDF for Hospital FAQ Search

*Date: 2026-11-02*  
*Status: Architecture Evaluation & Implementation Blueprint*

---

## 1. Context & Motivation

The Hospital AI Assistant currently implements a lightweight in-memory TF-IDF keyword retrieval engine (`backend/app/ai/faq.py`) that chunks markdown documents under `knowledge_base/*.md` (visiting hours, parking, billing, department locations, patient rights) and passes the top-$k$ relevant passages to the LLM context.

Item from `to_Do.md` Section F:
> *"Try `pgvector` for FAQ search, which currently uses Postgres full-text search."*

This document provides a comparative engineering and clinical evaluation of `pgvector` vector similarity search versus lexical search, detailing trade-offs, operational costs, and an implementation blueprint.

---

## 2. Comparative Analysis

| Dimension | Current Lexical Retrieval (TF-IDF / FTS) | Semantic Vector Search (`pgvector`) |
|---|---|---|
| **Retrieval Mechanism** | Token frequency & inverse document frequency with stemming. | High-dimensional embedding distance (cosine similarity). |
| **Retrieval Latency** | **< 1 ms** (pure in-memory index loaded on startup). | **~150–300 ms** (embedding API call + vector DB index scan). |
| **Operational Dependencies** | **Zero.** Standard Python library (`re`, `math`) + standard Postgres. | Requires `pgvector/pgvector` Docker image, DB extension `CREATE EXTENSION vector`, and external embedding API key. |
| **Cost per Query** | **$0.00** | ~$0.00002 per search (embedding API generation). |
| **Offline Resilience** | **100% resilient.** Operates locally even during network outages. | Fails or degrades if embedding provider is unreachable. |
| **Semantic Matching** | Fails on vocabulary mismatch (e.g. "Where can I leave my vehicle?" vs "Parking & Transport"). | **Excels.** Resolves synonyms, paraphrases, and multi-lingual colloquialisms. |
| **Precision on Hospital Codes** | High precision on specific clinic names, room numbers, and phone extensions. | Risk of fuzzy hallucinated proximity between distinct departments. |

---

## 3. Recommended Architecture: Hybrid Search

Neither pure keyword matching nor pure vector embeddings is optimal in isolation for healthcare information:
- Keyword search reliably finds exact identifiers ("Ward 4B", "Dr. Vance", "08:00").
- Vector search handles descriptive, colloquial, or indirect questions ("Can my 6-year-old come see grandma?").

### Recommended Hybrid Strategy:
1. **Stage 1 (Deterministic Fast Path):** Run the in-memory TF-IDF search. If a strong keyword match is detected (score $> 1.5$), return those excerpts immediately (< 1 ms latency, zero API cost).
2. **Stage 2 (Semantic Vector Fallback):** If keyword match confidence is weak or empty, invoke the `pgvector` cosine similarity index.

---

## 4. Implementation Blueprint for `pgvector`

When migrating production to include `pgvector`:

### 4.1 Infrastructure (`infra/docker-compose.yml`)
Switch PostgreSQL service image from `postgres:17-alpine` to `pgvector/pgvector:pg17`:
```yaml
db:
  image: pgvector/pgvector:pg17
  environment:
    POSTGRES_DB: hospital
    POSTGRES_USER: hospital_admin
    POSTGRES_PASSWORD: ${DB_PASSWORD}
```

### 4.2 Alembic Migration (`alembic/versions/0004_faq_vector.py`)
```python
"""add pgvector extension and faq embeddings table"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.create_table(
        "faq_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("file", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
    )
    # HNSW index for ultra-fast cosine similarity lookups:
    op.execute(
        "CREATE INDEX idx_faq_embeddings_hnsw ON faq_embeddings "
        "USING hnsw (embedding vector_cosine_ops);"
    )

def downgrade():
    op.drop_table("faq_embeddings")
```

### 4.3 Query Implementation (`backend/app/ai/vector_search.py`)
```python
from sqlalchemy import select
from pgvector.sqlalchemy import Vector

async def search_semantic_faq(db: AsyncSession, query_embedding: list[float], limit: int = 3):
    stmt = (
        select(FAQEmbedding)
        .order_by(FAQEmbedding.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()
```

---

## 5. Conclusion & Action

For the current deployment scale (knowledge base of ~10 markdown documents covering ~50 FAQ sections):
- The current in-memory TF-IDF engine provides near-instant response times and 100% offline fallback without added infrastructure complexity or operational costs.
- When the knowledge base expands beyond 500 documents or multi-lingual patient portals are introduced, enabling the `pgvector` blueprint above provides a seamless upgrade path.
