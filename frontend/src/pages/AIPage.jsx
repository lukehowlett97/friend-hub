import React, { useState, useEffect, useCallback, useRef } from 'react';
import { apiFetch } from '../api/client';
import DraftActionCard from '../components/AI/DraftActionCard';
import { acceptDraftAction, rejectDraftAction } from '../services/api';
import './FeaturePages.css';

// ── Memory Entry Card ────────────────────────────────────────────────────────

function MemoryEntryCard({ memory }) {
  const typeColors = {
    daily_summary: '#3b82f6',
    weekly_summary: '#3b82f6',
    decision: '#10b981',
    unresolved_plan: '#f59e0b',
    funny_moment: '#ec4899',
    user_preference: '#8b5cf6',
    suggestion_context: '#6b7280',
  };

  const color = typeColors[memory.memory_type] || '#6b7280';

  return (
    <div className="ai-memory-card" style={{ borderLeftColor: color }}>
      <div className="ai-memory-header">
        <span className="ai-memory-type" style={{ backgroundColor: color }}>
          {memory.memory_type.replace(/_/g, ' ')}
        </span>
        <span className="ai-memory-date">
          {new Date(memory.created_at).toLocaleDateString()}
        </span>
      </div>
      {memory.title && (
        <h4 className="ai-memory-title">{memory.title}</h4>
      )}
      <p className="ai-memory-content">{memory.content}</p>
      {memory.tags && memory.tags.length > 0 && (
        <div className="ai-memory-tags">
          {memory.tags.map((tag, i) => (
            <span key={i} className="ai-tag">#{tag}</span>
          ))}
        </div>
      )}
      {memory.confidence !== null && (
        <div className="ai-confidence">
          Confidence: {Math.round(memory.confidence * 100)}%
        </div>
      )}
    </div>
  );
}

// ── Suggestion Card ──────────────────────────────────────────────────────────

function SuggestionCard({ suggestion, onAccept, onReject, isLoading }) {
  const statusColors = {
    pending: '#f59e0b',
    accepted: '#10b981',
    rejected: '#ef4444',
    archived: '#6b7280',
  };

  const status = suggestion.status || 'pending';
  const color = statusColors[status] || '#6b7280';
  const isPending = status === 'pending';

  return (
    <div className="ai-suggestion-card" style={{ borderLeftColor: color }}>
      <div className="ai-suggestion-header">
        <span className="ai-suggestion-type" style={{ backgroundColor: color }}>
          {suggestion.suggestion_type}
        </span>
        <span className="ai-suggestion-status">{status}</span>
      </div>
      <h4 className="ai-suggestion-title">{suggestion.title}</h4>
      {suggestion.body && (
        <p className="ai-suggestion-body">{suggestion.body}</p>
      )}
      {suggestion.proposed_hub_item_type && (
        <div className="ai-suggestion-hub-item">
          Would create: {suggestion.proposed_hub_item_type}
        </div>
      )}
      {isPending && !isLoading && (
        <div className="ai-suggestion-actions">
          <button
            className="btn btn-primary btn-sm"
            onClick={() => onAccept(suggestion.id)}
          >
            Accept
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => onReject(suggestion.id)}
          >
            Reject
          </button>
        </div>
      )}
      {isLoading && (
        <div className="ai-suggestion-loading">Processing...</div>
      )}
      {!isPending && (
        <div className="ai-suggestion-result">
          {status === 'accepted' && suggestion.created_hub_item_id && (
            <span>Accepted — Created Hub Item</span>
          )}
          {status === 'accepted' && !suggestion.created_hub_item_id && (
            <span>Accepted</span>
          )}
          {status === 'rejected' && <span>Rejected</span>}
        </div>
      )}
    </div>
  );
}

// ── Chat Message ─────────────────────────────────────────────────────────────

const AI_IMAGE_RE = /\[\[ai-image:((?:https?:\/\/|\/)[^\]]+)\]\]/i;

function ChatMessage({ message, draftStates, onAcceptDraft, onRejectDraft }) {
  const isUser = message.role === 'user';
  const drafts = message.draftActions || [];
  const imageMatch = !isUser && message.content?.match(AI_IMAGE_RE);
  const imageUrl = imageMatch ? imageMatch[1] : null;
  const textContent = imageUrl ? message.content.replace(AI_IMAGE_RE, '').trim() : message.content;

  return (
    <div className={`bot-chat-message ${isUser ? 'user' : 'bot'}`}>
      <div className="bot-chat-avatar">
        {isUser ? '👤' : '🤖'}
      </div>
      <div className="bot-chat-bubble-group">
        <div className="bot-chat-bubble">
          {textContent && <div className="bot-chat-text">{textContent}</div>}
          {imageUrl && (
            <img
              src={imageUrl}
              alt="AI generated"
              style={{ maxWidth: '100%', borderRadius: '8px', marginTop: textContent ? '8px' : '0' }}
            />
          )}
          {message.suggestedActions && message.suggestedActions.length > 0 && (
            <div className="bot-chat-actions">
              {message.suggestedActions.map((action, i) => (
                <button
                  key={i}
                  className="bot-action-btn"
                  onClick={() => message.onActionClick?.(action)}
                >
                  {action}
                </button>
              ))}
            </div>
          )}
          {message.stats && (
            <div className="bot-chat-stats">
              {message.stats.memoryCount > 0 && (
                <span>📝 {message.stats.memoryCount} memories</span>
              )}
              {message.stats.suggestionCount > 0 && (
                <span>💡 {message.stats.suggestionCount} suggestions</span>
              )}
            </div>
          )}
        </div>

        {/* Draft action cards — rendered below the reply bubble */}
        {drafts.length > 0 && (
          <div className="bot-chat-drafts">
            {drafts.map(draft => {
              const st = draftStates?.[draft.id] || {};
              // Use the latest version of the draft if the user has already acted on it
              const latestDraft = st.draft ? { ...draft, ...st.draft } : draft;
              return (
                <DraftActionCard
                  key={draft.id}
                  draftAction={latestDraft}
                  onAccept={onAcceptDraft}
                  onReject={onRejectDraft}
                  loading={!!st.loading}
                  error={st.error || null}
                />
              );
            })}
          </div>
        )}
        {message.createdItems?.length > 0 && (
          <div className="bot-chat-created-items">
            {message.createdItems.map((item, i) => (
              <a key={i} href={item.route} className="bot-chat-created-item">
                <span className="bot-chat-created-item__badge">{item.item_type}</span>
                <span className="bot-chat-created-item__title">{item.title}</span>
                <span className="bot-chat-created-item__ref">{item.short_id}</span>
                <span className="bot-chat-created-item__arrow">→</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Hub Bot Lab Page ────────────────────────────────────────────────────

export default function AIPage() {
  const [memories, setMemories] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('chat');
  const [processingIds, setProcessingIds] = useState(new Set());
  
  // Agent Runs state
  const [agentRuns, setAgentRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runDetailLoading, setRunDetailLoading] = useState(false);
  
  // Dry run toggle
  const [dryRun, setDryRun] = useState(false);
  
  // Per-draft-action state: { [draftId]: { loading, error, draft } }
  // draft is the latest version of the action (updated after accept/reject).
  const [draftStates, setDraftStates] = useState({});

  // Chat state
  const [chatMessages, setChatMessages] = useState([
    {
      id: 'welcome',
      role: 'bot',
      content: '🤖 Welcome to Hub Bot Lab!\n\nNo @hub needed — just use slash commands or plain text:\n• /event — Create an event\n• /poll — Create a poll\n• /image — Generate an image\n• /idea — Log an idea\n• /remind — Set a reminder\n• "summarise" — Generate a chat summary',
      suggestedActions: [
        '/event',
        '/poll',
        '/image',
        '/idea',
        '/remind',
        'summarise',
      ],
    },
  ]);
  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const chatEndRef = useRef(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages]);

  const fetchMemories = useCallback(async () => {
    try {
      const response = await apiFetch('/api/v1/ai/memories?limit=20');
      if (response.ok) {
        const data = await response.json();
        setMemories(data.memories || []);
      }
    } catch (err) {
      console.error('Failed to fetch memories:', err);
    }
  }, []);

  const fetchSuggestions = useCallback(async () => {
    try {
      const response = await apiFetch('/api/v1/ai/suggestions?limit=20');
      if (response.ok) {
        const data = await response.json();
        setSuggestions(data.suggestions || []);
      }
    } catch (err) {
      console.error('Failed to fetch suggestions:', err);
    }
  }, []);

  useEffect(() => {
    fetchMemories();
    fetchSuggestions();
  }, [fetchMemories, fetchSuggestions]);

  const fetchAgentRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const response = await apiFetch('/api/v1/ai/agent-runs?limit=50');
      if (response.ok) {
        const data = await response.json();
        setAgentRuns(data.runs || []);
      }
    } catch (err) {
      console.error('Failed to fetch agent runs:', err);
    } finally {
      setRunsLoading(false);
    }
  }, []);

  const fetchAgentRunDetail = useCallback(async (runId) => {
    setRunDetailLoading(true);
    try {
      const response = await apiFetch(`/api/v1/ai/agent-runs/${runId}`);
      if (response.ok) {
        const data = await response.json();
        setSelectedRun(data);
      }
    } catch (err) {
      console.error('Failed to fetch run detail:', err);
    } finally {
      setRunDetailLoading(false);
    }
  }, []);

  const handleSelectRun = (runId) => {
    setSelectedRun(null);
    fetchAgentRunDetail(runId);
  };

  const handleBackToRuns = () => {
    setSelectedRun(null);
  };

  useEffect(() => {
    if (activeTab === 'runs') {
      fetchAgentRuns();
    }
  }, [activeTab, fetchAgentRuns]);

  const handleSendMessage = async (messageText) => {
    const text = messageText || inputValue.trim();
    if (!text || isSending) return;

    setIsSending(true);
    setInputValue('');
    setError(null);

    // Add user message
    const userMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
    };
    setChatMessages(prev => [...prev, userMessage]);

    try {
      // Include dry_run flag in the request
      const response = await apiFetch('/api/v1/ai/hub-bot-chat', {
        method: 'POST',
        body: JSON.stringify({ message: text, dry_run: dryRun }),
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to send message');
      }

      const data = await response.json();

      // Add bot response, carrying any draft actions proposed during this run
      const botMessage = {
        id: (Date.now() + 1).toString(),
        role: 'bot',
        content: data.reply,
        suggestedActions: data.suggested_actions || [],
        draftActions: data.draft_actions || [],
        createdItems: data.created_items || [],
        stats: {
          memoryCount: data.created_memory_count,
          suggestionCount: data.created_suggestion_count,
        },
        onActionClick: (action) => handleSendMessage(action),
      };
      setChatMessages(prev => [...prev, botMessage]);

      // Refresh data if new memories or suggestions were created
      if (data.created_memory_count > 0 || data.created_suggestion_count > 0) {
        await fetchMemories();
        await fetchSuggestions();
      }
    } catch (err) {
      setError(err.message);
      // Add error message
      setChatMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'bot',
        content: `⚠️ Error: ${err.message}`,
      }]);
    } finally {
      setIsSending(false);
    }
  };

  const handleAcceptSuggestion = async (suggestionId) => {
    setProcessingIds(prev => new Set([...prev, suggestionId]));
    try {
      const response = await apiFetch(`/api/v1/ai/suggestions/${suggestionId}/accept`, {
        method: 'POST',
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to accept suggestion');
      }

      const data = await response.json();
      if (data.success) {
        setSuggestions(prev => prev.map(s => 
          s.id === suggestionId ? data.suggestion : s
        ));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setProcessingIds(prev => {
        const next = new Set(prev);
        next.delete(suggestionId);
        return next;
      });
    }
  };

  const handleRejectSuggestion = async (suggestionId) => {
    setProcessingIds(prev => new Set([...prev, suggestionId]));
    try {
      const response = await apiFetch(`/api/v1/ai/suggestions/${suggestionId}/reject`, {
        method: 'POST',
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to reject suggestion');
      }

      const data = await response.json();
      if (data.success) {
        setSuggestions(prev => prev.map(s => 
          s.id === suggestionId ? data.suggestion : s
        ));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setProcessingIds(prev => {
        const next = new Set(prev);
        next.delete(suggestionId);
        return next;
      });
    }
  };

  const handleAcceptDraft = async (draftId) => {
    setDraftStates(prev => ({ ...prev, [draftId]: { ...prev[draftId], loading: true, error: null } }));
    try {
      const data = await acceptDraftAction(draftId);
      setDraftStates(prev => ({
        ...prev,
        [draftId]: { loading: false, error: null, draft: data.draft_action },
      }));
      // Also update the draft inside chatMessages so navigation persists through re-renders
      setChatMessages(prev => prev.map(msg => {
        if (!msg.draftActions) return msg;
        return {
          ...msg,
          draftActions: msg.draftActions.map(d =>
            d.id === draftId ? { ...d, ...data.draft_action } : d
          ),
        };
      }));
    } catch (err) {
      setDraftStates(prev => ({
        ...prev,
        [draftId]: { ...prev[draftId], loading: false, error: err.message },
      }));
    }
  };

  const handleRejectDraft = async (draftId) => {
    setDraftStates(prev => ({ ...prev, [draftId]: { ...prev[draftId], loading: true, error: null } }));
    try {
      const data = await rejectDraftAction(draftId);
      setDraftStates(prev => ({
        ...prev,
        [draftId]: { loading: false, error: null, draft: data.draft_action },
      }));
      setChatMessages(prev => prev.map(msg => {
        if (!msg.draftActions) return msg;
        return {
          ...msg,
          draftActions: msg.draftActions.map(d =>
            d.id === draftId ? { ...d, ...data.draft_action } : d
          ),
        };
      }));
    } catch (err) {
      setDraftStates(prev => ({
        ...prev,
        [draftId]: { ...prev[draftId], loading: false, error: err.message },
      }));
    }
  };

  const pendingSuggestions = suggestions.filter(s => s.status === 'pending');
  const processedSuggestions = suggestions.filter(s => s.status !== 'pending');

  const quickCommands = [
    { label: '📅 /event', command: '/event' },
    { label: '📊 /poll', command: '/poll' },
    { label: '🖼 /image', command: '/image' },
    { label: '💡 /idea', command: '/idea' },
    { label: '⏰ /remind', command: '/remind' },
    { label: '📝 Summarise', command: 'summarise' },
  ];

  return (
    <div className="page page-ai page-hub-bot-lab">
      <div className="page-header">
        <h1>🤖 Hub Bot Lab</h1>
        <p className="page-subtitle">
          Testing interface for Friend Hub bot commands
        </p>
      </div>

      {error && (
        <div className="error-banner">{error}</div>
      )}

      {/* Tabs */}
      <div className="ai-tabs">
        <button
          className={`ai-tab ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          Chat
        </button>
        <button
          className={`ai-tab ${activeTab === 'suggestions' ? 'active' : ''}`}
          onClick={() => setActiveTab('suggestions')}
        >
          Suggestions ({pendingSuggestions.length})
        </button>
        <button
          className={`ai-tab ${activeTab === 'memories' ? 'active' : ''}`}
          onClick={() => setActiveTab('memories')}
        >
          Memories ({memories.length})
        </button>
        <button
          className={`ai-tab ${activeTab === 'history' ? 'active' : ''}`}
          onClick={() => setActiveTab('history')}
        >
          History ({processedSuggestions.length})
        </button>
        <button
          className={`ai-tab ${activeTab === 'runs' ? 'active' : ''}`}
          onClick={() => setActiveTab('runs')}
        >
          Agent Runs ({agentRuns.length})
        </button>
      </div>

      {/* Tab Content */}
      <div className="ai-tab-content">
        {activeTab === 'chat' && (
          <div className="bot-chat-container">
            {/* Dry Run Toggle */}
            <div className="dry-run-toggle">
              <label className="dry-run-label">
                <input
                  type="checkbox"
                  checked={dryRun}
                  onChange={e => setDryRun(e.target.checked)}
                />
                <span className="dry-run-text">Dry Run (preview only, no saves)</span>
              </label>
            </div>
            <div className="bot-chat-messages">
              {chatMessages.map(msg => (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  draftStates={draftStates}
                  onAcceptDraft={handleAcceptDraft}
                  onRejectDraft={handleRejectDraft}
                />
              ))}
              {isSending && (
                <div className="bot-chat-message bot">
                  <div className="bot-chat-avatar">🤖</div>
                  <div className="bot-chat-bubble">
                    <div className="bot-chat-typing">Thinking...</div>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Quick Commands */}
            <div className="bot-quick-commands">
              {quickCommands.map((cmd, i) => (
                <button
                  key={i}
                  className="quick-command-btn"
                  onClick={() => handleSendMessage(cmd.command)}
                  disabled={isSending}
                >
                  {cmd.label}
                </button>
              ))}
            </div>

            {/* Input */}
            <div className="bot-chat-input-area">
              <input
                className="bot-chat-input"
                type="text"
                placeholder="Type a command..."
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
                disabled={isSending}
              />
              <button
                className="btn btn-primary bot-send-btn"
                onClick={() => handleSendMessage()}
                disabled={isSending || !inputValue.trim()}
              >
                Send
              </button>
            </div>
          </div>
        )}

        {activeTab === 'suggestions' && (
          <div className="ai-suggestions-list">
            {pendingSuggestions.length === 0 ? (
              <div className="ai-empty-state">
                <p>No pending suggestions.</p>
                <p className="ai-empty-hint">
                  Use "suggest poll" in the Chat tab to create suggestions.
                </p>
              </div>
            ) : (
              pendingSuggestions.map(suggestion => (
                <SuggestionCard
                  key={suggestion.id}
                  suggestion={suggestion}
                  onAccept={handleAcceptSuggestion}
                  onReject={handleRejectSuggestion}
                  isLoading={processingIds.has(suggestion.id)}
                />
              ))
            )}
          </div>
        )}

        {activeTab === 'memories' && (
          <div className="ai-memories-list">
            {memories.length === 0 ? (
              <div className="ai-empty-state">
                <p>No memories yet.</p>
                <p className="ai-empty-hint">
                  Use "summarise" in the Chat tab to create memories.
                </p>
              </div>
            ) : (
              memories.map(memory => (
                <MemoryEntryCard key={memory.id} memory={memory} />
              ))
            )}
          </div>
        )}

        {activeTab === 'history' && (
          <div className="ai-history-list">
            {processedSuggestions.length === 0 ? (
              <div className="ai-empty-state">
                <p>No history yet.</p>
                <p className="ai-empty-hint">
                  Accepted and rejected suggestions will appear here.
                </p>
              </div>
            ) : (
              processedSuggestions.map(suggestion => (
                <SuggestionCard
                  key={suggestion.id}
                  suggestion={suggestion}
                  onAccept={() => {}}
                  onReject={() => {}}
                  isLoading={false}
                />
              ))
            )}
          </div>
        )}

        {activeTab === 'runs' && (
          <div className="ai-runs-container">
            {selectedRun ? (
              /* Run Detail View */
              <div className="ai-run-detail">
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={handleBackToRuns}
                  style={{ marginBottom: '12px' }}
                >
                  ← Back to runs
                </button>
                
                <div className="ai-run-header">
                  <span className={`ai-run-status status-${selectedRun.status}`}>
                    {selectedRun.status}
                  </span>
                  <span className="ai-run-mode">{selectedRun.mode}</span>
                  <span className="ai-run-provider">{selectedRun.provider}</span>
                  {selectedRun.model && <span className="ai-run-model">{selectedRun.model}</span>}
                </div>
                
                <div className="ai-run-meta">
                  <span>Duration: {selectedRun.duration_ms ? `${selectedRun.duration_ms}ms` : 'N/A'}</span>
                  <span>Created: {selectedRun.created_at ? new Date(selectedRun.created_at).toLocaleString() : 'N/A'}</span>
                  {selectedRun.completed_at && (
                    <span>Completed: {new Date(selectedRun.completed_at).toLocaleString()}</span>
                  )}
                </div>

                {selectedRun.user_message && (
                  <div className="ai-run-section">
                    <button
                      className="ai-run-section-toggle"
                      onClick={() => {
                        const el = document.getElementById('run-user-msg');
                        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
                      }}
                    >
                      ▶ User Message
                    </button>
                    <div id="run-user-msg" className="ai-run-section-content">
                      <pre>{selectedRun.user_message}</pre>
                    </div>
                  </div>
                )}

                <div className="ai-run-section">
                  <button
                    className="ai-run-section-toggle"
                    onClick={() => {
                      const el = document.getElementById('run-prompt');
                      if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
                    }}
                  >
                    ▶ Prompt
                  </button>
                  <div id="run-prompt" className="ai-run-section-content" style={{ display: 'none' }}>
                    <pre>{selectedRun.prompt_text || '(no prompt)'}</pre>
                  </div>
                </div>

                <div className="ai-run-section">
                  <button
                    className="ai-run-section-toggle"
                    onClick={() => {
                      const el = document.getElementById('run-raw');
                      if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
                    }}
                  >
                    ▶ Raw Response
                  </button>
                  <div id="run-raw" className="ai-run-section-content" style={{ display: 'none' }}>
                    <pre>{selectedRun.raw_response || '(no response)'}</pre>
                  </div>
                </div>

                <div className="ai-run-section">
                  <button
                    className="ai-run-section-toggle"
                    onClick={() => {
                      const el = document.getElementById('run-parsed');
                      if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
                    }}
                  >
                    ▶ Parsed Response
                  </button>
                  <div id="run-parsed" className="ai-run-section-content" style={{ display: 'none' }}>
                    <pre>{JSON.stringify(selectedRun.parsed_response, null, 2) || '(none)'}</pre>
                  </div>
                </div>

                {selectedRun.validation_errors && selectedRun.validation_errors.length > 0 && (
                  <div className="ai-run-section">
                    <button
                      className="ai-run-section-toggle section-error"
                      onClick={() => {
                        const el = document.getElementById('run-errors');
                        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
                      }}
                    >
                      ▶ Validation Errors ({selectedRun.validation_errors.length})
                    </button>
                    <div id="run-errors" className="ai-run-section-content" style={{ display: 'none' }}>
                      <pre className="error-text">{JSON.stringify(selectedRun.validation_errors, null, 2)}</pre>
                    </div>
                  </div>
                )}

                {selectedRun.created_memory_ids && selectedRun.created_memory_ids.length > 0 && (
                  <div className="ai-run-section">
                    <button
                      className="ai-run-section-toggle"
                      onClick={() => {
                        const el = document.getElementById('run-memories');
                        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
                      }}
                    >
                      ▶ Created Memories ({selectedRun.created_memory_ids.length})
                    </button>
                    <div id="run-memories" className="ai-run-section-content" style={{ display: 'none' }}>
                      <pre>{JSON.stringify(selectedRun.created_memory_ids, null, 2)}</pre>
                    </div>
                  </div>
                )}

                {selectedRun.created_suggestion_ids && selectedRun.created_suggestion_ids.length > 0 && (
                  <div className="ai-run-section">
                    <button
                      className="ai-run-section-toggle"
                      onClick={() => {
                        const el = document.getElementById('run-suggestions');
                        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
                      }}
                    >
                      ▶ Created Suggestions ({selectedRun.created_suggestion_ids.length})
                    </button>
                    <div id="run-suggestions" className="ai-run-section-content" style={{ display: 'none' }}>
                      <pre>{JSON.stringify(selectedRun.created_suggestion_ids, null, 2)}</pre>
                    </div>
                  </div>
                )}

                {selectedRun.error_message && (
                  <div className="ai-run-section">
                    <button
                      className="ai-run-section-toggle section-error"
                      onClick={() => {
                        const el = document.getElementById('run-error');
                        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
                      }}
                    >
                      ▶ Error
                    </button>
                    <div id="run-error" className="ai-run-section-content" style={{ display: 'none' }}>
                      <pre className="error-text">{selectedRun.error_message}</pre>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              /* Runs List View */
              <>
                {runsLoading ? (
                  <div className="ai-empty-state">
                    <p>Loading runs...</p>
                  </div>
                ) : agentRuns.length === 0 ? (
                  <div className="ai-empty-state">
                    <p>No agent runs yet.</p>
                    <p className="ai-empty-hint">
                      Use "summarise" in the Chat tab to create runs.
                    </p>
                  </div>
                ) : (
                  <div className="ai-runs-list">
                    {agentRuns.map(run => (
                      <div
                        key={run.id}
                        className="ai-run-card"
                        onClick={() => handleSelectRun(run.id)}
                      >
                        <div className="ai-run-card-header">
                          <span className={`ai-run-status status-${run.status}`}>
                            {run.status}
                          </span>
                          <span className="ai-run-duration">
                            {run.duration_ms ? `${run.duration_ms}ms` : '-'}
                          </span>
                        </div>
                        <div className="ai-run-card-body">
                          <span className="ai-run-mode">{run.mode}</span>
                          <span className="ai-run-provider">{run.provider}</span>
                          {run.model && <span className="ai-run-model">{run.model}</span>}
                        </div>
                        <div className="ai-run-card-footer">
                          <span className="ai-run-time">
                            {run.created_at ? new Date(run.created_at).toLocaleString() : ''}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <style jsx>{`
        .page-hub-bot-lab {
          width: 100%;
          max-width: 100%;
          display: flex;
          flex-direction: column;
          height: 100%;
          padding: 0;
          margin: 0;
        }

        .page-hub-bot-lab .page-header {
          flex-shrink: 0;
          padding: 16px 24px;
        }

        .page-hub-bot-lab .error-banner {
          flex-shrink: 0;
          margin: 0;
          border-radius: 0;
        }

        /* Chat Container */
        .bot-chat-container {
          display: flex;
          flex-direction: column;
          flex: 1;
          background: var(--card-bg, #fff);
          border: none;
          border-radius: 0;
          overflow: hidden;
          margin: 0;
        }

        .bot-chat-messages {
          flex: 1;
          overflow-y: auto;
          padding: 20px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .bot-chat-message {
          display: flex;
          gap: 8px;
          align-items: flex-start;
        }

        .bot-chat-message.user {
          flex-direction: row-reverse;
        }

        .bot-chat-avatar {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 16px;
          background: var(--bg-secondary, #f9fafb);
          flex-shrink: 0;
        }

        .bot-chat-bubble {
          max-width: 85%;
          padding: 12px 16px;
          background: var(--bg-secondary, #f9fafb);
          border-radius: 12px;
          white-space: pre-wrap;
          word-wrap: break-word;
        }

        .bot-chat-bubble-group {
          display: flex;
          flex-direction: column;
          max-width: 85%;
          gap: 0;
        }

        .bot-chat-message.user .bot-chat-bubble-group {
          align-items: flex-end;
        }

        .bot-chat-message.user .bot-chat-bubble {
          background: var(--primary-color, #3b82f6);
          color: #fff;
        }

        /* Draft cards sit below the reply bubble, full-width within the group */
        .bot-chat-drafts {
          display: flex;
          flex-direction: column;
          gap: 6px;
          width: 100%;
        }

        .bot-chat-text {
          font-size: 14px;
          line-height: 1.5;
        }

        .bot-chat-typing {
          color: var(--text-secondary, #6b7280);
          font-style: italic;
        }

        .bot-chat-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 10px;
        }

        .bot-action-btn {
          padding: 4px 10px;
          font-size: 12px;
          background: var(--card-bg, #fff);
          border: 1px solid var(--border-color, #e5e7eb);
          border-radius: 14px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .bot-action-btn:hover {
          background: var(--primary-color, #3b82f6);
          color: #fff;
          border-color: var(--primary-color, #3b82f6);
        }

        .bot-chat-stats {
          display: flex;
          gap: 12px;
          margin-top: 8px;
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
        }

        /* Quick Commands */
        .bot-quick-commands {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          padding: 8px 16px;
          border-top: 1px solid var(--border-color, #e5e7eb);
          background: var(--bg-secondary, #f9fafb);
        }

        .quick-command-btn {
          padding: 6px 12px;
          font-size: 12px;
          background: var(--card-bg, #fff);
          border: 1px solid var(--border-color, #e5e7eb);
          border-radius: 16px;
          cursor: pointer;
          transition: all 0.2s;
          white-space: nowrap;
        }

        .quick-command-btn:hover:not(:disabled) {
          background: var(--primary-color, #3b82f6);
          color: #fff;
          border-color: var(--primary-color, #3b82f6);
        }

        .quick-command-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        /* Input Area */
        .bot-chat-input-area {
          display: flex;
          gap: 8px;
          padding: 12px 16px;
          border-top: 1px solid var(--border-color, #e5e7eb);
        }

        .bot-chat-input {
          flex: 1;
          padding: 10px 14px;
          border: 1px solid var(--border-color, #e5e7eb);
          border-radius: 20px;
          font-size: 14px;
          outline: none;
          transition: border-color 0.2s;
        }

        .bot-chat-input:focus {
          border-color: var(--primary-color, #3b82f6);
        }

        .bot-send-btn {
          border-radius: 20px;
          padding: 10px 20px;
        }

        /* Tabs */
        .ai-tabs {
          display: flex;
          gap: 4px;
          border-bottom: 1px solid var(--border-color, #e5e7eb);
          margin-bottom: 0;
          padding: 0 16px;
          background: var(--card-bg, #fff);
          overflow-x: auto;
          -webkit-overflow-scrolling: touch;
          flex-shrink: 0;
        }

        .ai-tab {
          padding: 10px 16px;
          background: none;
          border: none;
          border-bottom: 2px solid transparent;
          cursor: pointer;
          font-size: 14px;
          color: var(--text-secondary, #6b7280);
          transition: all 0.2s;
        }

        .ai-tab:hover {
          color: var(--text-primary, #374151);
        }

        .ai-tab.active {
          color: var(--primary-color, #3b82f6);
          border-bottom-color: var(--primary-color, #3b82f6);
        }

        .ai-tab-content {
          flex: 1;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          background: var(--card-bg, #fff);
        }

        /* Suggestions & Memories Lists */
        .ai-suggestions-list,
        .ai-memories-list,
        .ai-history-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
          flex: 1;
          overflow-y: auto;
          padding: 16px;
        }

        .ai-suggestion-card,
        .ai-memory-card {
          background: var(--card-bg, #fff);
          border: 1px solid var(--border-color, #e5e7eb);
          border-left: 4px solid;
          border-radius: 8px;
          padding: 16px;
        }

        .ai-suggestion-header,
        .ai-memory-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }

        .ai-suggestion-type,
        .ai-memory-type {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 12px;
          font-weight: 600;
          color: #fff;
          text-transform: uppercase;
        }

        .ai-suggestion-status,
        .ai-memory-date {
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
        }

        .ai-suggestion-title,
        .ai-memory-title {
          margin: 0 0 8px;
          font-size: 16px;
        }

        .ai-suggestion-body,
        .ai-memory-content {
          margin: 0 0 12px;
          font-size: 14px;
          color: var(--text-primary, #374151);
          line-height: 1.5;
        }

        .ai-suggestion-hub-item {
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
          margin-bottom: 12px;
        }

        .ai-suggestion-actions {
          display: flex;
          gap: 8px;
        }

        .ai-suggestion-result {
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
          font-style: italic;
        }

        .ai-suggestion-loading {
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
        }

        .ai-memory-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
          margin-bottom: 8px;
        }

        .ai-tag {
          display: inline-block;
          padding: 2px 6px;
          background: var(--bg-secondary, #f9fafb);
          border-radius: 4px;
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
        }

        .ai-confidence {
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
        }

        .ai-empty-state {
          text-align: center;
          padding: 60px 20px;
          color: var(--text-secondary, #6b7280);
          flex: 1;
          display: flex;
          flex-direction: column;
          justify-content: center;
          align-items: center;
        }

        .ai-empty-hint {
          font-size: 13px;
          margin-top: 4px;
        }

        .btn-sm {
          padding: 6px 12px;
          font-size: 13px;
        }

        /* Dry Run Toggle */
        .dry-run-toggle {
          padding: 8px 16px;
          border-bottom: 1px solid var(--border-color, #e5e7eb);
          background: var(--bg-secondary, #f9fafb);
        }

        .dry-run-label {
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
          font-size: 13px;
          color: var(--text-secondary, #6b7280);
        }

        .dry-run-label input[type="checkbox"] {
          cursor: pointer;
        }

        .dry-run-text {
          user-select: none;
        }

        /* Agent Runs List */
        .ai-runs-container {
          display: flex;
          flex-direction: column;
          gap: 12px;
          flex: 1;
          overflow-y: auto;
          padding: 16px;
        }

        .ai-runs-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          flex: 1;
        }

        .ai-run-card {
          background: var(--card-bg, #fff);
          border: 1px solid var(--border-color, #e5e7eb);
          border-radius: 8px;
          padding: 12px 16px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .ai-run-card:hover {
          border-color: var(--primary-color, #3b82f6);
          box-shadow: 0 1px 4px rgba(0,0,0,0.1);
        }

        .ai-run-card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 6px;
        }

        .ai-run-status {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          color: #fff;
        }

        .status-running { background: #f59e0b; }
        .status-completed { background: #10b981; }
        .status-failed { background: #ef4444; }

        .ai-run-duration {
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
          font-family: monospace;
        }

        .ai-run-card-body {
          display: flex;
          gap: 8px;
          align-items: center;
          margin-bottom: 4px;
        }

        .ai-run-mode {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary, #374151);
        }

        .ai-run-provider,
        .ai-run-model {
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
        }

        .ai-run-card-footer {
          font-size: 11px;
          color: var(--text-secondary, #9ca3af);
        }

        /* Run Detail View */
        .ai-run-detail {
          display: flex;
          flex-direction: column;
          gap: 8px;
          flex: 1;
          overflow-y: auto;
          padding: 16px;
        }

        .ai-run-header {
          display: flex;
          gap: 8px;
          align-items: center;
          flex-wrap: wrap;
        }

        .ai-run-meta {
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          font-size: 12px;
          color: var(--text-secondary, #6b7280);
          margin-bottom: 8px;
        }

        .ai-run-section {
          border: 1px solid var(--border-color, #e5e7eb);
          border-radius: 8px;
          overflow: hidden;
        }

        .ai-run-section-toggle {
          width: 100%;
          padding: 10px 12px;
          background: var(--bg-secondary, #f9fafb);
          border: none;
          border-bottom: 1px solid var(--border-color, #e5e7eb);
          cursor: pointer;
          text-align: left;
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary, #374151);
          transition: background 0.2s;
        }

        .ai-run-section-toggle:hover {
          background: var(--border-color, #e5e7eb);
        }

        .ai-run-section-toggle.section-error {
          color: #ef4444;
        }

        .ai-run-section-content {
          padding: 12px;
        }

        .ai-run-section-content pre {
          margin: 0;
          font-size: 12px;
          line-height: 1.5;
          white-space: pre-wrap;
          word-break: break-all;
          font-family: monospace;
          max-height: 300px;
          overflow-y: auto;
        }

        .ai-run-section-content .error-text {
          color: #ef4444;
        }

        @media (max-width: 768px) {
          .page-hub-bot-lab .page-header {
            padding: 12px;
          }

          .bot-chat-container {
            min-height: calc(100vh - 250px);
          }

          .bot-chat-messages {
            padding: 16px;
          }

          .bot-chat-bubble {
            max-width: 90%;
          }

          .ai-tabs {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
          }

          .ai-tab {
            white-space: nowrap;
            padding: 10px 12px;
            font-size: 13px;
            flex-shrink: 0;
          }

          .ai-suggestions-list,
          .ai-memories-list,
          .ai-history-list,
          .ai-runs-container {
            padding: 12px;
            gap: 10px;
          }

          .ai-run-section-content pre {
            font-size: 11px;
          }
        }

        @media (max-width: 480px) {
          .bot-chat-bubble {
            max-width: 95%;
          }

          .ai-suggestion-card,
          .ai-memory-card {
            padding: 12px;
          }

          .ai-tab {
            padding: 8px 10px;
            font-size: 12px;
          }
        }
      `}</style>
    </div>
  );
}