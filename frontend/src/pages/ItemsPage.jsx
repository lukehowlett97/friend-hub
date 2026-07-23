import React from 'react';
import { useAuth } from '../auth/AuthProvider.jsx';
import './ItemsPage.css';

const baseItems = [
  { path: '/ideas', label: 'Ideas', icon: '!', status: 'Open', description: 'Store pub ideas, trips, food places, and random schemes' },
  { path: '/polls', label: 'Polls', icon: '%', status: 'Vote', description: 'Quick decisions: dates, locations, activities, times' },
  { path: '/events', label: 'Events', icon: '@', status: 'Plan', description: 'Plan group activities with dates, times, attendees' },
  { path: '/reminders', label: 'Reminders', icon: '^', status: 'Due', description: 'Shared reminders for plans and admin tasks' },
  { path: '/notes', label: 'Notes', icon: '=', status: 'Write', description: 'Shared text for memories, plans, rules, and recommendations' },
  { path: '/calendar', label: 'Calendar', icon: '#', status: 'View', description: 'View upcoming events and activities on a calendar' },
  { path: '/photos', label: 'Photos', icon: '+', status: 'New', description: 'Keep group memories, uploads, and event photos together' },
];

const adminItems = [
  { path: '/admin/archive', label: 'Archive', icon: '~', status: 'Admin', description: 'View all deleted ideas, polls, events, and reminders' },
];

const ItemsPage = ({ onNavigate }) => {
  const { user } = useAuth();
  const items = user?.is_owner ? [...baseItems, ...adminItems] : baseItems;

  const handleNavigate = (event, path) => {
    event.preventDefault();
    onNavigate(path);
  };

  return (
    <section className="page items-page">
      <header className="page-header">
        <h1>Items</h1>
        <p className="page-subtitle">Manage ideas, polls, events, reminders, and see everything on a calendar.</p>
      </header>

      <div className="items-grid">
        {items.map((item) => (
          <a
            key={item.path}
            href={item.path}
            className="items-card"
            onClick={(event) => handleNavigate(event, item.path)}
          >
            <span className="items-card__icon" aria-hidden="true">{item.icon}</span>
            <span className="items-card__content">
              <span className="items-card__topline">
                <h2>{item.label}</h2>
                <em>{item.status}</em>
              </span>
              <p>{item.description}</p>
            </span>
          </a>
        ))}
      </div>
    </section>
  );
};

export default ItemsPage;
