import React, { useEffect, useMemo, useState } from 'react';
import { fetchTopicDetail, fetchTopicTimeline } from '../services/api.js';
import './TopicsPage.css';

const DEFAULT_DATE_FROM = '2020-09-20';
const DEFAULT_DATE_TO = '2020-09-27';
const ALL = 'all';

function formatDate(value) {
  if (!value) return '';
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
}

function formatTimeRange(start, end) {
  const format = (value) => {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  };
  const a = format(start);
  const b = format(end);
  if (a && b) return `${a} – ${b}`;
  return a || b || 'Time unknown';
}

function prettyType(value) {
  if (!value) return 'Unclassified';
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function sortedOptions(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function topicMatches(topic, filters) {
  if (filters.type !== ALL && topic.topic_type !== filters.type) return false;
  if (filters.tag !== ALL && !(topic.tags || []).includes(filters.tag)) return false;
  if (filters.participant !== ALL && !(topic.participant_names || []).includes(filters.participant)) return false;
  return true;
}

function buildChatHref(anchor) {
  return anchor || null;
}

function FilterSelect({ label, value, onChange, options, formatOption = (x) => x }) {
  return (
    <label className="topics-filter">
      <span>{label}</span>
      <div className="topics-filter__select">
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          <option value={ALL}>All</option>
          {options.map((option) => (
            <option key={option} value={option}>{formatOption(option)}</option>
          ))}
        </select>
      </div>
    </label>
  );
}

function TopicCard({ topic, expanded, detail, loadingDetail, onToggle, onNavigate }) {
  const title = topic.display_label || topic.refined_label || topic.label || 'Untitled topic';
  const chatHref = buildChatHref(topic.chat_anchor);
  const confidence = typeof topic.confidence === 'number' ? Math.round(topic.confidence * 100) : null;
  const tags = (topic.tags || []).slice(0, 4);
  const people = (topic.participant_names || []).slice(0, 4);
  const extraPeople = Math.max(0, (topic.participant_names || []).length - people.length);

  return (
    <article className={`topic-card${expanded ? ' topic-card--expanded' : ''}`}>
      <button
        type="button"
        className="topic-card__main"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <div className="topic-card__topline">
          <span className={`topic-type topic-type--${topic.topic_type || 'unknown'}`}>{prettyType(topic.topic_type)}</span>
          <span className="topic-card__time">{formatTimeRange(topic.first_message_at || topic.started_at, topic.last_message_at || topic.ended_at)}</span>
        </div>

        <h3>{title}</h3>
        {topic.summary && <p>{topic.summary}</p>}

        <div className="topic-card__meta">
          <span><strong>{topic.message_count || 0}</strong> msgs</span>
          <span><strong>{topic.participant_count || (topic.participant_names || []).length || 0}</strong> people</span>
          <span><strong>{topic.segment_count || topic.segments || 0}</strong> segments</span>
          {confidence !== null && <span className="topic-card__conf">{confidence}% match</span>}
        </div>

        {(tags.length > 0 || people.length > 0) && (
          <div className="topic-card__chips" aria-label="Topic tags and participants">
            {tags.map((tag) => (
              <span className="topic-chip topic-chip--tag" key={tag}>#{tag}</span>
            ))}
            {people.map((name) => (
              <span className="topic-chip" key={name}>{name}</span>
            ))}
            {extraPeople > 0 && <span className="topic-chip topic-chip--more">+{extraPeople}</span>}
          </div>
        )}

        <span className="topic-card__expand-hint">{expanded ? 'Hide detail' : 'Tap for detail'}</span>
      </button>

      {expanded && (
        <div className="topic-detail-panel">
          {loadingDetail && <div className="topic-detail-loading">Loading topic detail…</div>}
          {!loadingDetail && detail && detail.error && (
            <div className="topic-detail-loading">{detail.error}</div>
          )}
          {!loadingDetail && detail && !detail.error && (
            <>
              <div className="topic-detail-grid">
                <div>
                  <span className="topic-detail-label">Participants</span>
                  <p>{(detail.participants || []).map((p) => p.canonical_name).join(', ') || (topic.participant_names || []).join(', ') || 'Unknown'}</p>
                </div>
                <div>
                  <span className="topic-detail-label">Refinement</span>
                  <p>{detail.label_source || 'unknown'}{detail.refinement_model ? ` via ${detail.refinement_model}` : ''}</p>
                </div>
                <div>
                  <span className="topic-detail-label">Volume</span>
                  <p>{detail.message_count || 0} messages · {detail.segment_count || 0} segments</p>
                </div>
              </div>
              {detail.summary && <p className="topic-detail-summary">{detail.summary}</p>}
              {(detail.segments || []).length > 0 && (
                <div className="topic-segments">
                  {(detail.segments || []).map((segment) => (
                    <div className="topic-segment" key={segment.id}>
                      <div className="topic-segment__meta">
                        <span>{formatTimeRange(segment.started_at, segment.ended_at)}</span>
                        <span>{typeof segment.score === 'number' ? `${Math.round(segment.score * 100)}% match` : 'Segment'}</span>
                      </div>
                      {segment.excerpt && <p>{segment.excerpt}</p>}
                      {segment.chat_anchor && (
                        <button
                          type="button"
                          className="topic-segment__chat-link"
                          onClick={() => onNavigate(segment.chat_anchor)}
                        >
                          Open segment in chat
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {chatHref && (
            <button
              type="button"
              className="topic-link-button"
              onClick={() => onNavigate(chatHref)}
            >
              Open chat ↗
            </button>
          )}
        </div>
      )}
    </article>
  );
}

export default function TopicsPage({ onNavigate }) {
  const [dateFrom, setDateFrom] = useState(DEFAULT_DATE_FROM);
  const [dateTo, setDateTo] = useState(DEFAULT_DATE_TO);
  const [timeline, setTimeline] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [filters, setFilters] = useState({ type: ALL, tag: ALL, participant: ALL });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [expandedTopicId, setExpandedTopicId] = useState(null);
  const [detailById, setDetailById] = useState({});
  const [detailLoadingId, setDetailLoadingId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError('');
      try {
        const data = await fetchTopicTimeline({ dateFrom, dateTo });
        if (!cancelled) setTimeline(data);
      } catch (err) {
        if (!cancelled) setError(err.message || 'Failed to load topics');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [dateFrom, dateTo]);

  const days = timeline?.days || [];
  const allTopics = useMemo(() => days.flatMap((day) => day.topics || []), [days]);
  const options = useMemo(() => ({
    types: sortedOptions(allTopics.map((topic) => topic.topic_type)),
    tags: sortedOptions(allTopics.flatMap((topic) => topic.tags || [])),
    participants: sortedOptions(allTopics.flatMap((topic) => topic.participant_names || [])),
  }), [allTopics]);

  const filteredDays = useMemo(() => (
    days
      .map((day) => ({
        ...day,
        topics: (day.topics || []).filter((topic) => topicMatches(topic, filters)),
      }))
      .filter((day) => day.topics.length > 0)
  ), [days, filters]);

  const filteredCount = filteredDays.reduce((total, day) => total + day.topics.length, 0);
  const activeFilterCount = Object.values(filters).filter((value) => value !== ALL).length;

  const updateFilter = (key, value) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const resetFilters = () => {
    setFilters({ type: ALL, tag: ALL, participant: ALL });
  };

  const toggleTopic = async (topicId) => {
    const nextExpanded = expandedTopicId === topicId ? null : topicId;
    setExpandedTopicId(nextExpanded);
    if (!nextExpanded || detailById[nextExpanded]) return;
    setDetailLoadingId(nextExpanded);
    try {
      const detail = await fetchTopicDetail(nextExpanded);
      setDetailById((current) => ({ ...current, [nextExpanded]: detail }));
    } catch (err) {
      setDetailById((current) => ({ ...current, [nextExpanded]: { error: err.message || 'Failed to load detail' } }));
    } finally {
      setDetailLoadingId(null);
    }
  };

  const handleNavigate = (path) => {
    if (onNavigate) onNavigate(path);
  };

  return (
    <div className="topics-page">
      <header className="topics-header">
        <p className="topics-eyebrow">Topic timeline</p>
        <h1>What did the group talk about?</h1>
        <p className="topics-subtitle">Browse refined chat topics by day, people, tags, and type.</p>
      </header>

      <div className="topics-toolbar">
        <button
          type="button"
          className={`topics-filter-toggle${filtersOpen ? ' is-open' : ''}`}
          onClick={() => setFiltersOpen((open) => !open)}
          aria-expanded={filtersOpen}
        >
          <span className="topics-filter-toggle__icon" aria-hidden="true">⚙</span>
          <span>Filters</span>
          {activeFilterCount > 0 && <span className="topics-filter-toggle__badge">{activeFilterCount}</span>}
        </button>
        <span className="topics-count">
          <strong>{filteredCount}</strong> {filteredCount === 1 ? 'topic' : 'topics'}
        </span>
      </div>

      {filtersOpen && (
        <section className="topics-controls" aria-label="Topic filters">
          <div className="topics-controls__dates">
            <label className="topics-filter">
              <span>From</span>
              <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
            </label>
            <label className="topics-filter">
              <span>To</span>
              <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </label>
          </div>
          <FilterSelect label="Type" value={filters.type} onChange={(value) => updateFilter('type', value)} options={options.types} formatOption={prettyType} />
          <FilterSelect label="Tag" value={filters.tag} onChange={(value) => updateFilter('tag', value)} options={options.tags} />
          <FilterSelect label="Person" value={filters.participant} onChange={(value) => updateFilter('participant', value)} options={options.participants} />
          <div className="topics-controls__actions">
            <button type="button" className="topics-reset-button" onClick={resetFilters} disabled={activeFilterCount === 0}>Reset filters</button>
            <button type="button" className="topics-done-button" onClick={() => setFiltersOpen(false)}>Done</button>
          </div>
        </section>
      )}

      {loading && <div className="topics-state">Loading topics…</div>}
      {error && <div className="topics-state topics-state--error">{error}</div>}
      {!loading && !error && filteredCount === 0 && (
        <div className="topics-state">
          No topics found for this range and filter set.
          {activeFilterCount > 0 && (
            <button type="button" className="topics-state__reset" onClick={resetFilters}>Clear filters</button>
          )}
        </div>
      )}

      {!loading && !error && filteredCount > 0 && (
        <section className="topics-timeline" aria-label="Topic timeline">
          {filteredDays.map((day) => (
            <div className="topics-day" key={day.date}>
              <div className="topics-day__heading">
                <h2>{formatDate(day.date)}</h2>
                <span>{day.topics.length} {day.topics.length === 1 ? 'topic' : 'topics'}</span>
              </div>
              <div className="topics-day__list">
                {day.topics.map((topic) => (
                  <TopicCard
                    key={topic.id}
                    topic={topic}
                    expanded={expandedTopicId === topic.id}
                    detail={detailById[topic.id]}
                    loadingDetail={detailLoadingId === topic.id}
                    onToggle={() => toggleTopic(topic.id)}
                    onNavigate={handleNavigate}
                  />
                ))}
              </div>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
