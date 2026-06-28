import React, { useState, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import SettingsModal from './components/SettingsModal';
import DocumentsModal from './components/DocumentsModal';
import { loadSettings, saveSettings } from './config';
import logo from './assets/logo.png';
import './App.css';

// Chat sessions live here in the app, NOT on the backend. The RAG server
// (serve.py) is stateless — it answers one question at a time and remembers
// nothing — so the sidebar history, titles, and message logs are owned and
// persisted by the frontend. We keep them in localStorage so they survive a
// restart of the desktop app.
const SESSIONS_KEY = 'localai.sessions.v1';

function makeEmptySession() {
  return { id: Date.now(), title: 'New Chat', messages: [] };
}

function loadSessions() {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed) && parsed.length) return parsed;
  } catch {
    // fall through to a fresh session
  }
  return [makeEmptySession()];
}

function App() {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isDocsOpen, setIsDocsOpen] = useState(false);
  const [settings, setSettings] = useState(loadSettings);
  const [sessions, setSessions] = useState(loadSessions);
  const [currentChatId, setCurrentChatId] = useState(() => loadSessions()[0].id);

  // Persist sessions whenever they change.
  useEffect(() => {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
  }, [sessions]);

  const currentSession =
    sessions.find((s) => s.id === currentChatId) || sessions[0];

  const handleNewChat = useCallback(() => {
    const fresh = makeEmptySession();
    setSessions((prev) => [fresh, ...prev]);
    setCurrentChatId(fresh.id);
  }, []);

  // Replace the message list for the active session. We also auto-title a new
  // chat from its first user message so the sidebar isn't a wall of "New Chat".
  const updateSessionMessages = useCallback(
    (sessionId, updater) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s;
          const messages =
            typeof updater === 'function' ? updater(s.messages) : updater;
          let title = s.title;
          if (title === 'New Chat') {
            const firstUser = messages.find((m) => m.role === 'user');
            if (firstUser) title = firstUser.content.slice(0, 40);
          }
          return { ...s, messages, title };
        })
      );
    },
    []
  );

  const handleSaveSettings = useCallback((next) => {
    setSettings(saveSettings(next));
  }, []);

  return (
    <div className="app-container">
      <header className="top-banner glass-panel">
        <img src={logo} alt="LJA Logo" className="banner-logo" />
      </header>

      <div className="main-content">
        <Sidebar
          sessions={sessions}
          currentChatId={currentChatId}
          onSelectChat={setCurrentChatId}
          onNewChat={handleNewChat}
          onOpenSettings={() => setIsSettingsOpen(true)}
          onOpenDocuments={() => setIsDocsOpen(true)}
        />
        <ChatArea
          key={currentSession.id}
          session={currentSession}
          settings={settings}
          onMessagesChange={(updater) =>
            updateSessionMessages(currentSession.id, updater)
          }
        />
      </div>

      {isSettingsOpen && (
        <SettingsModal
          settings={settings}
          onSave={handleSaveSettings}
          onClose={() => setIsSettingsOpen(false)}
        />
      )}

      {isDocsOpen && (
        <DocumentsModal settings={settings} onClose={() => setIsDocsOpen(false)} />
      )}
    </div>
  );
}

export default App;
