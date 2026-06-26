import React, { useState } from 'react';
import { checkHealth } from '../api/ragClient';
import '../styles/SettingsModal.css';

// Settings now read from and write to the real config (localStorage via App).
// The "General" tab holds the connection details that actually drive requests:
// the backend Base URL, model id, and system prompt.
function SettingsModal({ settings, onSave, onClose }) {
  const [activeTab, setActiveTab] = useState('general');
  const [form, setForm] = useState({ ...settings });
  const [test, setTest] = useState(null); // { state: 'idle'|'testing'|'ok'|'fail', msg }

  const update = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  const handleSave = () => {
    onSave(form);
    onClose();
  };

  const handleTest = async () => {
    setTest({ state: 'testing' });
    const res = await checkHealth(form.baseUrl);
    if (res.ok) {
      setTest({
        state: 'ok',
        msg: `Connected — chat: ${res.data?.chat_model || '?'}, embed: ${res.data?.embed_model || '?'}`,
      });
    } else {
      setTest({ state: 'fail', msg: res.error || 'Unreachable' });
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content glass-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Settings</h2>
          <button className="close-btn" onClick={onClose}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div className="modal-body">
          <div className="settings-sidebar">
            <button
              className={`tab-btn ${activeTab === 'general' ? 'active' : ''}`}
              onClick={() => setActiveTab('general')}
            >
              Connection
            </button>
            <button
              className={`tab-btn ${activeTab === 'models' ? 'active' : ''}`}
              onClick={() => setActiveTab('models')}
            >
              Model
            </button>
          </div>

          <div className="settings-content">
            {activeTab === 'general' && (
              <div className="settings-section">
                <h3>Backend Base URL</h3>
                <p className="setting-desc">
                  Root URL of the RAG server (serve.py). No trailing <code>/v1</code>.
                </p>
                <input
                  type="text"
                  className="settings-input"
                  value={form.baseUrl}
                  onChange={(e) => update('baseUrl', e.target.value)}
                  placeholder="http://100.77.186.35:8088"
                />

                <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <button
                    className="btn secondary-btn"
                    onClick={handleTest}
                    disabled={test?.state === 'testing'}
                  >
                    {test?.state === 'testing' ? 'Testing…' : 'Test Connection'}
                  </button>
                  {test?.state === 'ok' && (
                    <span style={{ color: 'var(--success, #4caf50)', fontSize: '0.85rem' }}>
                      ✓ {test.msg}
                    </span>
                  )}
                  {test?.state === 'fail' && (
                    <span style={{ color: 'var(--danger, #ff6b6b)', fontSize: '0.85rem' }}>
                      ✗ {test.msg}
                    </span>
                  )}
                </div>

                <h3 className="mt-4">System Prompt</h3>
                <p className="setting-desc">
                  Sent as the system message. (Note: the current serve.py uses its
                  own built-in prompt and ignores this — kept for when it doesn't.)
                </p>
                <textarea
                  className="settings-textarea"
                  rows="4"
                  value={form.systemPrompt}
                  onChange={(e) => update('systemPrompt', e.target.value)}
                />
              </div>
            )}

            {activeTab === 'models' && (
              <div className="settings-section">
                <h3>Model ID</h3>
                <p className="setting-desc">
                  The model id the backend advertises at <code>/v1/models</code>.
                </p>
                <input
                  type="text"
                  className="settings-input"
                  value={form.model}
                  onChange={(e) => update('model', e.target.value)}
                  placeholder="makerspace-rag"
                />
              </div>
            )}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn secondary-btn" onClick={onClose}>Cancel</button>
          <button className="btn primary-btn" onClick={handleSave}>Save Changes</button>
        </div>
      </div>
    </div>
  );
}

export default SettingsModal;
