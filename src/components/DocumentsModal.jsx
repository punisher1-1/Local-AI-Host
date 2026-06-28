import React, { useState, useEffect, useCallback } from 'react';
import { listDocuments, getChunks } from '../api/ragClient';
import '../styles/SettingsModal.css';
import '../styles/DocumentsModal.css';

// In-app "staging view": lists ingested documents and shows the readable chunk
// text the parser produced — so you can inspect/tune retrieval without psql.
function DocumentsModal({ settings, onClose }) {
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [error, setError] = useState(null);

  const openDoc = useCallback(
    async (name) => {
      setSelected(name);
      setLoadingChunks(true);
      setChunks([]);
      try {
        setChunks(await getChunks(settings.baseUrl, name));
      } catch (e) {
        setError(e.message);
      } finally {
        setLoadingChunks(false);
      }
    },
    [settings]
  );

  useEffect(() => {
    listDocuments(settings.baseUrl)
      .then((d) => {
        setDocs(d);
        setLoadingDocs(false);
        if (d.length) openDoc(d[0].name);
      })
      .catch((e) => {
        setError(e.message);
        setLoadingDocs(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content glass-panel docs-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Documents</h2>
          <button className="close-btn" onClick={onClose}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div className="modal-body docs-body">
          <div className="docs-list">
            <span className="docs-list-title">
              {settings.model} · {settings.baseUrl ? settings.baseUrl.replace(/^https?:\/\//, '') : 'same-origin'}
            </span>
            {loadingDocs && <p className="docs-empty">Loading…</p>}
            {!loadingDocs && docs.length === 0 && (
              <p className="docs-empty">No documents indexed yet. Upload one with the attach button.</p>
            )}
            {docs.map((d) => (
              <button
                key={d.name}
                className={`doc-item ${selected === d.name ? 'active' : ''}`}
                onClick={() => openDoc(d.name)}
                title={d.name}
              >
                <span className="doc-name">{d.name}</span>
                <span className="doc-count">{d.chunks}</span>
              </button>
            ))}
          </div>

          <div className="docs-chunks">
            {error && <div className="chat-error" role="alert">⚠ {error}</div>}
            {loadingChunks && <p className="docs-empty">Loading chunks…</p>}
            {!loadingChunks && selected && chunks.length === 0 && !error && (
              <p className="docs-empty">No chunks for this document.</p>
            )}
            {chunks.map((c, i) => (
              <div className="chunk-card" key={i}>
                <div className="chunk-meta">
                  chunk {c.chunk ?? i}
                  {c.page != null && ` · page ${c.page}`}
                  <span className="chunk-len">{c.text.length} chars</span>
                </div>
                <p className="chunk-text">{c.text}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn primary-btn" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}

export default DocumentsModal;
