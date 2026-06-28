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

import re

import psycopg
from pypdf import PdfReader

# Some parsers (e.g. Docling's VLM pipeline) embed page images into their markdown
# as base64 data URIs. Those are useless for retrieval and would otherwise be
# chunked + embedded into garbage vectors, so strip them before anything else.
_DATA_URI_RE = re.compile(
    r'!\[[^\]]*\]\(\s*data:[^)]*\)|data:[a-z]+/[^;\s]+;base64,[A-Za-z0-9+/=]{40,}',
    re.IGNORECASE,
)


def _strip_embedded_data(text: str) -> str:
    return _DATA_URI_RE.sub("", text)

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
    text = _strip_embedded_data(text)  # drop base64 image blobs some parsers embed
    text = " ".join(text.split())      # normalize whitespace/newlines
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
# CHUNK (structured) — split markdown on its headings so each chunk IS a section
# and carries that heading as metadata. This is the high-value move for vague
# queries over regulations: "termination pay?" lands on a self-labeled
# "Sec. 61.014. PAYMENT OF WAGES" chunk instead of a context-free window. Long
# sections are window-split, but every piece keeps its section label.
# ════════════════════════════════════════════════════════════════════════════
_HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s+(.*\S)\s*$')


def chunk_markdown_by_heading(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Return a list of (section, chunk_text). Splits on markdown headings; the
    heading is both prepended into the chunk body (so the chunk is self-describing
    for the embedder) and returned separately (so it can go into metadata_)."""
    text = _strip_embedded_data(text)
    sections, heading, buf = [], None, []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            if heading is not None or buf:
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if heading is not None or buf:
        sections.append((heading, "\n".join(buf).strip()))

    out = []
    for sec, body in sections:
        full = f"{sec}\n{body}".strip() if sec else body
        if not full:
            continue
        if len(" ".join(full.split())) <= size:
            out.append((sec, full))
        else:
            for piece in chunk_text(full, size, overlap):
                out.append((sec, piece))
    return out


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


def ingest_file(conn, path: pathlib.Path, replace: bool = False, structured: bool = False) -> int:
    # replace=True makes re-ingesting the same filename idempotent (drop its old
    # chunks first) instead of appending duplicates — used by the upload endpoint.
    if replace:
        delete_by_name(conn, path.name)
    # structured=True splits markdown/text on headings and tags each chunk with
    # its section. (PDFs have no markdown headings, so they fall back to windows.)
    use_headings = structured and path.suffix.lower() in {".md", ".txt"}
    n = 0
    for text, page in load_document(path):
        if use_headings:
            units = chunk_markdown_by_heading(text)            # [(section, chunk)]
        else:
            units = [(None, c) for c in chunk_text(text)]
        for ci, (section, chunk) in enumerate(units):
            vec = core.embed(chunk)
            if len(vec) != EMBED_DIM:
                raise RuntimeError(
                    f"Embedding dimension {len(vec)} != expected {EMBED_DIM}. "
                    f"Is EMBED_MODEL '{core.EMBED_MODEL}' the bge-m3 model this table is for?"
                )
            meta = {"name": path.name, "page": page, "section": section, "chunk": ci}
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {core.RAG_TABLE} (text, metadata_, embedding) "
                    f"VALUES (%s, %s, %s::vector)",
                    (chunk, json.dumps(meta), _vector_literal(vec)),
                )
            n += 1
    conn.commit()
    return n


def ingest_paths(paths, reset: bool = False, replace: bool = False, structured: bool = False) -> int:
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
            total += ingest_file(conn, p, replace=replace, structured=structured)
    return total


def main():
    ap = argparse.ArgumentParser(description="Ingest documents into pgvector for the Local AI RAG app.")
    ap.add_argument("--source", default=os.environ.get("INGEST_DIR", "/data/pdfs"),
                    help="Folder of .pdf/.txt/.md files (default: /data/pdfs)")
    ap.add_argument("--reset", action="store_true",
                    help="TRUNCATE the table before ingesting (clean re-index)")
    ap.add_argument("--preview", action="store_true",
                    help="Parse + chunk and PRINT the chunks only — no embedding, no DB writes. "
                         "Tune with CHUNK_SIZE / CHUNK_OVERLAP env vars and re-run.")
    ap.add_argument("--structured", action="store_true",
                    help="Split markdown/text on headings; tag each chunk with its section "
                         "(metadata_.section). Best for structured docs and regulations.")
    args = ap.parse_args()

    src = pathlib.Path(args.source)
    if not src.is_dir():
        raise SystemExit(f"Source folder not found: {src}")

    files = sorted(p for p in src.rglob("*") if p.suffix.lower() in SUPPORTED)
    if not files:
        raise SystemExit(f"No .pdf/.txt/.md files found under {src}")

    # ── DRY RUN: see exactly how a document parses + chunks, no DB, no embedder.
    if args.preview:
        for f in files:
            print(f"\n===== {f.name} =====")
            n = 0
            use_headings = args.structured and f.suffix.lower() in {".md", ".txt"}
            for text, page in load_document(f):
                units = chunk_markdown_by_heading(text) if use_headings else [(None, c) for c in chunk_text(text)]
                for section, chunk in units:
                    tag = f"section: {section}" if section else f"page {page}"
                    print(f"\n--- chunk {n}  ({tag}, {len(chunk)} chars) ---")
                    print(chunk)
                    n += 1
            mode = " · structured" if use_headings else ""
            print(f"\n[{f.name}: {n} chunks  @ size={CHUNK_SIZE} / overlap={CHUNK_OVERLAP}{mode}]")
        return

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
                c = ingest_file(conn, f, structured=args.structured)
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
