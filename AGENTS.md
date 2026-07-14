# AGENTS.md

## Cursor Cloud specific instructions

### What this app is
"Local AI" is a RAG chat app in one repo with three parts:
- **Frontend** — React/Vite SPA (repo root, `src/`). Dev server: `npm run dev`.
- **Backend** — FastAPI, OpenAI-compatible RAG API in `server/` (`serve.py`). Endpoints: `/health`, `/search`, `/v1/chat/completions`, `/ingest`, `/documents`, `/chunks`.
- **Electron** — desktop wrapper of the same frontend (`electron/`), launched automatically by `npm run dev`.

The RAG flow (`server/makerspace_rag.py`) is: embed query (Ollama) → retrieve from Postgres/pgvector → build prompt → generate (Ollama or any OpenAI-compatible server).

### Dependencies
Installed by the startup update script: `npm install` (root) and `pip install --break-system-packages -r server/requirements.txt`. No need to reinstall these manually.

### Standard commands
See `package.json` scripts (`dev`, `build`, `lint`, `build:electron`) and `DEPLOYMENT.md` (Docker/prod). Backend run + RAG details are documented in `server/serve.py`, `server/ingest.py`, and `.env.example`.

### Non-obvious gotchas (read before running)
- **`uvicorn` is not on PATH** (installed to `~/.local/bin`). Run the backend with `python3 -m uvicorn serve:app --host 0.0.0.0 --port 8088` from `server/`.
- **The backend does NOT auto-load `.env`.** `serve.py`/`makerspace_rag.py` read plain `os.environ`. Export vars first, e.g. `set -a && source /workspace/.env && set +a` in the shell that starts uvicorn / `ingest.py`.
- **`.env` and `data/pdfs/` are gitignored**, so they do not exist on a fresh clone. `.env.example` points at unreachable home-lab IPs; create a local `.env` (see below) for local dev.
- **`npm run dev` also launches Electron.** In this headless VM Electron prints harmless dbus/GPU errors — ignore them; the Vite web server still runs.
- **Vite dev server binds IPv6 localhost only.** Use `http://localhost:5173` (resolves to `::1`); `http://127.0.0.1:5173` will refuse the connection. In dev, Vite proxies `/v1`, `/search`, `/health` to the backend on `:8088`, so leave the app's Settings Base URL blank (same-origin).
- **`npm run lint` currently reports pre-existing errors** (unused `React` imports in `src/components/*`, `process` global in `vite.config.js`). These are in the committed code, not an environment problem; `npm run build` succeeds.

### Local RAG services (Postgres + Ollama) — required for chat/search
The full chat/search path needs three backing services, run locally in this VM (no external hosts):
- **Postgres 16 + pgvector**, started without systemd: `sudo pg_ctlcluster 16 main start`. DB `lja_rag`, role `rag`/`rag` (superuser). Vector extension is enabled in that DB.
- **Ollama** (embeddings + generation), started in a shell: `OLLAMA_HOST=127.0.0.1:11434 OLLAMA_FLASH_ATTENTION=0 ollama serve`. Models pulled: `nomic-embed-text` (embeddings, 768-dim) and `llama3.2:1b` (chat).
- **Ollama AMX gotcha:** Ollama's `sapphirerapids` (AMX) CPU backend segfaults in this VM. The fix already applied: the AMX backend `.so` was moved to `/usr/local/lib/ollama/_disabled_amx/` so Ollama falls back to an AVX-512 backend. If Ollama is ever reinstalled/upgraded, re-apply this (move `libggml-cpu-sapphirerapids.so` out of `/usr/local/lib/ollama/`) or chat generation will crash with a segfault.

Local `.env` used for dev (recreate at repo root if missing):
```
DATABASE_URL=postgresql://rag:rag@127.0.0.1:5432/lja_rag
RAG_TABLE=data_lja_rag
TOP_K=4
GEN_BINDING=ollama
OLLAMA_URL=http://127.0.0.1:11434
CHAT_MODEL=llama3.2:1b
EMBED_MODEL=nomic-embed-text
EMBED_DIM=768
```
`EMBED_DIM` MUST match the embedding model's vector size (nomic-embed-text = 768; the default bge-m3 = 1024). A mismatch makes `ingest.py` raise a dimension error.

### Typical startup sequence for a chat/search test
1. `sudo pg_ctlcluster 16 main start`
2. `OLLAMA_HOST=127.0.0.1:11434 OLLAMA_FLASH_ATTENTION=0 ollama serve` (own terminal)
3. Put docs in `data/pdfs/`, then from `server/`: `set -a && source /workspace/.env && set +a && python3 ingest.py --source /workspace/data/pdfs --structured`
4. From `server/`: `set -a && source /workspace/.env && set +a && python3 -m uvicorn serve:app --host 0.0.0.0 --port 8088`
5. From root: `npm run dev`, then open `http://localhost:5173`.
