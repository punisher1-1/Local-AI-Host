# Local AI — Deployment Guide (Docker image in a dedicated Proxmox LXC)

This deploys the **whole app — frontend + backend — as one Docker container**.
The **database is intentionally separate** (external pgvector Postgres). The
container is stateless: destroy and recreate it freely; the data lives in
Postgres with its own backups.

```
                         ┌──────────────────────── dedicated LXC (Docker) ───────────────────────┐
  browser  ──http:8080── │  nginx :80  ──serves──►  React app (built dist/)                       │
                         │     │                                                                   │
                         │     └──proxy /v1,/search,/health──►  uvicorn :8088  (FastAPI serve.py)  │
                         └───────────────────────────────────────────┬───────────────────────────┘
                                                                      │
                  ┌───────────────────────────────────────────────────┼───────────────────────────┐
                  ▼                                ▼                    ▼
         vLLM /v1 (Granite, G9/Ada)     Ollama embed (G1a/Strix)   pgvector Postgres (its own home)
```

Because nginx serves the page **and** proxies the API on the same origin, the
browser never makes a cross-origin call, so **CORS is a non-issue** in this
deployment.

---

## 1. Create the LXC on Proxmox

A lightweight Debian/Ubuntu LXC is plenty — the container does no GPU work, it's
just a web tier. Suggested: 2 vCPU, 2 GB RAM, 16 GB disk.

Enable the features Docker needs **before** first boot (Proxmox host shell, swap
`<CTID>` for the container id):

```bash
pct set 260 --features nesting=1,keyctl=1
```

> **AppArmor note (from your KB — "Docker in LXC AppArmor and Deployment
> Troubleshooting"):** on this kernel/AppArmor combo, Docker inside the LXC
> can't load the `docker-default` profile and containers fail with exit 243.
> The verified workaround is to run the app container **unconfined** — already
> set as `security_opt: [apparmor=unconfined]` in `docker-compose.yml`, so you
> shouldn't hit it. The container is still isolated by the LXC's namespaces and
> cgroups.

## 2. Install Docker in the LXC

```bash
# inside the LXC
apt-get update && apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version
```

## 3. Get the app onto the LXC

Copy this `ai-frontend` folder into the LXC (git clone, `scp`, or a bind mount).
Everything the build needs is in here — the frontend source **and** the backend
(`server/serve.py`, `server/makerspace_rag.py`).

## 4. Configure the connections

```bash
cd ai-frontend
cp .env.example .env
nano .env
```

Fill in (see comments in the file):

| Variable        | What it points at                                   |
|-----------------|-----------------------------------------------------|
| `DATABASE_URL`  | external pgvector Postgres (`postgresql://…`)        |
| `GEN_BASE_URL`  | vLLM on the **G9/Ada**, incl. `/v1` → `http://<G9>:8000/v1` |
| `CHAT_MODEL`    | `ibm-granite/granite-4.1-8b-fp8` (match `/v1/models`)|
| `OLLAMA_URL`    | Ollama on the **G1a/Strix** → `http://<G1A>:11434`   |
| `EMBED_MODEL`   | **must** match the model the index was built with    |

> The `EMBED_MODEL` rule is the one that silently breaks RAG: a different
> embedding model = a different vector space = meaningless similarity scores.
> Keep it identical to whatever built `data_makerspace_rag`.

## 5. Build and run

```bash
docker compose up -d --build
docker compose logs -f        # watch nginx + uvicorn start
```

Then browse to **`http://<lxc-ip>:8080`**. In the app's Settings, the Base URL
should stay **blank** (same-origin) — leave it empty and hit **Test Connection**;
you should see the backend's chat/embed models come back.

## 6. Verify the path end-to-end

```bash
# from inside the LXC — the same URL the browser uses, via nginx:
curl http://localhost:8080/health
curl "http://localhost:8080/search?q=is%20the%203d%20printer%20available&k=3"
```

`/health` confirms the backend is up; `/search` confirms it can reach Postgres
and embed a query. If `/search` errors, it's a DB or embedding-host problem, not
the UI.

---

## Cloning for expansion

This is why it's its own LXC: once it's working, snapshot it in Proxmox and
clone the LXC as a template for a second instance or a staging copy. Each clone
just needs its own `.env` (e.g. a different DB or model endpoint). The app
carries no state, so clones are disposable.

## Updating the app

```bash
cd ai-frontend && git pull         # or re-copy the folder
docker compose up -d --build       # rebuilds the image, recreates the container
```

## Notes / follow-ups

- **Streaming:** `serve.py` currently sends the full answer as one SSE chunk
  (not true token streaming). The frontend already renders progressive streams,
  so when you upgrade `serve.py` to stream from vLLM, the UI animates with no
  frontend change.
- **Backend source of truth:** the canonical backend lives in the Obsidian
  `LJA Local AI Project/makerspace-rag/`. The copies in `server/` are what this
  image builds — keep them in sync when you change the backend.
- **HTTPS / single URL:** if you later put this behind the reverse proxy from
  your "Internal Access to AI Nodes" decision record, terminate TLS there and
  point it at `<lxc-ip>:8080`.
