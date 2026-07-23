import React, { useEffect, useState } from 'react';
import { fetchServerResources } from '../services/api.js';
import './ServerPage.css';

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = bytes, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

function fmtCents(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

function fmtTokens(n) {
  if (!n) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(0)}k`;
  return String(n);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function UsageBar({ used, total, warnAt, label }) {
  const pct     = total > 0 ? Math.min((used / total) * 100, 100) : 0;
  const warnPct = total > 0 && warnAt ? (warnAt / total) * 100 : null;
  const isWarn  = warnAt && used >= warnAt;
  const isDanger = pct >= 90;
  const color = isDanger ? '#ef4444' : isWarn ? '#f59e0b' : '#667eea';

  return (
    <div className="srv-bar-wrap">
      <div className="srv-bar-track">
        {warnPct && <div className="srv-bar-warn-marker" style={{ left: `${warnPct}%` }} />}
        <div className="srv-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="srv-bar-labels">
        <span>{label}</span>
        <span style={{ color }}>{pct.toFixed(1)}%</span>
      </div>
    </div>
  );
}

function StatTile({ label, value, sub }) {
  return (
    <div className="srv-stat-tile">
      <span className="srv-stat-value">{value}</span>
      <span className="srv-stat-label">{label}</span>
      {sub && <span className="srv-stat-sub">{sub}</span>}
    </div>
  );
}

function SectionCard({ title, icon, children }) {
  return (
    <div className="srv-card">
      <h2 className="srv-card-title"><span>{icon}</span>{title}</h2>
      {children}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ServerPage() {
  const [data, setData]     = useState(null);
  const [error, setError]   = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    fetchServerResources()
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <section className="page server-page"><div className="placeholder-panel">Loading…</div></section>;
  if (error)   return <section className="page server-page"><div className="placeholder-panel">Error: {error}</div></section>;
  if (!data)   return null;

  const { storage, database, app, ai } = data;

  const diskUsedPct     = storage.disk_total_bytes > 0 ? (storage.disk_used_bytes / storage.disk_total_bytes) * 100 : 0;
  const uploadUsedPct   = storage.upload_max_bytes > 0 ? (storage.upload_dir_bytes / storage.upload_max_bytes) * 100 : 0;
  const aiUsedPct       = ai.budget_cents > 0 ? (ai.used_cents / ai.budget_cents) * 100 : 0;

  return (
    <section className="page server-page">
      <header className="page-header">
        <h1>Server Resources</h1>
        <p className="page-subtitle">VPS storage, database health, and AI API usage.</p>
      </header>

      <button type="button" className="srv-refresh-btn" onClick={load}>↻ Refresh</button>

      <div className="srv-grid">

        {/* ── Storage ── */}
        <SectionCard title="VPS Disk" icon="💾">
          <UsageBar
            used={storage.disk_used_bytes}
            total={storage.disk_total_bytes}
            label={`${fmtBytes(storage.disk_used_bytes)} used of ${fmtBytes(storage.disk_total_bytes)}`}
          />
          <div className="srv-stat-row">
            <StatTile label="Used"  value={fmtBytes(storage.disk_used_bytes)} />
            <StatTile label="Free"  value={fmtBytes(storage.disk_free_bytes)} />
            <StatTile label="Total" value={fmtBytes(storage.disk_total_bytes)} />
          </div>
        </SectionCard>

        {/* ── Uploads ── */}
        <SectionCard title="Uploads Directory" icon="🖼️">
          <UsageBar
            used={storage.upload_dir_bytes}
            total={storage.upload_max_bytes}
            warnAt={storage.upload_warn_bytes}
            label={`${fmtBytes(storage.upload_dir_bytes)} of ${fmtBytes(storage.upload_max_bytes)} limit`}
          />
          <div className="srv-stat-row">
            <StatTile label="Photos & Avatars" value={fmtBytes(storage.upload_dir_bytes)} />
            <StatTile label="Warn at"  value={fmtBytes(storage.upload_warn_bytes)} />
            <StatTile label="Hard cap" value={fmtBytes(storage.upload_max_bytes)} />
          </div>
        </SectionCard>

        {/* ── Database ── */}
        <SectionCard title="Database" icon="🗄️">
          <div className="srv-stat-row">
            <StatTile label="DB size"     value={fmtBytes(database.size_bytes)} />
            <StatTile label="Users"       value={app.users.toLocaleString()} />
            <StatTile label="Messages"    value={app.messages.toLocaleString()} />
            <StatTile label="Photos"      value={app.photos.toLocaleString()} />
            <StatTile label="Ideas"       value={app.ideas.toLocaleString()} />
            <StatTile label="Polls"       value={app.polls.toLocaleString()} />
            <StatTile label="Online now"  value={app.connections.toLocaleString()} />
          </div>
        </SectionCard>

        {/* ── AI API ── */}
        <SectionCard title="AI API Credits" icon="🤖">
          {!ai.configured ? (
            <div className="srv-ai-unconfigured">
              <p>No AI API key configured.</p>
              <p className="srv-ai-hint">Set <code>AI_API_KEY</code> in your <code>.env</code> to enable AI features and credit tracking.</p>
            </div>
          ) : (
            <>
              <div className="srv-ai-provider">
                <span className="srv-ai-badge">{ai.provider}</span>
                <span className="srv-ai-status srv-ai-status--ok">API key set ✓</span>
              </div>

              {ai.budget_cents > 0 ? (
                <>
                  <UsageBar
                    used={ai.used_cents}
                    total={ai.budget_cents}
                    warnAt={ai.budget_cents * 0.8}
                    label={`${fmtCents(ai.used_cents)} used of ${fmtCents(ai.budget_cents)} monthly budget`}
                  />
                  <div className="srv-stat-row">
                    <StatTile label="Used this month" value={fmtCents(ai.used_cents)} />
                    <StatTile label="Remaining"       value={fmtCents(Math.max(0, ai.budget_cents - ai.used_cents))} />
                    <StatTile label="Budget"          value={fmtCents(ai.budget_cents)} />
                  </div>
                </>
              ) : (
                <p className="srv-ai-hint">Set <code>AI_MONTHLY_BUDGET_CENTS</code> to track against a monthly budget.</p>
              )}

              <div className="srv-stat-row" style={{ marginTop: '0.75rem' }}>
                <StatTile
                  label="Tokens this month"
                  value={fmtTokens(ai.tokens_total)}
                  sub={`↑${fmtTokens(ai.tokens_in)} / ↓${fmtTokens(ai.tokens_out)}`}
                />
              </div>
            </>
          )}
        </SectionCard>

      </div>
    </section>
  );
}
