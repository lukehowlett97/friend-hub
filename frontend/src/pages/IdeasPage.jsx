import React, { useEffect, useMemo, useState } from 'react';
import CreatorCard from '../components/Planning/CreatorCard.jsx';
import EngagementPanel from '../components/Planning/EngagementPanel.jsx';
import HubItemCardMeta from '../components/Planning/HubItemCardMeta.jsx';
import { createIdea, deleteIdea, fetchIdeas, pinHubItem, sendHubItemToChat, updateIdea } from '../services/api.js';
import { useAuth } from '../auth/AuthProvider.jsx';
import './FeaturePages.css';

const STATUSES = ['maybe', 'planned', 'done', 'rejected'];

const IdeasPage = ({ onNavigate }) => {
  const { user } = useAuth();
  const [ideas, setIdeas] = useState([]);
  const [filter, setFilter] = useState('all');
  const [error, setError] = useState(null);
  const [form, setForm] = useState({ title: '', description: '', category: 'general', status: 'maybe' });

  const loadIdeas = () => {
    fetchIdeas()
      .then((data) => {
        setIdeas(data.ideas || []);
        setError(null);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(() => {
    loadIdeas();
  }, []);

  const visibleIdeas = useMemo(
    () => ideas.filter((idea) => filter === 'all' || idea.status === filter),
    [ideas, filter],
  );

  const submitIdea = async (event) => {
    event.preventDefault();
    try {
      await createIdea(form);
      setForm({ title: '', description: '', category: form.category, status: 'maybe' });
      loadIdeas();
    } catch (err) {
      setError(err.message);
    }
  };

  const changeStatus = async (idea, status) => {
    try {
      await updateIdea(idea.id, { status });
      loadIdeas();
    } catch (err) {
      setError(err.message);
    }
  };

  const editIdea = async (idea) => {
    const title = window.prompt('Idea title', idea.title || '');
    if (title === null) return;
    const category = window.prompt('Category', idea.category || 'general');
    if (category === null) return;
    const description = window.prompt('Details', idea.description || '');
    if (description === null) return;
    try {
      await updateIdea(idea.id, { title, category, description });
      loadIdeas();
    } catch (err) {
      setError(err.message);
    }
  };

  const removeIdea = async (idea) => {
    const confirmed = window.confirm(
      `Delete "${idea.title}"?\n\nThis will move the idea to the archive instead of permanently deleting it.`,
    );
    if (!confirmed) return;
    try {
      await deleteIdea(idea.id);
      loadIdeas();
    } catch (err) {
      setError(err.message);
    }
  };

  const togglePin = async (item) => {
    try {
      await pinHubItem(item.id, !item.pinned_to_home);
      loadIdeas();
    } catch (err) {
      setError(err.message);
    }
  };

  const sendToChat = async (item) => {
    await sendHubItemToChat(item.id);
    loadIdeas();
  };

  const prepareChatMessage = (item) => {
    onNavigate?.(`/chat?draft=${encodeURIComponent(item.short_id || '')}`);
  };

  const canDeleteIdea = (idea) => {
    const role = user?.role;
    return role === 'owner' || role === 'admin' || idea.creator?.id === user?.id;
  };

  const canEditIdea = canDeleteIdea;

  return (
    <section className="page feature-page">
      <header className="page-header">
        <h1>Ideas</h1>
        <p className="page-subtitle">Store pub ideas, trips, food places, and random schemes.</p>
      </header>

      <form className="feature-form stacked-form" onSubmit={submitIdea}>
        <input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="Idea title" required />
        <input value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} placeholder="Category" />
        <select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
          {STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
        </select>
        <textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Details" rows="3" />
        <button type="submit">Add Idea</button>
      </form>

      {error && <div className="inline-error">{error}</div>}

      <div className="filter-tabs">
        {['all', ...STATUSES].map((status) => (
          <button key={status} className={filter === status ? 'active' : ''} onClick={() => setFilter(status)}>{status}</button>
        ))}
      </div>

      <div className="feature-list">
        {visibleIdeas.map((idea) => (
          <article key={idea.id} className="planning-card">
            <HubItemCardMeta
              item={idea.hub_item}
              onPin={togglePin}
              onSendToChat={sendToChat}
              onPrepareChatMessage={prepareChatMessage}
              canEdit={canEditIdea(idea)}
              canDelete={canDeleteIdea(idea)}
              onEdit={() => editIdea(idea)}
              onDelete={() => removeIdea(idea)}
              editLabel="Edit idea"
              deleteLabel="Delete idea"
            />
            <div className="planning-card-header">
              <div>
                <span className="eyebrow">{idea.category}</span>
                <h2>{idea.title}</h2>
                {idea.description && <p>{idea.description}</p>}
                <CreatorCard creator={idea.creator} onNavigate={onNavigate} />
              </div>
              <div className="row-actions">
                <select value={idea.status} onChange={(event) => changeStatus(idea, event.target.value)}>
                  {STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
                </select>
              </div>
            </div>
            <EngagementPanel targetType="idea" targetId={idea.id} reactions={idea.reactions} commentCount={idea.comment_count} onChange={loadIdeas} />
          </article>
        ))}
      </div>
    </section>
  );
};

export default IdeasPage;
