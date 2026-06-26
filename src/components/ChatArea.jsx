import React, { useState, useEffect, useRef, useCallback } from 'react';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';
import { streamChat, getSources } from '../api/ragClient';
import '../styles/ChatArea.css';

// ChatArea owns the live conversation. Messages are passed down from App (so
// they persist with the session) and changes are pushed back up via
// onMessagesChange. The actual network call goes through ragClient.
function ChatArea({ session, settings, onMessagesChange }) {
  const messages = session.messages;
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState(null);
  const messagesEndRef = useRef(null);
  const abortRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Cancel any in-flight request if the user switches chats / unmounts.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const handleSendMessage = useCallback(
    async (text) => {
      setError(null);

      const userMsg = { id: Date.now(), role: 'user', content: text };
      const aiId = Date.now() + 1;
      const aiMsg = { id: aiId, role: 'ai', content: '', streaming: true };

      // Show the user's message and an empty assistant bubble immediately.
      onMessagesChange((prev) => [...prev, userMsg, aiMsg]);
      setIsStreaming(true);

      // Build the OpenAI-format message history from everything so far.
      // (serve.py only reads the last user turn today, but sending full history
      // keeps us correct if the backend starts using it.)
      const history = [
        { role: 'system', content: settings.systemPrompt },
        ...messages
          .filter((m) => m.role === 'user' || m.role === 'ai')
          .map((m) => ({
            role: m.role === 'ai' ? 'assistant' : 'user',
            content: m.content,
          })),
        { role: 'user', content: text },
      ];

      const controller = new AbortController();
      abortRef.current = controller;

      // Append streamed text into the assistant bubble as it arrives.
      const appendToAi = (chunk) => {
        onMessagesChange((prev) =>
          prev.map((m) =>
            m.id === aiId ? { ...m, content: m.content + chunk } : m
          )
        );
      };

      try {
        await streamChat({
          baseUrl: settings.baseUrl,
          model: settings.model,
          messages: history,
          onToken: appendToAi,
          signal: controller.signal,
        });

        // Mark the bubble done, then fetch the retrieval sources for grounding.
        onMessagesChange((prev) =>
          prev.map((m) => (m.id === aiId ? { ...m, streaming: false } : m))
        );

        const sources = await getSources(settings.baseUrl, text);
        if (sources.length) {
          onMessagesChange((prev) =>
            prev.map((m) => (m.id === aiId ? { ...m, sources } : m))
          );
        }
      } catch (err) {
        if (err?.name === 'AbortError') {
          onMessagesChange((prev) =>
            prev.map((m) =>
              m.id === aiId
                ? { ...m, streaming: false, content: m.content || '_(stopped)_' }
                : m
            )
          );
        } else {
          setError(err.message || String(err));
          // Drop the empty assistant bubble on a hard failure.
          onMessagesChange((prev) => prev.filter((m) => m.id !== aiId));
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [messages, settings, onMessagesChange]
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const visible = messages.filter((m) => m.role !== 'system');

  return (
    <main className="chat-area">
      <div className="chat-header glass-panel">
        <h2 className="chat-title">{session.title || 'New Chat'}</h2>
        <span className="chat-endpoint" title="Backend endpoint">
          {settings.model} · {settings.baseUrl ? settings.baseUrl.replace(/^https?:\/\//, '') : 'same-origin'}
        </span>
      </div>

      <div className="messages-container">
        <div className="messages-list">
          {visible.length === 0 && (
            <div className="empty-state">
              <p>Ask a question about the MakerSpace knowledge base.</p>
            </div>
          )}
          {visible.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {error && (
            <div className="chat-error" role="alert">
              ⚠ {error}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="input-container">
        <ChatInput
          onSendMessage={handleSendMessage}
          onStop={handleStop}
          isStreaming={isStreaming}
        />
      </div>
    </main>
  );
}

export default ChatArea;
