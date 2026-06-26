// ragClient.js — the network layer between the React UI and the RAG backend.
//
// Everything that touches the backend lives here, so the components never build
// URLs or parse responses themselves. The backend speaks the OpenAI chat
// protocol (see makerspace-rag/serve.py), which means this same client would
// also work against Ollama, vLLM, or OpenAI itself if you ever pivot — that's
// the "OpenAI API as the internal seam" idea from your architecture notes.

import { normalizeBaseUrl } from '../config';

/**
 * Ping the backend's /health endpoint. Used by the Settings "Test Connection"
 * button so the user gets a clear yes/no before they start chatting.
 *
 * @returns {Promise<{ok: boolean, data?: object, error?: string}>}
 */
export async function checkHealth(baseUrl, { timeoutMs = 8000 } = {}) {
  const base = normalizeBaseUrl(baseUrl);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${base}/health`, { signal: controller.signal });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: friendlyError(err) };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Send a chat turn and stream the assistant's reply back token-by-token.
 *
 * Reads the Server-Sent Events (SSE) stream the backend returns when
 * stream:true. Each SSE line looks like `data: {<chat.completion.chunk>}` and
 * the stream ends with `data: [DONE]`. We pull the `delta.content` out of each
 * chunk and hand it to onToken as it arrives.
 *
 * NOTE: the current serve.py sends the whole answer as ONE chunk rather than
 * true per-token streaming, so today you'll see the reply appear in one go.
 * This parser already handles real multi-chunk streaming, so when you upgrade
 * serve.py to stream from Ollama, the UI starts animating with no changes here.
 *
 * @param {object}   opts
 * @param {string}   opts.baseUrl      backend root, e.g. http://100.77.186.35:8088
 * @param {string}   opts.model        model id, e.g. "makerspace-rag"
 * @param {Array}    opts.messages     [{role, content}, ...] OpenAI format
 * @param {Function} opts.onToken      (textChunk) => void, called as text arrives
 * @param {AbortSignal} [opts.signal]  to support a Stop button
 * @returns {Promise<{content: string, sources: Array}>}  full reply + sources
 */
export async function streamChat({ baseUrl, model, messages, onToken, signal }) {
  const base = normalizeBaseUrl(baseUrl);

  const res = await fetch(`${base}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, messages, stream: true }),
    signal,
  });

  if (!res.ok) {
    const detail = await safeText(res);
    throw new Error(`Backend returned HTTP ${res.status}${detail ? `: ${detail}` : ''}`);
  }
  if (!res.body) {
    throw new Error('Backend did not return a streaming body.');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let content = '';

  // SSE frames are separated by a blank line. We buffer partial reads and split
  // on "\n\n" so a chunk that arrives mid-frame doesn't get mis-parsed.
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? ''; // keep the trailing partial frame for next read

    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (payload === '[DONE]') continue;
      try {
        const json = JSON.parse(payload);
        const delta = json?.choices?.[0]?.delta?.content;
        if (delta) {
          content += delta;
          onToken?.(delta);
        }
      } catch {
        // Ignore keep-alive lines or any malformed frame; keep streaming.
      }
    }
  }

  // serve.py only returns x_sources on the NON-streaming path. Sources are best
  // fetched separately via getSources() when you want to show grounding.
  return { content, sources: [] };
}

/**
 * Retrieval-only debug call. Shows exactly which chunks the backend would build
 * an answer from — handy for a "Sources" panel or for diagnosing a bad answer
 * (is it retrieval or the LLM?). Maps to serve.py's GET /search.
 */
export async function getSources(baseUrl, query, k = 4) {
  const base = normalizeBaseUrl(baseUrl);
  try {
    const res = await fetch(`${base}/search?q=${encodeURIComponent(query)}&k=${k}`);
    if (!res.ok) return [];
    return await res.json();
  } catch {
    return [];
  }
}

// ── helpers ──────────────────────────────────────────────────────────────────

function friendlyError(err) {
  if (err?.name === 'AbortError') return 'Request timed out';
  // A failed fetch to a LAN/Tailscale host usually means it's unreachable or
  // CORS is blocking it — point the user at the likely culprits.
  if (err instanceof TypeError) {
    return 'Could not reach the server (is it running, and is CORS enabled?)';
  }
  return err?.message || String(err);
}

async function safeText(res) {
  try {
    const t = await res.text();
    return t.slice(0, 200);
  } catch {
    return '';
  }
}
