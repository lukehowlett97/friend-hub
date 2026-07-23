import React, { useMemo, useState } from 'react';
import { ActivityCard } from './ActivityFeedCards.jsx';
import {
  createPinnedItemActivity,
  createActivePollActivity,
  createUpcomingEventActivity,
  createRecentEditActivity,
  createOpenReminderActivity,
  createHubItemUpdateActivity,
  createAIMemoryActivity,
  formatRelativeTime,
} from './ActivityFeedTypes.js';
import './WhatsHappeningFeed.css';

/**
 * Filter button component
 */
const FilterChip = ({ label, isActive, onClick }) => (
  <button
    type="button"
    className={`feed-filter-chip${isActive ? ' active' : ''}`}
    onClick={onClick}
    aria-pressed={isActive}
  >
    {label}
  </button>
);

/**
 * Empty state for the feed
 */
const EmptyFeedState = () => (
  <div className="feed-empty-state">
    <div className="feed-empty-icon">🌟</div>
    <p className="feed-empty-title">All caught up!</p>
    <p className="feed-empty-subtitle">No activity at the moment. Start creating or stay tuned for group updates.</p>
  </div>
);

/**
 * Main "What's happening" feed component
 * Displays mixed activity types in a dynamic, personalized feed
 */
export const WhatsHappeningFeed = ({ dashboard, onNavigate }) => {
  const [activeFilter, setActiveFilter] = useState('all');

  // ────── Build unified activity feed from dashboard data ──────

  const activities = useMemo(() => {
    const allActivities = [];

    // Pinned items - highest priority
    if (dashboard?.pinned_items?.length > 0) {
      dashboard.pinned_items.forEach((item) => {
        const activity = createPinnedItemActivity(item, item.type || 'hub_item');
        allActivities.push(activity);
      });
    }

    // Active polls - high engagement value
    if (dashboard?.active_polls?.length > 0) {
      dashboard.active_polls.forEach((poll) => {
        const activity = createActivePollActivity(poll);
        allActivities.push(activity);
      });
    }

    // Upcoming events - time-sensitive
    if (dashboard?.upcoming_events?.length > 0) {
      dashboard.upcoming_events.forEach((event) => {
        const activity = createUpcomingEventActivity(event);
        allActivities.push(activity);
      });
    }

    // Open reminders - need attention
    if (dashboard?.open_reminders?.length > 0) {
      dashboard.open_reminders.forEach((reminder) => {
        const activity = createOpenReminderActivity(reminder);
        allActivities.push(activity);
      });
    }

    // Recent activity - shows engagement
    if (dashboard?.activity?.length > 0) {
      // Show top 3-5 most recent activities
      dashboard.activity.slice(0, 3).forEach((activityItem) => {
        const activity = createRecentEditActivity(activityItem);
        allActivities.push(activity);
      });
    }

    // AI suggestions - personalized value
    if (dashboard?.ai_suggestions?.length > 0) {
      dashboard.ai_suggestions.forEach((suggestion) => {
        const activity = createAIMemoryActivity(suggestion);
        allActivities.push(activity);
      });
    }

    // AI memory - contextual reminders
    if (dashboard?.ai_memories?.length > 0) {
      dashboard.ai_memories.forEach((memory) => {
        const activity = createAIMemoryActivity(memory);
        allActivities.push(activity);
      });
    }

    return allActivities;
  }, [dashboard]);

  // ────── Filter activities ──────

  const filteredActivities = useMemo(() => {
    if (activeFilter === 'all') return activities;

    const filterMap = {
      live: (a) => ['active-poll', 'upcoming-event'].includes(a.type),
      pinned: (a) => a.type === 'pinned-item',
      upcoming: (a) => a.type === 'upcoming-event' || a.type === 'open-reminder',
      ai: (a) => a.type === 'ai-memory',
    };

    const filterFn = filterMap[activeFilter];
    return filterFn ? activities.filter(filterFn) : activities;
  }, [activities, activeFilter]);

  // ────── Render ──────

  if (!dashboard) {
    return (
      <section className="whats-happening-feed">
        <div className="feed-loading">Loading activity…</div>
      </section>
    );
  }

  return (
    <section className="whats-happening-feed">
      <div className="feed-header">
        <h2 className="feed-title">What's happening</h2>
        <p className="feed-subtitle">Live group activity and updates</p>
      </div>

      {/* Filter chips */}
      <div className="feed-filters">
        <FilterChip
          label="All"
          isActive={activeFilter === 'all'}
          onClick={() => setActiveFilter('all')}
        />
        <FilterChip
          label="Live"
          isActive={activeFilter === 'live'}
          onClick={() => setActiveFilter('live')}
        />
        {(dashboard?.pinned_items?.length > 0) && (
          <FilterChip
            label="Pinned"
            isActive={activeFilter === 'pinned'}
            onClick={() => setActiveFilter('pinned')}
          />
        )}
        {(dashboard?.upcoming_events?.length > 0 || dashboard?.open_reminders?.length > 0) && (
          <FilterChip
            label="Upcoming"
            isActive={activeFilter === 'upcoming'}
            onClick={() => setActiveFilter('upcoming')}
          />
        )}
        {(dashboard?.ai_suggestions?.length > 0 || dashboard?.ai_memories?.length > 0) && (
          <FilterChip
            label="AI"
            isActive={activeFilter === 'ai'}
            onClick={() => setActiveFilter('ai')}
          />
        )}
      </div>

      {/* Feed cards */}
      <div className="feed-cards-container">
        {filteredActivities.length > 0 ? (
          <div className="feed-cards">
            {filteredActivities.map((activity) => (
              <ActivityCard key={`${activity.type}-${activity.id}`} activity={activity} onNavigate={onNavigate} />
            ))}
          </div>
        ) : (
          <EmptyFeedState />
        )}
      </div>
    </section>
  );
};

/**
 * Mock data generator for development/testing
 */
export function generateMockWhatsHappeningData() {
  const now = new Date();
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  const twoDaysAgo = new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000);
  const threeDaysFromNow = new Date(now.getTime() + 3 * 24 * 60 * 60 * 1000);

  return {
    pinned_items: [
      {
        id: '1',
        type: 'poll',
        title: 'Ibiza planning',
        short_id: 'P-4',
        question: 'Ibiza planning',
        comment_count: 2,
        created_at: twoDaysAgo.toISOString(),
      },
    ],
    active_polls: [
      {
        id: '2',
        type: 'poll',
        question: 'Friday pub?',
        short_id: 'P-5',
        options: [{}, {}, {}],
        responses: [{}, {}, {}],
        deadline_at: now.toISOString(),
        created_at: now.toISOString(),
      },
    ],
    upcoming_events: [
      {
        id: '3',
        type: 'event',
        title: 'Football',
        short_id: 'E-2',
        event_start_at: tomorrow.toISOString(),
        location: 'Park',
        invites: [{}, {}, {}, {}],
        created_at: now.toISOString(),
      },
      {
        id: '4',
        type: 'event',
        title: 'Team Lunch',
        short_id: 'E-3',
        event_start_at: threeDaysFromNow.toISOString(),
        location: 'Downtown',
        invites: [{}, {}, {}],
        created_at: now.toISOString(),
      },
    ],
    open_reminders: [
      {
        id: '5',
        type: 'reminder',
        title: 'Book accommodation',
        short_id: 'R-1',
        due_at: threeDaysFromNow.toISOString(),
        assignees: [{ nickname: 'Alex' }],
        created_at: now.toISOString(),
      },
    ],
    activity: [
      {
        id: 'a1',
        target_type: 'poll',
        target_id: '2',
        target_name: 'Friday plans',
        action: 'comment',
        summary: 'Ryan: Friday pub?',
        actor: { nickname: 'Ryan', avatar_url: null },
        created_at: now.toISOString(),
      },
      {
        id: 'a2',
        target_type: 'event',
        target_id: '3',
        target_name: 'Football',
        action: 'rsvp',
        summary: 'Jamie: Going to Football',
        actor: { nickname: 'Jamie', avatar_url: null },
        created_at: new Date(now.getTime() - 30 * 60 * 1000).toISOString(),
      },
    ],
    ai_suggestions: [
      {
        id: 'ai1',
        suggestion: 'Create a poll for Ibiza dates?',
        context: 'Based on recent planning discussion',
        action_label: 'Create',
        action_route: '/polls/new?context=ibiza',
        created_at: now.toISOString(),
      },
    ],
    counts: {
      activity: 2,
      events: 2,
      polls: 2,
      items: 1,
    },
  };
}

/**
 * Alternative compact version for displaying in detail panels
 */
export const CompactWhatsHappeningFeed = ({ activities, onNavigate, maxItems = 5 }) => (
  <div className="compact-feed">
    {activities.slice(0, maxItems).map((activity) => (
      <ActivityCard key={`${activity.type}-${activity.id}`} activity={activity} onNavigate={onNavigate} />
    ))}
  </div>
);
