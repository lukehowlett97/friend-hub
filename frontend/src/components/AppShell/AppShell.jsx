import React, { useState, useEffect } from 'react';
import './AppShell.css';
import NotificationBell from '../Notifications/NotificationBell.jsx';
import UserAvatar from '../Chat/UserAvatar.jsx';
import RoomSwitcher from './RoomSwitcher.jsx';
import { useAuth } from '../../auth/AuthProvider.jsx';
import { isDemoMode } from '../../api/client.js';

const mainNavItems = [
  { path: '/home',  label: 'Home'  },
  { path: '/chat',  label: 'Chat'  },
  { path: '/items', label: 'Items', isGroup: true },
];

const baseMoreNavItems = [
  { path: '/lore',     label: 'Lore',     icon: '⌘', desc: 'Group memory' },
  { path: '/photos',   label: 'Photos',   icon: '▧', desc: 'Shared uploads' },
  { path: '/stats',    label: 'Stats',    icon: '↗', desc: 'Hub activity' },
  { path: '/topics',   label: 'Topics',   icon: '◇', desc: 'Weekly chat timeline' },
  { path: '/members',  label: 'Members',  icon: '◌', desc: 'People and roles' },
  { path: '/server',   label: 'Server',   icon: '▣', desc: 'System status' },
  { path: '/ai',       label: 'AI',       icon: '✦', desc: 'Hub Bot tools' },
  { path: '/search',   label: 'Search',   icon: '⌕', desc: 'Search everything' },
  { path: '/settings', label: 'Settings', icon: '⚙', desc: 'Theme and prefs' },
];

const itemRoutes = ['/items', '/ideas', '/polls', '/events', '/calendar', '/reminders', '/notes', '/admin/archive'];

function SidebarProfile({ currentPath, onNavigate }) {
  const { user } = useAuth();
  const demoMode = isDemoMode() || user?.is_guest;
  if (!user) return null;
  const isActive = currentPath.startsWith('/profile');
  return (
    <button
      type="button"
      className={`sidebar-profile-btn${isActive ? ' active' : ''}`}
      onClick={() => onNavigate('/profile')}
      title={`Your profile — ${user.nickname}`}
    >
      <UserAvatar nickname={user.nickname} size={26} avatarUrl={user.avatar_url} />
      <span className="sidebar-profile-name">{user.nickname}</span>
    </button>
  );
}

const AppShell = ({ currentPath, onNavigate, onSearch, children }) => {
  const [moreOpen, setMoreOpen] = useState(false);
  const { user } = useAuth();
  const isChatRoute = currentPath === '/chat';

  const moreNavItems = user?.is_owner
    ? [
        ...baseMoreNavItems,
        { path: '/admin/users', label: 'Users', icon: '◎', desc: 'Admin accounts' },
        { path: '/admin/identity', label: 'Identities', icon: '◇', desc: 'Messenger links' },
      ]
    : baseMoreNavItems;

  const isActivePath = (path) => {
    if (path === '/items') return itemRoutes.includes(currentPath);
    if (path === '/events' && currentPath.startsWith('/events/')) return true;
    return currentPath === path;
  };

  const isMoreActive = moreNavItems.some(item => isActivePath(item.path));

  const handleNavigate = (event, path) => {
    event.preventDefault();
    setMoreOpen(false);
    onNavigate(path);
  };

  const handleMoreClick = (e) => {
    e.stopPropagation();
    setMoreOpen(prev => !prev);
  };

  useEffect(() => {
    if (!moreOpen) return;
    const close = () => setMoreOpen(false);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [moreOpen]);

  return (
    <div className="app-shell">
      <aside className="app-sidebar" aria-label="Primary navigation">
        <a className="app-brand" href="/home" onClick={(event) => handleNavigate(event, '/home')}>
          Friend Hub
        </a>

        {!demoMode && <RoomSwitcher />}

        {!demoMode && <button
          type="button"
          className="sidebar-search-input sidebar-search-shortcut"
          onClick={() => onNavigate('/search')}
          aria-label="Go to search"
        >
          Search…
        </button>}

        <nav className="app-nav">
          {(demoMode ? [{ path: '/chat', label: 'Demo chat' }] : mainNavItems).map((item) => (
            <a
              key={item.path}
              className={`app-nav-link ${isActivePath(item.path) ? 'active' : ''}`}
              href={item.path}
              aria-current={isActivePath(item.path) ? 'page' : undefined}
              onClick={(event) => handleNavigate(event, item.path)}
            >
              {item.label}
            </a>
          ))}
          {!demoMode && <button
            type="button"
            className={`app-nav-link app-nav-more-btn ${isMoreActive || moreOpen ? 'active' : ''}`}
            onClick={handleMoreClick}
          >
            More
          </button>}
          {moreOpen && (
            <div className="app-nav-more-items" onClick={e => e.stopPropagation()}>
              {moreNavItems.map((item) => (
                <a
                  key={item.path}
                  className={`app-nav-link app-nav-more-item ${isActivePath(item.path) ? 'active' : ''}`}
                  href={item.path}
                  aria-current={isActivePath(item.path) ? 'page' : undefined}
                  onClick={(event) => handleNavigate(event, item.path)}
                >
                  {item.label}
                </a>
              ))}
            </div>
          )}
        </nav>

        <div className="app-sidebar-footer">
          {demoMode && <div className="demo-session-notice">You’re chatting as {user.nickname}. This temporary demo session does not create an account.</div>}
          <SidebarProfile currentPath={currentPath} onNavigate={onNavigate} />
          <NotificationBell onNavigate={onNavigate} />
        </div>
      </aside>

      <main className={`app-main${isChatRoute ? ' app-main--chat' : ''}`}>{children}</main>

      <nav className="mobile-bottom-nav" aria-label="Mobile primary navigation">
        {(demoMode ? [{ path: '/chat', label: 'Demo chat' }] : mainNavItems).map((item) => (
          <a
            key={item.path}
            className={`mobile-nav-link ${isActivePath(item.path) ? 'active' : ''}`}
            href={item.path}
            aria-current={isActivePath(item.path) ? 'page' : undefined}
            onClick={(event) => handleNavigate(event, item.path)}
          >
            {item.mobileLabel || item.label}
          </a>
        ))}
        {!demoMode && <button
          type="button"
          className={`mobile-nav-link mobile-nav-more-btn ${isMoreActive || moreOpen ? 'active' : ''}`}
          onClick={handleMoreClick}
        >
          More
        </button>}
        {user && !demoMode && (
          <button
            type="button"
            className={`mobile-nav-profile-btn${currentPath.startsWith('/profile') ? ' active' : ''}`}
            onClick={() => {
              setMoreOpen(false);
              onNavigate('/profile');
            }}
            title={`Your profile — ${user.nickname}`}
            aria-label={`Open profile for ${user.nickname}`}
            aria-current={currentPath.startsWith('/profile') ? 'page' : undefined}
          >
            <UserAvatar nickname={user.nickname} size={28} avatarUrl={user.avatar_url} />
          </button>
        )}
      </nav>

      {moreOpen && (
        <div className="more-popup" onClick={e => e.stopPropagation()}>
          {moreNavItems.map((item) => (
            <a
              key={item.path}
              className={`more-popup-item ${isActivePath(item.path) ? 'active' : ''}`}
              href={item.path}
              data-icon={item.icon}
              onClick={(event) => handleNavigate(event, item.path)}
            >
              <span className="more-popup-item__label">{item.label}</span>
              <span className="more-popup-item__desc">{item.desc}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
};

export default AppShell;
