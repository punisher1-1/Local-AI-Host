// config.js — single source of truth for backend connection settings.
//
// These values are what the frontend uses to reach the MakerSpace RAG backend
// (serve.py — an OpenAI-compatible FastAPI server). They're persisted in
// localStorage so the user can change them in Settings without editing code,
// and they survive app restarts.
//
// The backend contract (see makerspace-rag/serve.py in the LJA Local AI Project):
//   GET  /health                 -> { status, embed_model, chat_model, table }
//   GET  /v1/models              -> { data: [{ id: "makerspace-rag", ... }] }
//   POST /v1/chat/completions    -> OpenAI chat protocol (supports stream:true, SSE)
//   GET  /search?q=&k=           -> retrieval-only debug view

const STORAGE_KEY = 'localai.settings.v1';

// Sensible defaults for THIS home lab. The RAG backend runs on the fastapi-node
// VM (Tailscale 100.77.186.35) on port 8088. Change in Settings if it moves.
export const DEFAULT_SETTINGS = {
  // Empty string = same-origin. In the web deployment, nginx serves this page
  // AND proxies /v1, /search, /health to the backend, so the browser just calls
  // relative paths ("/v1/chat/completions") and there's no CORS to worry about.
  // For the Electron desktop build (file://) or `npm run dev` against a remote
  // backend, set an absolute URL here or in Settings, e.g. http://<host>:8088.
  baseUrl: '',                          // same-origin via nginx
  model: 'makerspace-rag',              // the model id serve.py advertises
  systemPrompt:
    'You answer questions about the MakerSpace using ONLY the provided context.',
  stream: true,                         // stream tokens as they arrive
};

export function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    // Merge so new default keys appear even on older saved blobs.
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(settings) {
  const merged = { ...DEFAULT_SETTINGS, ...settings };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
  return merged;
}

// Normalize a base URL: trim whitespace and any trailing slash so we can safely
// append "/v1/chat/completions" etc. without doubling up slashes.
export function normalizeBaseUrl(url) {
  return (url || '').trim().replace(/\/+$/, '');
}
