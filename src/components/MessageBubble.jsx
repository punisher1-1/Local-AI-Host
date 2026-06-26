import React from 'react';
import '../styles/MessageBubble.css';

function MessageBubble({ message }) {
  const isUser = message.role === 'user';
  const sources = message.sources || [];

  return (
    <div className={`message-wrapper ${isUser ? 'user' : 'ai'}`}>
      {!isUser && (
        <div className="avatar ai-avatar">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2a2 2 0 0 1 2 2c0 1.1-.9 2-2 2s-2-.9-2-2 .9-2 2-2zm0 14c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3zM5.5 8.5C4.12 8.5 3 9.62 3 11s1.12 2.5 2.5 2.5 2.5-1.12 2.5-2.5-1.12-2.5-2.5-2.5zm13 0c-1.38 0-2.5 1.12-2.5 2.5s1.12 2.5 2.5 2.5 2.5-1.12 2.5-2.5-1.12-2.5-2.5-2.5z"></path>
            <path d="m8.5 14.5 7-9"></path>
            <path d="m15.5 14.5-7-9"></path>
          </svg>
        </div>
      )}

      <div className="message-content glass-panel">
        <p>
          {message.content}
          {/* Blinking cursor while this bubble is still streaming. */}
          {message.streaming && <span className="stream-cursor">▍</span>}
        </p>

        {/* Retrieval grounding: which KB chunks the answer was built from. */}
        {sources.length > 0 && (
          <div className="message-sources">
            <span className="sources-label">Sources</span>
            <ul>
              {sources.map((s, i) => (
                <li key={i} title={s.text || ''}>
                  {(s.name || 'chunk')}{' '}
                  {typeof s.score === 'number' && (
                    <span className="source-score">({s.score})</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {isUser && (
        <div className="avatar user-avatar">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
        </div>
      )}
    </div>
  );
}

export default MessageBubble;
