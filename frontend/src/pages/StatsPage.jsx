import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchStats,
  fetchStatsActivity,
  fetchStatsLeaderboard,
  fetchStatsTopReactions,
  fetchStatsReactionSignature,
  fetchStatsReactionDyadic,
  fetchStatsReactionTrends,
  fetchStatsReactionsBySender,
  fetchStatsTopReactedMessages,
  fetchMembers,
} from '../services/api.js';
import { buildChatMessageHref } from '../utils/chatLinks.js';
import './StatsPage.css';

// ── Shared helpers ────────────────────────────────────────────────────────────

const TIME_RANGES = [
  { id: 'all',    label: 'All time', days: null },
  { id: '30d',    label: '30d',      days: 30   },
  { id: '90d',    label: '90d',      days: 90   },
  { id: 'year',   label: 'Year',     days: 365  },
];

const GROUP_BY_OPTIONS = [
  { id: 'day',   label: 'Day'   },
  { id: 'week',  label: 'Week'  },
  { id: 'month', label: 'Month' },
  { id: 'year',  label: 'Year'  },
];

const ACTIVITY_METRICS = [
  { id: 'messages', label: 'Messages', singular: 'message' },
  { id: 'photos', label: 'Photos', singular: 'photo' },
  { id: 'gifs', label: 'GIFs', singular: 'GIF' },
];

const ACTIVITY_SORT_OPTIONS = [
  { id: 'date_asc', label: 'Oldest first' },
  { id: 'date_desc', label: 'Newest first' },
  { id: 'count_desc', label: 'Most first' },
  { id: 'count_asc', label: 'Fewest first' },
];

const FALLBACK_TOP_EMOJIS = ['😆', '👍', '❤', '😮', '🤣', '👎', '😢', '😠']
  .map(emoji => ({ emoji, count: 0 }));

const TOP_REACTED_PAGE_SIZE = 10;

function rangeToParams(rangeId) {
  const r = TIME_RANGES.find(x => x.id === rangeId);
  if (!r || r.days == null) return { dateFrom: undefined, dateTo: undefined };
  const from = new Date(Date.now() - r.days * 86400 * 1000);
  return { dateFrom: from.toISOString(), dateTo: undefined };
}

function dateInputToApiStart(value) {
  return value ? new Date(`${value}T00:00:00`).toISOString() : undefined;
}

function dateInputToApiEnd(value) {
  if (!value) return undefined;
  const d = new Date(`${value}T00:00:00`);
  d.setDate(d.getDate() + 1);
  return d.toISOString();
}

function toDateInput(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function todayInput() {
  return toDateInput(new Date());
}

function dayDiff(from, to) {
  if (!from || !to) return 0;
  const a = new Date(`${from}T00:00:00`);
  const b = new Date(`${to}T00:00:00`);
  return Math.max(0, Math.round((b - a) / 86400000));
}

function useUrlParam(key, defaultValue) {
  const get = () => new URLSearchParams(window.location.search).get(key) ?? defaultValue;
  const [value, setValue] = useState(get);

  const set = useCallback((v) => {
    setValue(v);
    const params = new URLSearchParams(window.location.search);
    if (v === defaultValue) params.delete(key); else params.set(key, v);
    const qs = params.toString();
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
  }, [key, defaultValue]);

  return [value, set];
}

// ── Chart primitives ──────────────────────────────────────────────────────────

const YEAR_COLORS = ['#667eea', '#10b981', '#f59e0b', '#06b6d4', '#f43f5e', '#8b5cf6', '#14b8a6', '#ec4899'];

function yearColor(iso) {
  const year = iso ? new Date(iso).getUTCFullYear() : 0;
  const idx = Math.abs(year) % YEAR_COLORS.length;
  return YEAR_COLORS[idx];
}

function mixHexColor(from, to, amount) {
  const clamp = Math.max(0, Math.min(1, amount));
  const parse = (hex) => [
    Number.parseInt(hex.slice(1, 3), 16),
    Number.parseInt(hex.slice(3, 5), 16),
    Number.parseInt(hex.slice(5, 7), 16),
  ];
  const [fr, fg, fb] = parse(from);
  const [tr, tg, tb] = parse(to);
  const mixed = [fr, fg, fb].map((v, i) => {
    const target = [tr, tg, tb][i];
    return Math.round(v + (target - v) * clamp).toString(16).padStart(2, '0');
  });
  return `#${mixed.join('')}`;
}

function HBar({ label, value, max, color = '#667eea', suffix = '' }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="hbar-row">
      <span className="hbar-label" title={label}>{label}</span>
      <div className="hbar-track">
        <div className="hbar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="hbar-value">{typeof value === 'number' ? value.toLocaleString() : value}{suffix}</span>
    </div>
  );
}

function pluraliseMetric(metric, count) {
  const option = ACTIVITY_METRICS.find(item => item.id === metric) || ACTIVITY_METRICS[0];
  if (option.id === 'gifs') return count === 1 ? option.singular : 'GIFs';
  return count === 1 ? option.singular : `${option.singular}s`;
}

function groupByNoun(groupBy) {
  return GROUP_BY_OPTIONS.find(item => item.id === groupBy)?.label.toLowerCase() || 'period';
}

function formatBucketDate(iso, groupBy) {
  if (!iso) return '';
  const d = new Date(iso);
  if (groupBy === 'year') return d.getUTCFullYear().toString();
  if (groupBy === 'month') return d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
  if (groupBy === 'week') return `w/c ${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}`;
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatAxisTickDate(iso, groupBy) {
  if (!iso) return '';
  const d = new Date(iso);
  if (groupBy === 'year') return d.getUTCFullYear().toString();
  if (groupBy === 'month') return d.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
  if (groupBy === 'week') return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

function ActivityChart({ data, groupBy, metric, onBucketClick }) {
  const containerRef = useRef(null);
  const [hovered, setHovered] = useState(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  if (!data || data.length === 0) {
    return <div className="sparkline-empty">No activity data for this period</div>;
  }

  const counts = data.map(d => d.count);
  const max = Math.max(...counts, 1);
  const metricLabel = pluraliseMetric(metric, 2);
  const W = 660, H = 188, LEFT = 54, RIGHT = 12, TOP = 16, BOTTOM = 42, BAR_GAP = 1;
  const plotW = W - LEFT - RIGHT;
  const plotH = H - TOP - BOTTOM;
  const barW = Math.max(1, plotW / data.length - BAR_GAP);
  const ticks = [...new Set([0, 0.5, 1].map(t => Math.round(max * t)))];

  const bars = data.map((d, i) => {
    const x = LEFT + i * (plotW / data.length);
    const barH = Math.max(2, (d.count / max) * plotH);
    const y = TOP + plotH - barH;
    return { x, y, barH, ...d };
  });
  const tickTarget = data.length <= 6 ? data.length : 5;
  const xTickIndexes = new Set(
    Array.from({ length: tickTarget }, (_, idx) => (
      Math.round((idx / Math.max(tickTarget - 1, 1)) * (data.length - 1))
    ))
  );

  const handleMouseMove = (e, bar, idx) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (rect) {
      setTooltipPos({ x: e.clientX - rect.left, y: e.clientY - rect.top - 36 });
    }
    setHovered({ ...bar, idx });
  };

  return (
    <div className="activity-chart-wrap" ref={containerRef}>
      <svg
        className="activity-chart"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${metricLabel} per ${groupByNoun(groupBy)} chart`}
      >
        <text
          className="activity-axis-title activity-axis-title--y"
          x={15}
          y={TOP + plotH / 2}
          textAnchor="middle"
          transform={`rotate(-90 15 ${TOP + plotH / 2})`}
        >
          {metricLabel}
        </text>
        {ticks.map((tick) => {
          const y = TOP + plotH - (tick / max) * plotH;
          return (
            <React.Fragment key={tick}>
              <line className="activity-grid-line" x1={LEFT} x2={W - RIGHT} y1={y} y2={y} />
              <text className="activity-axis-label" x={LEFT - 8} y={y + 4} textAnchor="end">
                {tick.toLocaleString()}
              </text>
            </React.Fragment>
          );
        })}
        <line className="activity-axis-line" x1={LEFT} x2={LEFT} y1={TOP} y2={TOP + plotH} />
        <line className="activity-axis-line" x1={LEFT} x2={W - RIGHT} y1={TOP + plotH} y2={TOP + plotH} />
        {bars.map((bar, i) => (
          <rect
            key={i}
            x={bar.x}
            y={bar.y}
            width={barW}
            height={bar.barH}
            rx="2"
            fill={yearColor(bar.date)}
            fillOpacity={hovered && hovered.idx !== i ? 0.5 : 1}
            style={{ cursor: 'pointer' }}
            onMouseMove={(e) => handleMouseMove(e, bar, i)}
            onMouseLeave={() => setHovered(null)}
            onClick={() => onBucketClick?.(bar)}
          />
        ))}
        {bars.map((bar, i) => xTickIndexes.has(i) && (
          <text
            key={`tick-${i}`}
            className="activity-axis-label activity-axis-label--x"
            x={bar.x + barW / 2}
            y={TOP + plotH + 18}
            textAnchor="middle"
          >
            {formatAxisTickDate(bar.date, groupBy)}
          </text>
        ))}
      </svg>
      {hovered && (
        <div
          className="activity-tooltip"
          style={{ left: tooltipPos.x, top: tooltipPos.y }}
          aria-hidden
        >
          <div className="activity-tooltip-date">{formatBucketDate(hovered.date, groupBy)}</div>
          <div className="activity-tooltip-count">
            {hovered.count.toLocaleString()} {pluraliseMetric(metric, hovered.count)}
          </div>
        </div>
      )}
    </div>
  );
}

function formatPeakHourLabel(hour) {
  if (hour === 0) return '12am';
  if (hour < 12) return `${hour}am`;
  if (hour === 12) return '12pm';
  return `${hour - 12}pm`;
}

function PeakHoursHeatmap({ data, selected, onSelect }) {
  if (!data || data.length === 0) return null;
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const labels = ['12a','1','2','3','4','5','6','7','8','9','10','11','12p','1','2','3','4','5','6','7','8','9','10','11'];
  const max = Math.max(...data.flatMap(row => row.hours.map(h => h.count)), 1);
  return (
    <div className="peak-heatmap-wrap">
      <div className="peak-heatmap">
        <div className="peak-corner" />
        {labels.map((label, i) => (
          <div key={i} className="peak-hour-label">{label}</div>
        ))}
        {data.map((row) => (
          <React.Fragment key={row.day}>
            <div className="peak-day-label">{days[row.day] ?? row.day}</div>
            {row.hours.map((hour) => {
              const intensity = hour.count / max;
              const bg = mixHexColor('#dbeafe', '#f43f5e', intensity);
              const isSelected = selected?.day === row.day && selected?.hour === hour.hour;
              return (
                <button
                  key={hour.hour}
                  type="button"
                  className={`peak-heat-cell${isSelected ? ' is-selected' : ''}`}
                  style={{ background: bg }}
                  title={`${days[row.day]} ${labels[hour.hour]}: ${hour.count.toLocaleString()} messages`}
                  aria-label={`${days[row.day]} ${formatPeakHourLabel(hour.hour)}: ${hour.count.toLocaleString()} messages`}
                  onClick={() => onSelect?.({
                    day: row.day,
                    dayLabel: days[row.day] ?? String(row.day),
                    hour: hour.hour,
                    hourLabel: formatPeakHourLabel(hour.hour),
                    count: hour.count,
                  })}
                />
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

function StatCard({ label, value, color, sub }) {
  return (
    <div className="stat-card" style={{ borderTopColor: color }}>
      <p className="stat-card-value">{typeof value === 'number' ? value.toLocaleString() : value}</p>
      <p className="stat-card-label">{label}</p>
      {sub && <p className="stat-card-sub">{sub}</p>}
    </div>
  );
}

function formatDateTime(iso) {
  if (!iso) return 'No messages yet';
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatUptime(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const totalDays = Math.floor(totalSeconds / 86400);
  const years = Math.floor(totalDays / 365);
  const days = totalDays % 365;
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return years > 0
    ? `${years.toLocaleString()}y ${days}d ${hours}h ${minutes}m ${seconds}s`
    : `${days.toLocaleString()}d ${hours}h ${minutes}m ${seconds}s`;
}

function formatRate(value) {
  if (typeof value !== 'number') return '0/day';
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}/day`;
}

function GroupClock({ firstMessageAt }) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!firstMessageAt) return undefined;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [firstMessageAt]);

  const firstMs = firstMessageAt ? new Date(firstMessageAt).getTime() : null;
  const uptime = firstMs ? formatUptime(now - firstMs) : '0d 0h 0m 0s';

  return (
    <div className="group-clock">
      <div className="group-clock-item">
        <span className="group-clock-label">First message</span>
        <span className="group-clock-value">{formatDateTime(firstMessageAt)}</span>
      </div>
      <div className="group-clock-item">
        <span className="group-clock-label">Group chat uptime</span>
        <span className="group-clock-value group-clock-value--timer">{uptime}</span>
      </div>
    </div>
  );
}

// ── Signature matrix ──────────────────────────────────────────────────────────

function SignatureMatrix({ people, emojis, matrix }) {
  const [sort, setSort] = useState(null);
  const [fullscreen, setFullscreen] = useState(false);

  if (!people?.length || !emojis?.length) {
    return <div className="matrix-empty">Not enough reaction data yet</div>;
  }

  const maxVal = Math.max(...matrix.flat(), 1);
  const rowIndexes = people.map((_, i) => i);
  if (sort) {
    rowIndexes.sort((a, b) => {
      const av = matrix[a]?.[sort.index] ?? 0;
      const bv = matrix[b]?.[sort.index] ?? 0;
      return sort.dir === 'desc' ? bv - av : av - bv;
    });
  }

  const handleSort = (index) => {
    setSort(prev => {
      if (!prev || prev.index !== index) return { index, dir: 'desc' };
      if (prev.dir === 'desc') return { index, dir: 'asc' };
      return null;
    });
  };

  const content = (
    <div className="sig-matrix-shell">
      <div className="sig-matrix-toolbar">
        <span>{sort ? `Sorted by ${emojis[sort.index]} ${sort.dir === 'desc' ? 'high to low' : 'low to high'}` : 'Click an emoji column to sort'}</span>
        <button
          type="button"
          className="sig-matrix-action"
          onClick={() => setFullscreen(v => !v)}
        >
          {fullscreen ? 'Exit full screen' : 'Full screen'}
        </button>
      </div>
      <div className="sig-matrix-wrap">
        <div className="sig-matrix" style={{ '--cols': emojis.length }}>
          <div className="sig-cell sig-corner" />
          {emojis.map((e, ei) => (
            <button
              key={e}
              type="button"
              className={`sig-cell sig-emoji-head sig-sort-head ${sort?.index === ei ? 'is-sorted' : ''}`}
              title={`Sort by ${e}`}
              onClick={() => handleSort(ei)}
            >
              <span>{e}</span>
              {sort?.index === ei && <span className="sig-sort-mark">{sort.dir === 'desc' ? '↓' : '↑'}</span>}
            </button>
          ))}
          {rowIndexes.map((pi) => {
            const person = people[pi];
            return (
              <React.Fragment key={person}>
                <div className="sig-cell sig-person-label" title={person}>{person}</div>
                {emojis.map((emoji, ei) => {
                  const val = matrix[pi]?.[ei] ?? 0;
                  const intensity = val / maxVal;
                  const bg = val === 0
                    ? 'transparent'
                    : `rgba(102,126,234,${0.08 + intensity * 0.85})`;
                  return (
                    <div
                      key={emoji}
                      className="sig-cell sig-data"
                      style={{ background: bg }}
                      title={`${person} x ${emoji}: ${val}`}
                    >
                      {val > 0 ? val : ''}
                    </div>
                  );
                })}
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </div>
  );

  return (
    <div className={fullscreen ? 'sig-matrix-fullscreen' : ''}>
      {fullscreen && <div className="sig-matrix-backdrop" onClick={() => setFullscreen(false)} />}
      <div className={fullscreen ? 'sig-matrix-modal' : ''}>
        {content}
      </div>
    </div>
  );
}

// ── Dyadic heatmap ────────────────────────────────────────────────────────────

function DyadicHeatmap({ givers, receivers, matrix }) {
  const [fullscreen, setFullscreen] = useState(false);

  if (!givers?.length || !receivers?.length) {
    return <div className="matrix-empty">Not enough reaction data yet</div>;
  }

  const maxVal = Math.max(...matrix.flat(), 1);

  const content = (
    <div className="sig-matrix-shell">
      <div className="sig-matrix-toolbar">
        <span>Reaction count from row person to column person</span>
        <button
          type="button"
          className="sig-matrix-action"
          onClick={() => setFullscreen(v => !v)}
        >
          {fullscreen ? 'Exit full screen' : 'Full screen'}
        </button>
      </div>
      <div className="sig-matrix-wrap">
        <div className="dyadic-header-row">
          <span className="dyadic-axis-label">Reacts to →</span>
        </div>
        <div className="sig-matrix" style={{ '--cols': receivers.length }}>
          <div className="sig-cell sig-corner">↓ From</div>
          {receivers.map(r => (
            <div key={r} className="sig-cell sig-person-head" title={r}>{r}</div>
          ))}
          {givers.map((giver, gi) => (
            <React.Fragment key={giver}>
              <div className="sig-cell sig-person-label" title={giver}>{giver}</div>
              {receivers.map((recv, ri) => {
                const val = matrix[gi]?.[ri] ?? 0;
                const intensity = val / maxVal;
                const bg = val === 0
                  ? 'transparent'
                  : `rgba(16,185,129,${0.08 + intensity * 0.85})`;
                return (
                  <div
                    key={recv}
                    className="sig-cell sig-data"
                    style={{ background: bg }}
                    title={`${giver} → ${recv}: ${val}`}
                  >
                    {val > 0 ? val : ''}
                  </div>
                );
              })}
            </React.Fragment>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <div className={fullscreen ? 'sig-matrix-fullscreen' : ''}>
      {fullscreen && <div className="sig-matrix-backdrop" onClick={() => setFullscreen(false)} />}
      <div className={fullscreen ? 'sig-matrix-modal' : ''}>
        {content}
      </div>
    </div>
  );
}

// ── Reaction trends ───────────────────────────────────────────────────────────

function ReactionTrendsChart({ series, groupBy = 'month' }) {
  const [fullscreen, setFullscreen] = useState(false);
  const [hiddenEmojis, setHiddenEmojis] = useState(() => new Set());
  const [hoverIndex, setHoverIndex] = useState(null);

  const COLORS = ['#667eea','#f59e0b','#10b981','#f43f5e','#8b5cf6','#06b6d4','#ec4899','#84cc16'];

  useEffect(() => {
    setHiddenEmojis(prev => {
      const available = new Set((series || []).map(s => s.emoji));
      const next = new Set([...prev].filter(emoji => available.has(emoji)));
      return next.size === prev.size ? prev : next;
    });
  }, [series]);

  if (!series?.length) return <div className="sparkline-empty">No trend data</div>;

  const allDates = [...new Set(series.flatMap(s => s.data.map(d => d.date)))].sort();
  if (!allDates.length) return <div className="sparkline-empty">No trend data</div>;

  const activeSeries = series.filter(s => !hiddenEmojis.has(s.emoji));
  const W = 680, H = 260;
  const PAD = { top: 18, right: 18, bottom: 42, left: 44 };
  const maxVal = Math.max(
    ...activeSeries.flatMap(s => s.data.map(d => d.count)),
    1
  );
  const yMax = Math.max(1, Math.ceil(maxVal / 5) * 5);
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const yTicks = [0, Math.round(yMax / 2), yMax];
  const xTickIndexes = [...new Set([0, Math.floor((allDates.length - 1) / 2), allDates.length - 1])];

  const xScale = (i) => PAD.left + (i / Math.max(allDates.length - 1, 1)) * plotW;
  const yScale = (v) => PAD.top + plotH - (v / yMax) * plotH;
  const parseTrendDate = (date) => {
    if (!date) return null;
    const match = String(date).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return null;
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  };
  const formatTrendDate = (date) => {
    const parsed = parseTrendDate(date);
    if (!parsed) return String(date || '');
    if (groupBy === 'year') {
      return parsed.toLocaleDateString(undefined, { year: 'numeric' });
    }
    if (groupBy === 'month') {
      return parsed.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
    }
    if (groupBy === 'week') {
      return `Week of ${parsed.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}`;
    }
    return parsed.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  };
  const valueFor = (s, date) => s.data.find(d => d.date === date)?.count ?? 0;
  const hoveredDate = hoverIndex == null ? null : allDates[hoverIndex];

  const toggleEmoji = (emoji) => {
    setHiddenEmojis(prev => {
      const next = new Set(prev);
      if (next.has(emoji)) next.delete(emoji);
      else next.add(emoji);
      return next;
    });
  };

  const handlePointerMove = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * W;
    const clamped = Math.max(PAD.left, Math.min(PAD.left + plotW, svgX));
    const index = Math.round(((clamped - PAD.left) / plotW) * Math.max(allDates.length - 1, 1));
    setHoverIndex(index);
  };

  const content = (
    <div className="reaction-trends-panel">
      <div className="sig-matrix-toolbar">
        <span>{activeSeries.length ? 'Hover for exact counts. Click emojis to hide or show lines.' : 'All emoji lines are hidden'}</span>
        <button
          type="button"
          className="sig-matrix-action"
          onClick={() => setFullscreen(v => !v)}
        >
          {fullscreen ? 'Exit full screen' : 'Full screen'}
        </button>
      </div>
      <div className="reaction-trends-chart-shell">
        <svg
          className="reaction-trends-chart"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="Emoji reaction trends over time"
          onPointerMove={handlePointerMove}
          onPointerLeave={() => setHoverIndex(null)}
        >
          {yTicks.map(tick => (
            <React.Fragment key={tick}>
              <line className="trend-grid-line" x1={PAD.left} x2={W - PAD.right} y1={yScale(tick)} y2={yScale(tick)} />
              <text className="trend-axis-label trend-axis-label--y" x={PAD.left - 8} y={yScale(tick)}>{tick}</text>
            </React.Fragment>
          ))}
          <line className="trend-axis-line" x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} />
          <line className="trend-axis-line" x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom} />
          {xTickIndexes.map(index => (
            <text
              key={allDates[index]}
              className="trend-axis-label"
              x={xScale(index)}
              y={H - 14}
              textAnchor={index === 0 ? 'start' : index === allDates.length - 1 ? 'end' : 'middle'}
            >
              {formatTrendDate(allDates[index])}
            </text>
          ))}
          {activeSeries.map((s) => {
            const si = series.findIndex(item => item.emoji === s.emoji);
            const points = allDates
              .map((date, index) => `${xScale(index).toFixed(1)},${yScale(valueFor(s, date)).toFixed(1)}`)
              .join(' ');
            return (
              <polyline
                key={s.emoji}
                points={points}
                fill="none"
                stroke={COLORS[si % COLORS.length]}
                strokeWidth="2.4"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            );
          })}
          {hoveredDate && (
            <>
              <line className="trend-hover-line" x1={xScale(hoverIndex)} x2={xScale(hoverIndex)} y1={PAD.top} y2={H - PAD.bottom} />
              {activeSeries.map((s) => {
                const si = series.findIndex(item => item.emoji === s.emoji);
                const count = valueFor(s, hoveredDate);
                return (
                  <circle
                    key={s.emoji}
                    className="trend-hover-point"
                    cx={xScale(hoverIndex)}
                    cy={yScale(count)}
                    r="3.8"
                    fill={COLORS[si % COLORS.length]}
                  />
                );
              })}
            </>
          )}
        </svg>
        {hoveredDate && (
          <div className="trend-tooltip">
            <strong>{formatTrendDate(hoveredDate)}</strong>
            {activeSeries
              .map(s => ({ emoji: s.emoji, count: valueFor(s, hoveredDate) }))
              .sort((a, b) => b.count - a.count)
              .map(item => (
                <span key={item.emoji}>{item.emoji} {item.count}</span>
              ))}
          </div>
        )}
      </div>
      <div className="trends-legend" aria-label="Toggle emoji trend lines">
        {series.map((s, si) => {
          const hidden = hiddenEmojis.has(s.emoji);
          return (
            <button
              key={s.emoji}
              type="button"
              className={`trends-legend-item ${hidden ? 'is-hidden' : ''}`}
              onClick={() => toggleEmoji(s.emoji)}
              aria-pressed={!hidden}
              title={`${hidden ? 'Show' : 'Hide'} ${s.emoji}`}
            >
              <span className="trends-legend-dot" style={{ background: COLORS[si % COLORS.length] }} />
              {s.emoji}
            </button>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className={fullscreen ? 'sig-matrix-fullscreen' : ''}>
      {fullscreen && <div className="sig-matrix-backdrop" onClick={() => setFullscreen(false)} />}
      <div className={fullscreen ? 'sig-matrix-modal reaction-trends-modal' : ''}>
        {content}
      </div>
    </div>
  );
}

// ── Top reacted messages ──────────────────────────────────────────────────────

function imageFromMessage(message) {
  if (message?.image_thumbnail_url || message?.image_url) {
    return {
      src: message.image_thumbnail_url || message.image_url,
      href: message.image_url || message.image_thumbnail_url,
      label: message.image_label || 'Image',
    };
  }
  const match = (message?.content || '').match(/\/uploads\/photos\/[^\s)]+/);
  if (!match) return null;
  return {
    src: match[0],
    href: match[0],
    label: (message.content || '').split('\n')[0]?.replace(/^Photo:\s*/i, '') || 'Image',
  };
}

function topReactedDisplayContent(message, image) {
  const content = message?.content || '';
  if (!image) return content;
  return content
    .split('\n')
    .filter(line => {
      const trimmed = line.trim();
      if (!trimmed) return false;
      if (/^Photo:/i.test(trimmed)) return false;
      if (/\/uploads\/photos\//.test(trimmed)) return false;
      return trimmed !== image.label;
    })
    .join('\n')
    .trim();
}

function TopReactedMessages({
  messages,
  senders,
  hasMore,
  loadingMore,
  onLoadMore,
  selectedSender,
  onSenderChange,
  mediaFilter,
  onMediaFilterChange,
  ignoreThumbs,
  onIgnoreThumbsChange,
  onNavigate,
}) {
  const [openImage, setOpenImage] = useState(null);

  return (
    <>
      <div className="top-reacted-filter">
        <label>
          <span>Sender</span>
          <select value={selectedSender} onChange={(e) => onSenderChange?.(e.target.value)}>
            <option value="">All senders</option>
            {(senders || []).map(sender => (
              <option key={sender} value={sender}>{sender}</option>
            ))}
          </select>
        </label>
        <div className="top-reacted-segment">
          <button
            type="button"
            className={`stats-chip stats-chip--sm ${mediaFilter === 'all' ? 'is-active' : ''}`}
            onClick={() => onMediaFilterChange?.('all')}
          >
            All
          </button>
          <button
            type="button"
            className={`stats-chip stats-chip--sm ${mediaFilter === 'images' ? 'is-active' : ''}`}
            onClick={() => onMediaFilterChange?.('images')}
          >
            Images
          </button>
        </div>
        <label className="top-reacted-check">
          <input
            type="checkbox"
            checked={ignoreThumbs}
            onChange={(e) => onIgnoreThumbsChange?.(e.target.checked ? '1' : '0')}
          />
          <span>Ignore thumbs</span>
        </label>
      </div>
      {!messages?.length && <div className="sparkline-empty">No data yet</div>}
      <div className="top-reacted-list">
        {(messages || []).map((m) => {
          const image = imageFromMessage(m);
          const displayContent = topReactedDisplayContent(m, image);
          return (
            <div key={m.message_id} className="top-reacted-row">
              <div className="top-reacted-meta">
                <span className="top-reacted-name">{m.sender_nickname}</span>
                <span className="top-reacted-date">
                  {m.created_at ? new Date(m.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: '2-digit' }) : ''}
                </span>
              </div>
              {image && (
                <button
                  type="button"
                  className="top-reacted-image"
                  onClick={() => setOpenImage(image)}
                  aria-label="Open image"
                >
                  <img src={image.src} alt={image.label} loading="lazy" decoding="async" />
                </button>
              )}
              {displayContent && <p className="top-reacted-content">{displayContent}</p>}
              <div className="top-reacted-foot">
                <div className="top-reacted-emojis" title={`${m.reaction_count} reactions`}>
                  {(m.reactions || []).map(({ emoji, count }) => (
                    <span key={emoji} className="top-reacted-emoji">{emoji} <b>{count}</b></span>
                  ))}
                </div>
                {onNavigate && (
                  <button
                    type="button"
                    className="top-reacted-link"
                    onClick={() => onNavigate(buildChatMessageHref(m.message_id))}
                  >
                    Open in chat ›
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {hasMore && (
        <div className="top-reacted-load">
          <button
            type="button"
            className="stats-chip stats-chip--sm"
            onClick={onLoadMore}
            disabled={loadingMore}
          >
            {loadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
      {openImage && (
        <div className="top-reacted-image-modal" role="dialog" aria-modal="true" aria-label="Image preview">
          <button
            type="button"
            className="top-reacted-image-backdrop"
            onClick={() => setOpenImage(null)}
            aria-label="Close image preview"
          />
          <div className="top-reacted-image-dialog">
            <button
              type="button"
              className="top-reacted-image-close"
              onClick={() => setOpenImage(null)}
              aria-label="Close"
            >
              ×
            </button>
            <img src={openImage.href} alt={openImage.label} />
          </div>
        </div>
      )}
    </>
  );
}

function ReactionsBySender({ data, topEmojis, emoji, onEmojiChange, sortBy, onSortChange }) {
  const rows = data?.senders || [];
  const maxReactions = Math.max(...rows.map(r => r.reaction_count || 0), 1);
  const maxRate = Math.max(...rows.map(r => r.reactions_per_message || 0), 1);

  return (
    <div className="sender-reacts-panel">
      <div className="sender-reacts-toolbar">
        <div className="sender-reacts-emoji-group">
          <span>Emoji</span>
          <div className="sender-reacts-emoji-list" aria-label="Reaction emoji">
          {(topEmojis || []).slice(0, 8).map(({ emoji: option }) => (
            <button
              key={option}
              type="button"
              className={`sender-reacts-emoji ${emoji === option ? 'is-active' : ''}`}
              onClick={() => onEmojiChange(option)}
              title={`Show ${option} reactions`}
            >
              {option}
            </button>
          ))}
          </div>
        </div>
        <div className="top-reacted-segment">
          <button
            type="button"
            className={`stats-chip stats-chip--sm ${sortBy === 'count' ? 'is-active' : ''}`}
            onClick={() => onSortChange?.('count')}
          >
            Total
          </button>
          <button
            type="button"
            className={`stats-chip stats-chip--sm ${sortBy === 'per_message' ? 'is-active' : ''}`}
            onClick={() => onSortChange?.('per_message')}
          >
            Per message
          </button>
        </div>
      </div>
      {!rows.length && <div className="sparkline-empty">No sender reaction data</div>}
      <div className="sender-reacts-list">
        {rows.map((row) => (
          <div key={row.sender_nickname} className="sender-reacts-row">
            <span className="sender-reacts-name" title={row.sender_nickname}>{row.sender_nickname}</span>
            <div className="sender-reacts-bars">
              <div className="sender-reacts-track" title={`${row.reaction_count.toLocaleString()} reactions received`}>
                <div
                  className="sender-reacts-fill sender-reacts-fill--count"
                  style={{ width: `${Math.max(2, (row.reaction_count / maxReactions) * 100)}%` }}
                />
              </div>
              <div className="sender-reacts-track" title={`${row.reactions_per_message.toLocaleString(undefined, { maximumFractionDigits: 3 })} reactions per message`}>
                <div
                  className="sender-reacts-fill sender-reacts-fill--rate"
                  style={{ width: `${Math.max(2, (row.reactions_per_message / maxRate) * 100)}%` }}
                />
              </div>
            </div>
            <span className="sender-reacts-value">
              {row.reaction_count.toLocaleString()}
              <small>{row.reactions_per_message.toLocaleString(undefined, { maximumFractionDigits: 3 })}/msg</small>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatsSelect({ label, value, onChange, children }) {
  return (
    <label className="stats-select-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </label>
  );
}

function ActivityControls({
  metric,
  setMetric,
  groupBy,
  setGroupBy,
  sort,
  setSort,
  userId,
  setUserId,
  members,
  fullscreen,
  setFullscreen,
}) {
  return (
    <div className="activity-controls">
      <div className="activity-controls__selects">
        <StatsSelect label="Show" value={metric} onChange={setMetric}>
          {ACTIVITY_METRICS.map(option => (
            <option key={option.id} value={option.id}>{option.label}</option>
          ))}
        </StatsSelect>
        <StatsSelect label="Group" value={groupBy} onChange={setGroupBy}>
          {GROUP_BY_OPTIONS.map(option => (
            <option key={option.id} value={option.id}>{option.label}</option>
          ))}
        </StatsSelect>
        <StatsSelect label="Sort" value={sort} onChange={setSort}>
          {ACTIVITY_SORT_OPTIONS.map(option => (
            <option key={option.id} value={option.id}>{option.label}</option>
          ))}
        </StatsSelect>
        <StatsSelect label="Member" value={userId} onChange={setUserId}>
          <option value="">Everyone</option>
          {(members || []).filter(member => member.id).map(member => (
            <option key={member.id || member.session_id} value={member.id}>
              {member.display_name || member.nickname || member.username || 'Member'}
            </option>
          ))}
        </StatsSelect>
      </div>
      <button
        type="button"
        className="stats-icon-button"
        onClick={() => setFullscreen(!fullscreen)}
        aria-pressed={fullscreen}
      >
        {fullscreen ? 'Exit full screen' : 'Full screen'}
      </button>
    </div>
  );
}

// ── Yapometer metric selector ─────────────────────────────────────────────────

const LEADERBOARD_METRICS = [
  { id: 'messages',           label: 'Messages'      },
  { id: 'words',              label: 'Words'         },
  { id: 'photos_sent',        label: 'Photos sent'   },
  { id: 'gifs_sent',          label: 'GIFs'          },
  { id: 'reactions_given',    label: 'Reacts given'  },
  { id: 'reactions_received', label: 'Reacts received'},
  { id: 'avg_length',         label: 'Avg length'    },
  { id: 'active_days',        label: 'Active days'   },
];

const NORMALISE_OPTIONS = [
  { id: 'absolute',      label: 'Total'     },
  { id: 'per_active_day', label: 'Per day'  },
  { id: 'percent',       label: '% of group'},
];

function YapDateControls({ minDate, maxDate, fromDate, toDate, setFromDate, setToDate }) {
  if (!minDate || !maxDate) return null;

  const totalDays = Math.max(dayDiff(minDate, maxDate), 1);
  const fromOffset = Math.min(dayDiff(minDate, fromDate), totalDays);
  const toOffset = Math.min(dayDiff(minDate, toDate), totalDays);

  const dateFromOffset = (offset) => {
    const d = new Date(`${minDate}T00:00:00`);
    d.setDate(d.getDate() + Number(offset));
    return toDateInput(d);
  };

  const updateFrom = (value) => {
    const next = value > toDate ? toDate : value;
    setFromDate(next);
  };

  const updateTo = (value) => {
    const next = value < fromDate ? fromDate : value;
    setToDate(next);
  };

  return (
    <div className="yap-date-controls">
      <div className="yap-date-fields">
        <label className="yap-date-field">
          <span>From</span>
          <input
            type="date"
            value={fromDate}
            min={minDate}
            max={toDate}
            onChange={(e) => updateFrom(e.target.value)}
          />
        </label>
        <label className="yap-date-field">
          <span>To</span>
          <input
            type="date"
            value={toDate}
            min={fromDate}
            max={maxDate}
            onChange={(e) => updateTo(e.target.value)}
          />
        </label>
      </div>
      <div className="yap-range-stack" aria-label="Yapometer date range">
        <input
          type="range"
          min="0"
          max={totalDays}
          value={fromOffset}
          onChange={(e) => updateFrom(dateFromOffset(e.target.value))}
        />
        <input
          type="range"
          min="0"
          max={totalDays}
          value={toOffset}
          onChange={(e) => updateTo(dateFromOffset(e.target.value))}
        />
      </div>
    </div>
  );
}

// ── Section component with lazy loading ──────────────────────────────────────

function Section({ title, meta, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="stats-section">
      <button
        type="button"
        className="stats-section-head"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
      >
        <h2>{title}</h2>
        {meta && <span className="stats-meta-inline">{meta}</span>}
        <span className="stats-section-chevron" aria-hidden>{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="stats-section-body">{children}</div>}
    </div>
  );
}

function Loading() {
  return <div className="stats-loading">Loading…</div>;
}

function StatsError({ msg }) {
  return <div className="stats-error">Failed to load: {msg}</div>;
}

// ── useFetch hook ─────────────────────────────────────────────────────────────

function useFetch(fn, deps) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fn()
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(e => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error };
}

// ── Page ──────────────────────────────────────────────────────────────────────

const STATUS_COLORS = {
  maybe: '#94a3b8', planned: '#3b82f6', done: '#22c55e', rejected: '#ef4444',
};

export default function StatsPage({ onNavigate }) {
  const [range] = useUrlParam('range', 'all');
  const [groupBy, setGroupBy] = useUrlParam('groupBy', 'month');
  const [activityMetric, setActivityMetric] = useUrlParam('activityMetric', 'messages');
  const [activitySort, setActivitySort] = useUrlParam('activitySort', 'date_asc');
  const [activityUserId, setActivityUserId] = useUrlParam('activityUserId', '');
  const [selectedActivityBucket, setSelectedActivityBucket] = useState(null);
  const [activityFullscreen, setActivityFullscreen] = useState(false);
  const [selectedPeakHour, setSelectedPeakHour] = useState(null);
  const [peakFullscreen, setPeakFullscreen] = useState(false);
  const [leaderMetric, setLeaderMetric] = useUrlParam('metric', 'messages');
  const [leaderNorm, setLeaderNorm] = useUrlParam('norm', 'absolute');
  const [yapFrom, setYapFrom] = useUrlParam('yapFrom', '');
  const [yapTo, setYapTo] = useUrlParam('yapTo', '');
  const [topSender, setTopSender] = useUrlParam('topSender', '');
  const [topMedia, setTopMedia] = useUrlParam('topMedia', 'all');
  const [ignoreThumbs, setIgnoreThumbs] = useUrlParam('ignoreThumbs', '0');
  const [reactEmoji, setReactEmoji] = useUrlParam('reactEmoji', '');
  const [reactSort, setReactSort] = useUrlParam('reactSort', 'count');
  const [sigDir, setSigDir] = useUrlParam('sigDir', 'given');

  const { dateFrom, dateTo } = useMemo(() => rangeToParams(range), [range]);
  const filterOpts = useMemo(
    () => ({ dateFrom, dateTo }),
    [dateFrom, dateTo]
  );

  // Legacy stats (totals, peak hours, poll participation, idea status)
  const legacy = useFetch(() => fetchStats(), []);
  const members = useFetch(() => fetchMembers(), []);

  const minYapDate = useMemo(() => toDateInput(legacy.data?.first_message_at), [legacy.data?.first_message_at]);
  const maxYapDate = useMemo(() => todayInput(), []);
  const effectiveYapFrom = yapFrom || minYapDate;
  const effectiveYapTo = yapTo || maxYapDate;
  const yapFilterOpts = useMemo(
    () => ({
      dateFrom: dateInputToApiStart(effectiveYapFrom),
      dateTo: dateInputToApiEnd(effectiveYapTo),
    }),
    [effectiveYapFrom, effectiveYapTo]
  );

  // Activity chart
  const activity = useFetch(
    () => fetchStatsActivity({
      ...filterOpts,
      groupBy,
      metric: activityMetric,
      userId: activityUserId || undefined,
    }),
    [dateFrom, dateTo, groupBy, activityMetric, activityUserId]
  );

  const activityBuckets = useMemo(() => {
    const buckets = [...(activity.data?.buckets || [])];
    const sort = ACTIVITY_SORT_OPTIONS.some(option => option.id === activitySort) ? activitySort : 'date_asc';
    buckets.sort((a, b) => {
      if (sort === 'count_desc') return (b.count || 0) - (a.count || 0);
      if (sort === 'count_asc') return (a.count || 0) - (b.count || 0);
      const aTime = a.date ? new Date(a.date).getTime() : 0;
      const bTime = b.date ? new Date(b.date).getTime() : 0;
      return sort === 'date_desc' ? bTime - aTime : aTime - bTime;
    });
    return buckets;
  }, [activity.data?.buckets, activitySort]);

  const selectedActivityMember = useMemo(
    () => (members.data?.members || []).find(member => member.id === activityUserId),
    [members.data?.members, activityUserId]
  );

  useEffect(() => {
    setSelectedActivityBucket(null);
  }, [dateFrom, dateTo, groupBy, activityMetric, activityUserId, activitySort]);

  // Leaderboard
  const leaderboard = useFetch(
    () => fetchStatsLeaderboard({ ...yapFilterOpts, metric: leaderMetric, normalise: leaderNorm }),
    [yapFilterOpts.dateFrom, yapFilterOpts.dateTo, leaderMetric, leaderNorm]
  );

  // Reactions Lab
  const topReactions = useFetch(
    () => fetchStatsTopReactions({ ...filterOpts }),
    [dateFrom, dateTo]
  );

  const topEmojiOptions = useMemo(
    () => {
      const live = (topReactions.data?.reactions || []).slice(0, 8);
      return live.length ? live : FALLBACK_TOP_EMOJIS;
    },
    [topReactions.data]
  );

  useEffect(() => {
    if (!reactEmoji && topEmojiOptions.length > 0) {
      setReactEmoji(topEmojiOptions[0].emoji);
    }
  }, [reactEmoji, setReactEmoji, topEmojiOptions]);

  const sigMatrix = useFetch(
    () => fetchStatsReactionSignature({ ...filterOpts, direction: sigDir }),
    [dateFrom, dateTo, sigDir]
  );

  const dyadic = useFetch(
    () => fetchStatsReactionDyadic({ ...filterOpts }),
    [dateFrom, dateTo]
  );

  const trends = useFetch(
    () => fetchStatsReactionTrends({ ...filterOpts, groupBy }),
    [dateFrom, dateTo, groupBy]
  );

  const reactionsBySender = useFetch(
    () => fetchStatsReactionsBySender({ ...filterOpts, emoji: reactEmoji || undefined, sortBy: reactSort }),
    [dateFrom, dateTo, reactEmoji, reactSort]
  );

  const [topReacted, setTopReacted] = useState({
    data: null,
    loading: true,
    loadingMore: false,
    error: null,
  });

  const loadTopReacted = useCallback(async ({ offset = 0, append = false } = {}) => {
    setTopReacted(prev => ({
      ...prev,
      data: append ? prev.data : null,
      loading: !append,
      loadingMore: append,
      error: null,
    }));
    try {
      const data = await fetchStatsTopReactedMessages({
        ...filterOpts,
        sender: topSender || undefined,
        mediaFilter: topMedia,
        ignoreThumbReactions: ignoreThumbs === '1',
        limit: TOP_REACTED_PAGE_SIZE,
        offset,
      });
      setTopReacted(prev => {
        const previousMessages = append ? (prev.data?.messages || []) : [];
        const seen = new Set(previousMessages.map(message => message.message_id));
        const nextMessages = [
          ...previousMessages,
          ...(data.messages || []).filter(message => !seen.has(message.message_id)),
        ];
        return {
          data: { ...data, messages: nextMessages },
          loading: false,
          loadingMore: false,
          error: null,
        };
      });
    } catch (error) {
      setTopReacted(prev => ({
        ...prev,
        loading: false,
        loadingMore: false,
        error: error.message,
      }));
    }
  }, [dateFrom, dateTo, filterOpts, topSender, topMedia, ignoreThumbs]);

  useEffect(() => {
    loadTopReacted({ offset: 0, append: false });
  }, [loadTopReacted]);

  const handleLoadMoreTopReacted = useCallback(() => {
    loadTopReacted({
      offset: topReacted.data?.messages?.length || 0,
      append: true,
    });
  }, [loadTopReacted, topReacted.data?.messages?.length]);

  const totals = legacy.data?.totals;
  const ideaStatusOrder = ['maybe', 'planned', 'done', 'rejected'];
  const ideaMax = totals
    ? Math.max(...ideaStatusOrder.map(s => legacy.data.idea_status?.[s] || 0), 1)
    : 1;

  const leaderMax = Math.max(
    ...(leaderboard.data?.entries || []).map(e => Number(e.value_normalised) || 0),
    1
  );

  const leaderSuffix = {
    messages: '',
    words: ' w',
    photos_sent: '',
    gifs_sent: '',
    reactions_given: '',
    reactions_received: '',
    avg_length: ' ch',
    active_days: 'd',
  }[leaderMetric] ?? '';

  return (
    <section className="page stats-page">
      <header className="page-header">
        <h1>Group Stats</h1>
        <p className="page-subtitle">Explore your group's history and lore</p>
      </header>

      {/* ── Overview cards ── */}
      {legacy.loading && <div className="stats-card-grid stats-cards-loading"><Loading /></div>}
      {legacy.error && <StatsError msg={legacy.error} />}
      {totals && (
        <>
          <GroupClock firstMessageAt={legacy.data.first_message_at} />
          <div className="stats-card-grid">
            <StatCard label="Messages" value={totals.messages} color="#667eea" sub={formatRate(legacy.data.per_day?.messages)} />
            <StatCard label="Photos" value={totals.photos ?? 0} color="#10b981" sub={formatRate(legacy.data.per_day?.photos)} />
            <StatCard label="GIFs" value={totals.gifs ?? 0} color="#f59e0b" sub={formatRate(legacy.data.per_day?.gifs)} />
            <StatCard label="Voice notes" value={totals.voice_notes ?? 0} color="#06b6d4" sub={formatRate(legacy.data.per_day?.voice_notes)} />
            <StatCard label="Reactions" value={totals.reactions ?? 0} color="#8b5cf6" sub={formatRate(legacy.data.per_day?.reactions)} />
            <StatCard label="Ideas" value={totals.ideas} color="#f43f5e" />
            <StatCard label="Polls" value={totals.polls} color="#14b8a6" />
            <StatCard label="Reminders" value={totals.reminders} color="#fb7185" />
            <StatCard label="Members" value={totals.members} color="#0ea5e9" />
            {(totals.imported_members ?? 0) > 0 && (
              <StatCard label="Imported" value={totals.imported_members} color="#64748b" />
            )}
          </div>
        </>
      )}

      {/* ── Activity chart ── */}
      <Section title="Activity" meta={
        activity.data?.buckets?.length
          ? `${activity.data.buckets.reduce((s, b) => s + b.count, 0).toLocaleString()} ${pluraliseMetric(activityMetric, 2)}`
          : undefined
      }>
        <div className="activity-panel">
          <div className="activity-panel__head">
            <ActivityControls
              metric={activityMetric}
              setMetric={setActivityMetric}
              groupBy={groupBy}
              setGroupBy={setGroupBy}
              sort={activitySort}
              setSort={setActivitySort}
              userId={activityUserId}
              setUserId={setActivityUserId}
              members={members.data?.members || []}
              fullscreen={activityFullscreen}
              setFullscreen={setActivityFullscreen}
            />
            <p className="stats-meta activity-axis-summary">
              {ACTIVITY_METRICS.find(item => item.id === activityMetric)?.label || 'Messages'} per {groupByNoun(groupBy)}
              {selectedActivityMember ? ` for ${selectedActivityMember.display_name || selectedActivityMember.nickname}` : ''}
              .
            </p>
          </div>
          {activity.loading && <Loading />}
          {activity.error && <StatsError msg={activity.error} />}
          {activity.data && (
            <>
              <ActivityChart
                data={activityBuckets}
                groupBy={groupBy}
                metric={activityMetric}
                onBucketClick={setSelectedActivityBucket}
              />
              {selectedActivityBucket && (
                <div className="activity-selection" role="status">
                  <strong>{formatBucketDate(selectedActivityBucket.date, groupBy)}</strong>
                  <span>
                    {selectedActivityBucket.count.toLocaleString()} {pluraliseMetric(activityMetric, selectedActivityBucket.count)}
                  </span>
                </div>
              )}
            </>
          )}
        </div>
        {activityFullscreen && activity.data && (
          <div className="activity-fullscreen" role="dialog" aria-modal="true" aria-label="Activity chart full screen">
            <div className="activity-fullscreen__bar">
              <strong>
                {ACTIVITY_METRICS.find(item => item.id === activityMetric)?.label || 'Messages'} per {groupByNoun(groupBy)}
              </strong>
              <button type="button" className="stats-icon-button" onClick={() => setActivityFullscreen(false)}>
                Exit
              </button>
            </div>
            <ActivityChart
              data={activityBuckets}
              groupBy={groupBy}
              metric={activityMetric}
              onBucketClick={setSelectedActivityBucket}
            />
          </div>
        )}
      </Section>

      {/* ── Peak hours ── */}
      <Section title="Peak hours" meta="When the group is most active">
        {legacy.loading && <Loading />}
        {legacy.data && (
          <div className="peak-panel">
            <div className="peak-panel__actions">
              <button
                type="button"
                className="stats-icon-button"
                onClick={() => setPeakFullscreen(true)}
              >
                Full screen
              </button>
            </div>
            <PeakHoursHeatmap
              data={legacy.data.peak_day_hours}
              selected={selectedPeakHour}
              onSelect={setSelectedPeakHour}
            />
            {selectedPeakHour && (
              <div className="activity-selection" role="status">
                <strong>{selectedPeakHour.dayLabel}, {selectedPeakHour.hourLabel}</strong>
                <span>{selectedPeakHour.count.toLocaleString()} messages</span>
              </div>
            )}
          </div>
        )}
        {peakFullscreen && legacy.data && (
          <div className="peak-fullscreen" role="dialog" aria-modal="true" aria-label="Peak hours full screen">
            <div className="activity-fullscreen__bar">
              <strong>Peak hours</strong>
              <button type="button" className="stats-icon-button" onClick={() => setPeakFullscreen(false)}>
                Exit
              </button>
            </div>
            <PeakHoursHeatmap
              data={legacy.data.peak_day_hours}
              selected={selectedPeakHour}
              onSelect={setSelectedPeakHour}
            />
            {selectedPeakHour && (
              <div className="activity-selection" role="status">
                <strong>{selectedPeakHour.dayLabel}, {selectedPeakHour.hourLabel}</strong>
                <span>{selectedPeakHour.count.toLocaleString()} messages</span>
              </div>
            )}
          </div>
        )}
      </Section>

      {/* ── Yapometer ── */}
      <Section title="Yapometer 🏆">
        <div className="yap-controls">
          <YapDateControls
            minDate={minYapDate}
            maxDate={maxYapDate}
            fromDate={effectiveYapFrom}
            toDate={effectiveYapTo}
            setFromDate={setYapFrom}
            setToDate={setYapTo}
          />
          <div className="yap-chip-row">
            {LEADERBOARD_METRICS.map(m => (
              <button
                key={m.id}
                type="button"
                className={`stats-chip stats-chip--sm ${leaderMetric === m.id ? 'is-active' : ''}`}
                onClick={() => setLeaderMetric(m.id)}
                aria-pressed={leaderMetric === m.id}
              >
                {m.label}
              </button>
            ))}
          </div>
          <div className="yap-chip-row">
            {NORMALISE_OPTIONS.map(n => (
              <button
                key={n.id}
                type="button"
                className={`stats-chip stats-chip--sm stats-chip--secondary ${leaderNorm === n.id ? 'is-active' : ''}`}
                onClick={() => setLeaderNorm(n.id)}
                aria-pressed={leaderNorm === n.id}
              >
                {n.label}
              </button>
            ))}
          </div>
        </div>
        {leaderboard.loading && <Loading />}
        {leaderboard.error && <StatsError msg={leaderboard.error} />}
        {leaderboard.data?.entries?.length > 0 && (
          <div className="yap-list">
            {leaderboard.data.entries.map(e => (
              <HBar
                key={e.nickname}
                label={e.nickname}
                value={e.value_normalised}
                max={leaderMax}
                suffix={leaderSuffix}
              />
            ))}
          </div>
        )}
      </Section>

      {/* ── Reactions Lab ── */}
      <Section title="Reactions Lab ⚗️" defaultOpen={true}>

        {/* Top reactions */}
        <h3 className="lab-sub-head">Top reactions</h3>
        {topReactions.loading && <Loading />}
        {topReactions.error && <StatsError msg={topReactions.error} />}
        {topReactions.data?.reactions?.length > 0 && (
          <div className="emoji-grid">
            {topReactions.data.reactions.map(({ emoji, count }) => (
              <div key={emoji} className="emoji-cell">
                <span className="emoji-icon">{emoji}</span>
                <span className="emoji-count">{count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        )}

        {/* Reactions by sender */}
        <h3 className="lab-sub-head lab-sub-head--spaced">Most reacts per sender</h3>
        <p className="stats-meta">Reactions received by message sender, with rate per message</p>
        {reactionsBySender.loading && <Loading />}
        {reactionsBySender.error && <StatsError msg={reactionsBySender.error} />}
        {reactionsBySender.data && (
          <ReactionsBySender
            data={reactionsBySender.data}
            topEmojis={topEmojiOptions}
            emoji={reactEmoji}
            onEmojiChange={setReactEmoji}
            sortBy={reactSort}
            onSortChange={setReactSort}
          />
        )}

        {/* Signature matrix */}
        <h3 className="lab-sub-head lab-sub-head--spaced">
          Signature matrix
          <div className="lab-dir-toggle">
            <button
              type="button"
              className={`stats-chip stats-chip--sm ${sigDir === 'given' ? 'is-active' : ''}`}
              onClick={() => setSigDir('given')}
              aria-pressed={sigDir === 'given'}
            >
              Given
            </button>
            <button
              type="button"
              className={`stats-chip stats-chip--sm ${sigDir === 'received' ? 'is-active' : ''}`}
              onClick={() => setSigDir('received')}
              aria-pressed={sigDir === 'received'}
            >
              Received
            </button>
          </div>
        </h3>
        <p className="stats-meta">
          {sigDir === 'given' ? 'Who gives which emoji' : 'Who receives which emoji'}
        </p>
        {sigMatrix.loading && <Loading />}
        {sigMatrix.error && <StatsError msg={sigMatrix.error} />}
        {sigMatrix.data && (
          <SignatureMatrix
            people={sigMatrix.data.people}
            emojis={sigMatrix.data.emojis}
            matrix={sigMatrix.data.matrix}
          />
        )}

        {/* Dyadic heatmap */}
        <h3 className="lab-sub-head lab-sub-head--spaced">Who reacts to whom</h3>
        <p className="stats-meta">Reaction count from row person to column person</p>
        {dyadic.loading && <Loading />}
        {dyadic.error && <StatsError msg={dyadic.error} />}
        {dyadic.data && (
          <DyadicHeatmap
            givers={dyadic.data.givers}
            receivers={dyadic.data.receivers}
            matrix={dyadic.data.matrix}
          />
        )}

        {/* Trends */}
        <h3 className="lab-sub-head lab-sub-head--spaced">Emoji trends over time</h3>
        {trends.loading && <Loading />}
        {trends.error && <StatsError msg={trends.error} />}
        {trends.data && <ReactionTrendsChart series={trends.data.series} groupBy={trends.data.group_by} />}

        {/* Top reacted messages */}
        <h3 className="lab-sub-head lab-sub-head--spaced">Most reacted messages</h3>
        {topReacted.loading && <Loading />}
        {topReacted.error && <StatsError msg={topReacted.error} />}
        {topReacted.data && (
          <TopReactedMessages
            messages={topReacted.data.messages}
            senders={topReacted.data.senders}
            hasMore={topReacted.data.has_more}
            loadingMore={topReacted.loadingMore}
            onLoadMore={handleLoadMoreTopReacted}
            selectedSender={topSender}
            onSenderChange={setTopSender}
            mediaFilter={topMedia}
            onMediaFilterChange={setTopMedia}
            ignoreThumbs={ignoreThumbs === '1'}
            onIgnoreThumbsChange={setIgnoreThumbs}
            onNavigate={onNavigate}
          />
        )}

      </Section>

      {/* ── Poll participation & ideas ── */}
      <div className="stats-two-col">
        {legacy.data?.poll_participation?.length > 0 && (
          <Section title="Poll participation" meta="Distinct polls voted in">
            {legacy.data.poll_participation.map(({ nickname, votes }) => (
              <HBar key={nickname} label={nickname} value={votes} max={legacy.data.poll_participation[0].votes} color="#10b981" suffix=" polls" />
            ))}
          </Section>
        )}
        {legacy.data && Object.keys(legacy.data.idea_status || {}).length > 0 && (
          <Section title="Ideas by status">
            {ideaStatusOrder.map(status => {
              const count = legacy.data.idea_status?.[status] || 0;
              return count > 0 ? (
                <HBar key={status} label={status} value={count} max={ideaMax} color={STATUS_COLORS[status]} />
              ) : null;
            })}
          </Section>
        )}
      </div>
    </section>
  );
}
