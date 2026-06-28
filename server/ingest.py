"""
ingest.py — load documents (PDF / TXT / MD) into pgvector for the Local AI RAG app.

This is the INDEX side that the query side (makerspace_rag.py) reads from. It is
deliberately transparent — each stage is a named function you can read and swap:

    files  → [LOAD]  extract raw text (per page for PDFs, so we can cite pages)
           → [CHUNK] split into overlapping character windows
           → [EMBED] bge-m3 via Ollama — the SAME model the query side uses
           → [WRITE] insert into pgvector (text, metadata_, embedding)

Why import makerspace_rag: so there is ONE source of truth for the embedder, the
Ollama host, the database URL, and the table name. The embedding model here MUST
match what the table was built with, or retrieval returns nonsense (same model =
same vector space). We even assert the dimension to catch a wrong model early.

The PARSE/CHUNK step is intentionally isolated. Swapping in a fancier parser
(LlamaIndex, etc.) later means editing load_document()/chunk_text() and re-running
with --reset — nothing else changes, because your source files are the source of
truth and the table is rebuildable from them.

Usage (inside the app container, with documents bind-mounted at /data/pdfs):
    docker compose exec ai-app python /app/ingest.py --source /data/pdfs
    docker compose exec ai-app python /app/ingest.py --source /data/pdfs --reset

    --reset TRUNCATEs the table first — use it when you change chunking and want a
    clean re-index.
"""
import os
import sys
import json
import argparse
import pathlib

import psycopg
from pypdf import PdfReader

import makerspace_rag as core  # one source of truth: embed(), EMBED_MODEL, OLLAMA_URL, DATABASE_URL, RAG_TABLE

EMBED_DIM     = int(os.environ.get("EMBED_DIM", "1024"))     # bge-m3 = 1024
CHUNK_SIZE    = int(os.environ.get("CHUNK_SIZE", "1000"))    # characters per chunk
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "150"))  # characters shared between neighbors
SUPPORTED     = {".pdf", ".txt", ".md"}


# ════════════════════════════════════════════════════════════════════════════
# SCHEMA — make sure pgvector + the table + an index exist (idempotent).
# The column layout MUST match what makerspace_rag.retrieve() selects:
#   text, metadata_, embedding
# ════════════════════════════════════════════════════════════════════════════
def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {core.RAG_TABLE} (
                id        bigserial PRIMARY KEY,
                text      text  NOT NULL,
                metadata_ jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                embedding vector({EMBED_DIM}) NOT NULL
            );
        """)
        # HNSW + cosine: no training step, tunes itself well for a small, changing KB.
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS {core.RAG_TABLE}_embedding_hnsw
            ON {core.RAG_TABLE} USING hnsw (embedding vector_cosine_ops);
        """)
    conn.commit()


# ════════════════════════════════════════════════════════════════════════════
# LOAD — file → raw text. PDFs yield one unit per page so we can record the page.
# ════════════════════════════════════════════════════════════════════════════
def load_document(path: pathlib.Path):
    """Yield (text, page_number_or_None) for each logical unit of the file."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(str(path))
        for i, page in enumerate(reader.pages, start=1):
            txt = (page.extract_text() or "").strip()
            if txt:
                yield txt, i
    else:  # .txt / .md
        txt = path.read_text(encoding="utf-8", errors="ignore").strip()
        if txt:
            yield txt, None


# ════════════════════════════════════════════════════════════════════════════
# CHUNK — overlapping character windows, broken on whitespace so we don't slice
# through a word. Break it: shrink CHUNK_SIZE to 200 and watch answers lose
# context, or kill CHUNK_OVERLAP and watch facts split across a boundary vanish.
# ════════════════════════════════════════════════════════════════════════════
def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    text = " ".join(text.split())  # normalize whitespace/newlines
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            sp = text.rfind(" ", start, end)
            if sp > start:
                end = sp
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, 0)
    return chunks


# ════════════════════════════════════════════════════════════════════════════
# WRITE — embed each chunk and insert it with citable metadata.
# metadata_.name is what serve.py's /search and the UI's "Sources" panel display.
# ════════════════════════════════════════════════════════════════════════════
def _vector_literal(vec):
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def delete_by_name(conn, name: str):
    """Remove all chunks previously ingested from a file of this name."""
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {core.RAG_TABLE} WHERE metadata_->>'name' = %s", (name,)
        )
    conn.commit()


def ingest_file(conn, path: pathlib.Path, replace: bool = False) -> int:
    # replace=True makes re-ingesting the same filename idempotent (drop its old
    # chunks first) instead of appending duplicates — used by the upload endpoint.
    if replace:
        delete_by_name(conn, path.name)
    n = 0
    for text, page in load_document(path):
        for ci, chunk in enumerate(chunk_text(text)):
            vec = core.embed(chunk)
            if len(vec) != EMBED_DIM:
                raise RuntimeError(
                    f"Embedding dimension {len(vec)} != expected {EMBED_DIM}. "
                    f"Is EMBED_MODEL '{core.EMBED_MODEL}' the bge-m3 model this table is for?"
                )
            meta = {"name": path.name, "page": page, "chunk": ci}
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {core.RAG_TABLE} (text, metadata_, embedding) "
                    f"VALUES (%s, %s, %s::vector)",
                    (chunk, json.dumps(meta), _vector_literal(vec)),
                )
            n += 1
    conn.commit()
    return n


def ingest_paths(paths, reset: bool = False, replace: bool = False) -> int:
    """Programmatic entry point (used by serve.py's /ingest endpoint). Opens a
    connection, ensures the schema, optionally resets, and ingests each path."""
    total = 0
    with psycopg.connect(core.DATABASE_URL, connect_timeout=10) as conn:
        ensure_schema(conn)
        if reset:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE {core.RAG_TABLE} RESTART IDENTITY;")
            conn.commit()
        for p in paths:
            total += ingest_file(conn, p, replace=replace)
    return total


def main():
    ap = argparse.ArgumentParser(description="Ingest documents into pgvector for the Local AI RAG app.")
    ap.add_argument("--source", default=os.environ.get("INGEST_DIR", "/data/pdfs"),
                    help="Folder of .pdf/.txt/.md files (default: /data/pdfs)")
    ap.add_argument("--reset", action="store_true",
                    help="TRUNCATE the table before ingesting (clean re-index)")
    args = ap.parse_args()

    src = pathlib.Path(args.source)
    if not src.is_dir():
        raise SystemExit(f"Source folder not found: {src}")

    files = sorted(p for p in src.rglob("*") if p.suffix.lower() in SUPPORTED)
    if not files:
        raise SystemExit(f"No .pdf/.txt/.md files found under {src}")

    print(f"Embedder : {core.EMBED_MODEL} @ {core.OLLAMA_URL}")
    print(f"Table    : {core.RAG_TABLE}")
    print(f"Database : {core.DATABASE_URL.rsplit('@', 1)[-1]}")  # host/db only, no creds
    print(f"Files    : {len(files)} under {src}")
    print("-" * 60)

    with psycopg.connect(core.DATABASE_URL, connect_timeout=10) as conn:
        ensure_schema(conn)
        if args.reset:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE {core.RAG_TABLE} RESTART IDENTITY;")
            conn.commit()
            print("Table truncated (--reset).")

        total = 0
        for f in files:
            try:
                c = ingest_file(conn, f)
                total += c
                print(f"  OK  {f.name}: {c} chunks")
            except SystemExit:
                raise
            except Exception as e:
                print(f"  ERR {f.name}: {e}")

    print("-" * 60)
    print(f"Done. {total} chunks embedded into {core.RAG_TABLE}.")


if __name__ == "__main__":
    main()
