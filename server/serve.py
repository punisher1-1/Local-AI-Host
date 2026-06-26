"""
serve.py — wrap the transparent RAG core as an OpenAI-compatible API.

This is the bridge you were missing: a chat UI (Open WebUI) only speaks the
OpenAI chat protocol and knows nothing about pgvector. So we expose ONE endpoint
that looks exactly like an OpenAI model — but every call secretly runs
retrieve → generate against your MakerSpace vectors.

Point Open WebUI at this as an "OpenAI API" connection:
    Base URL : http://<this-host>:8088/v1
    API key  : anything (ignored)
Then pick the model "makerspace-rag" in the chat dropdown.

Run:
    uvicorn serve:app --host 0.0.0.0 --port 8088
    # or: python serve.py
"""
import os
import time
import json
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import makerspace_rag as core   # reuse the SAME four-layer functions — one source of truth

MODEL_ID = os.environ.get("RAG_MODEL_ID", "makerspace-rag")
PORT = int(os.environ.get("PORT", "8088"))

app = FastAPI(title="MakerSpace RAG (OpenAI-compatible)", version="0.1.0")

# CORS — required so a browser-based UI (the Vite/Electron "Local AI" frontend)
# can call this API directly from a different origin. Without this, the browser
# blocks the request before it ever reaches FastAPI. CORS_ORIGINS is a
# comma-separated allowlist; default "*" is fine for a trusted LAN/Tailscale lab,
# but tighten it (e.g. the app's origin) if this is ever exposed more widely.
_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "embed_model": core.EMBED_MODEL, "chat_model": core.CHAT_MODEL, "table": core.RAG_TABLE}


# ── Transparent debug endpoint — retrieval ONLY, no generation ────────────────
# Hit http://host:8088/search?q=... to SEE exactly what the UI's answer is built
# from. Invaluable when an answer looks wrong: is it retrieval or the LLM?
@app.get("/search")
def search(q: str, k: int = core.TOP_K):
    hits = core.retrieve(core.embed(q), k)
    return [{"score": round(h["score"], 4),
             "name": (h.get("metadata_") or {}).get("name"),
             "text": h["text"]} for h in hits]


# ── OpenAI-compatible: model list (so Open WebUI shows us in its dropdown) ─────
@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "makerspace"}]}


# ── OpenAI-compatible: chat completions (the part Open WebUI actually calls) ───
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = bool(body.get("stream", False))

    # The user's question = the last user-role message. (Earlier turns are
    # ignored here for simplicity — a real build would condense chat history.)
    question = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")

    result = core.answer(question)           # ← all four RAG layers run here
    content = result["answer"]
    created = int(time.time())
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    if stream:
        # Open WebUI defaults to streaming. We don't truly stream from Ollama
        # here; we send the finished answer as a single SSE chunk, then [DONE].
        def event_stream():
            first = {"id": cid, "object": "chat.completion.chunk", "created": created,
                     "model": MODEL_ID,
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": content},
                                  "finish_reason": None}]}
            yield f"data: {json.dumps(first)}\n\n"
            done = {"id": cid, "object": "chat.completion.chunk", "created": created,
                    "model": MODEL_ID,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return {
        "id": cid, "object": "chat.completion", "created": created, "model": MODEL_ID,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        # Bonus: surface the retrieved sources so you can inspect grounding from the API.
        "x_sources": [{"score": round(h["score"], 4),
                       "name": (h.get("metadata_") or {}).get("name")} for h in result["sources"]],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve:app", host="0.0.0.0", port=PORT)
