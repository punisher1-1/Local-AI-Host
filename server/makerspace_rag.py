"""
makerspace_rag.py — the transparent RETRIEVE + GENERATE core (the query side).

Your index_pipeline.py built the vector store. THIS is the other half: turning a
question into an answer. It is written to be *read and broken*, not hidden behind
a framework — every layer is a separate, named function you can poke at.

FLOW:  question
         → embed (same model as the index: mxbai-embed-large)      [layer: EMBED]
         → cosine search in pgvector (data_makerspace_rag)         [layer: RETRIEVE]
         → stuff retrieved text into a prompt template             [layer: PROMPT]
         → ask Ollama for the answer                               [layer: GENERATE]
         → answer + the sources it used

CLI (see every layer printed):
    python makerspace_rag.py "is the 3d printer available to reserve?"

Env (override anything; defaults match index_pipeline.py + the home lab):
    DATABASE_URL   postgres conn (same DB your indexer wrote to)
    OLLAMA_URL     http://10.10.10.30:11434
    EMBED_MODEL    mxbai-embed-large     # MUST equal what the index was built with
    CHAT_MODEL     qwen2.5:3b            # any model from `ollama list`
    RAG_TABLE      data_makerspace_rag
    TOP_K          4
"""
import os
import sys
import json

import httpx
import psycopg

# ── Config (env-overridable) ──────────────────────────────────────────────────
# EMBEDDING stays on Ollama. The model here MUST match the model the index was
# built with — a different model = a different vector space = meaningless cosine
# distances. (In the lab this Ollama runs on the G1a / Strix Halo node.)
OLLAMA_URL  = os.environ.get("OLLAMA_URL", "http://10.10.10.31:11434").rstrip("/")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "mxbai-embed-large")   # == index embedder

# GENERATION moved to vLLM (OpenAI-compatible) on the G9 / RTX 2000 Ada node.
# GEN_BINDING selects the protocol:
#   "openai" -> POST {GEN_BASE_URL}/chat/completions   (vLLM, the new default)
#   "ollama" -> POST {OLLAMA_URL}/api/chat             (the old path, kept for rollback)
# GEN_BASE_URL already includes the /v1 suffix, e.g. http://<G9-IP>:8000/v1.
GEN_BINDING  = os.environ.get("GEN_BINDING", "openai").lower()
GEN_BASE_URL = os.environ.get("GEN_BASE_URL", "http://10.10.10.30:8000/v1").rstrip("/")
GEN_API_KEY  = os.environ.get("GEN_API_KEY", "none")              # vLLM ignores it, but the header is required
CHAT_MODEL   = os.environ.get("CHAT_MODEL", "ibm-granite/granite-4.1-8b-fp8")  # must match /v1/models

RAG_TABLE   = os.environ.get("RAG_TABLE", "data_makerspace_rag")
TOP_K       = int(os.environ.get("TOP_K", "4"))

# Your indexer reads DATABASE_URL as a SQLAlchemy URL (postgresql+psycopg://...).
# psycopg wants a plain libpq URL, so strip the "+psycopg"/"+asyncpg" driver tag.
_raw_db = os.environ.get("DATABASE_URL", "postgresql://makerspace:makerspace@10.10.10.20:5432/makerspacehub")
DATABASE_URL = _raw_db.replace("postgresql+psycopg", "postgresql").replace("postgresql+asyncpg", "postgresql")

SYSTEM_PROMPT = (
    "You answer questions about the MakerSpace using ONLY the provided context. "
    "If the context does not contain the answer, say you don't have that information. "
    "Be concise and mention the item names you used."
)


# ════════════════════════════════════════════════════════════════════════════
# LAYER: EMBED — turn text into a vector with the SAME model the index used.
# Break it: change EMBED_MODEL to bge-m3 and watch retrieval return nonsense —
# different model = different vector space = meaningless cosine distances.
# ════════════════════════════════════════════════════════════════════════════
def embed(text: str) -> list[float]:
    resp = httpx.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


# ════════════════════════════════════════════════════════════════════════════
# LAYER: RETRIEVE — nearest chunks by cosine distance in pgvector.
# `<=>` is pgvector's cosine-distance operator; smaller = closer. score = 1 - dist
# so it reads as a 0..1 similarity. This is raw SQL ON PURPOSE so you can see
# exactly what LlamaIndex does for you under the hood.
# Break it: set k=1 (too little context) or k=50 (noise) and watch answers change.
# ════════════════════════════════════════════════════════════════════════════
def retrieve(query_vec: list[float], k: int = TOP_K) -> list[dict]:
    literal = "[" + ",".join(repr(float(x)) for x in query_vec) + "]"
    sql = f"""
        SELECT text,
               metadata_,
               1 - (embedding <=> %s::vector) AS score
        FROM {RAG_TABLE}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    with psycopg.connect(DATABASE_URL, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (literal, literal, k))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


# ════════════════════════════════════════════════════════════════════════════
# LAYER: PROMPT — assemble retrieved text into the model's instructions.
# Break it: delete the context, or tell the model to "use your own knowledge",
# and watch grounding disappear — proof the answer comes from retrieval, not the LLM.
# ════════════════════════════════════════════════════════════════════════════
def build_prompt(question: str, hits: list[dict]) -> str:
    context = "\n\n---\n\n".join(h["text"] for h in hits)
    return f"Context:\n{context}\n\nQuestion: {question}"


# ════════════════════════════════════════════════════════════════════════════
# LAYER: GENERATE — hand the prompt to Ollama's chat model.
# Break it: swap CHAT_MODEL, or raise temperature, and watch faithfulness drift.
# ════════════════════════════════════════════════════════════════════════════
def generate(question: str, hits: list[dict]) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(question, hits)},
    ]

    # Rollback path: Ollama's native chat API.
    if GEN_BINDING == "ollama":
        resp = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": CHAT_MODEL, "messages": messages,
                  "stream": False, "options": {"temperature": 0.1}},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    # Default path: OpenAI-compatible chat completions (vLLM / Granite on the Ada).
    resp = httpx.post(
        f"{GEN_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {GEN_API_KEY}"},
        json={"model": CHAT_MODEL, "messages": messages,
              "temperature": 0.1, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── Inspection: list ingested documents + read back their stored chunks ───────
# Powers the in-app "Documents" viewer so you can see what the parser produced
# (the readable text), not just the vectors, without dropping to psql.
def list_documents() -> list[dict]:
    sql = f"""
        SELECT metadata_->>'name' AS name, COUNT(*) AS chunks
        FROM {RAG_TABLE}
        GROUP BY 1
        ORDER BY 1
    """
    with psycopg.connect(DATABASE_URL, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [{"name": r[0], "chunks": r[1]} for r in cur.fetchall()]


def get_chunks(name: str) -> list[dict]:
    # ORDER BY id == insertion order == parse order (page, then chunk index).
    sql = f"""
        SELECT metadata_->>'page' AS page,
               metadata_->>'chunk' AS chunk,
               text
        FROM {RAG_TABLE}
        WHERE metadata_->>'name' = %s
        ORDER BY id
    """
    with psycopg.connect(DATABASE_URL, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (name,))
            return [{"page": r[0], "chunk": r[1], "text": r[2]} for r in cur.fetchall()]


# ── Orchestration: the whole pipeline in one call ─────────────────────────────
def answer(question: str, k: int = TOP_K) -> dict:
    """Run all four layers and return the answer + the sources used."""
    qvec = embed(question)
    hits = retrieve(qvec, k)
    if not hits:
        return {"answer": "Nothing relevant found in the knowledge base.", "sources": []}
    text = generate(question, hits)
    return {"answer": text, "sources": hits}


# ── CLI: print EVERY layer so you can see the machine work ────────────────────
def _cli(question: str):
    print(f"\n[1] QUESTION: {question}")

    qvec = embed(question)
    print(f"\n[2] EMBED  → {EMBED_MODEL} produced a {len(qvec)}-dim vector")
    print(f"          first 5 dims: {[round(x, 4) for x in qvec[:5]]} ...")

    hits = retrieve(qvec)
    print(f"\n[3] RETRIEVE → top {len(hits)} chunks from {RAG_TABLE} (by cosine similarity):")
    for i, h in enumerate(hits, 1):
        name = (h.get("metadata_") or {}).get("name", "?")
        print(f"   {i}. score={h['score']:.4f}  [{name}]  {h['text'][:90]}...")

    prompt = build_prompt(question, hits)
    print(f"\n[4] PROMPT → sent to {CHAT_MODEL} ({len(prompt)} chars of context+question)")

    print(f"\n[5] GENERATE → answer:\n")
    print(generate(question, hits))
    print()


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "What equipment is available to reserve?"
    _cli(q)
