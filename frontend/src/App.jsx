import React, { useEffect, useState } from 'react';
import Chat from './components/Chat/Chat.jsx';
import AppShell from './components/AppShell/AppShell.jsx';
import HomePage from './pages/HomePage.jsx';
import ItemsPage from './pages/ItemsPage.jsx';
import IdeasPage from './pages/IdeasPage.jsx';
import MembersPage from './pages/MembersPage.jsx';
import CalendarPage from './pages/CalendarPage.jsx';
import EventDetailPage from './pages/EventDetailPage.jsx';
import EventsPage from './pages/EventsPage.jsx';
import PollsPage from './pages/PollsPage.jsx';
import PhotosPage from './pages/PhotosPage.jsx';
import RemindersPage from './pages/RemindersPage.jsx';
import NotesPage from './pages/NotesPage.jsx';
import NoteDetailPage from './pages/NoteDetailPage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';
import SearchPage from './pages/SearchPage.jsx';
import StatsPage from './pages/StatsPage.jsx';
import TopicsPage from './pages/TopicsPage.jsx';
import ServerPage from './pages/ServerPage.jsx';
import AIPage from './pages/AIPage.jsx';
import GroupLorePage from './pages/GroupLorePage.jsx';
import ProfilePage from './pages/ProfilePage.jsx';
import AdminUsersPage from './pages/AdminUsersPage.jsx';
import AdminIdentityPage from './pages/AdminIdentityPage.jsx';
import ArchivePage from './pages/ArchivePage.jsx';
import WelcomePage from './pages/WelcomePage.jsx';
import JoinPage from './pages/JoinPage.jsx';
import InstallPrompt from './components/PWA/InstallPrompt.jsx';
import GlobalChatNotifications from './components/Notifications/GlobalChatNotifications.jsx';
import { AuthProvider, useAuth } from './auth/AuthProvider.jsx';
import { ThemeProvider } from './theme/ThemeProvider.jsx';
import './App.css';

const routes = new Set(['/home', '/items', '/ideas', '/polls', '/events', '/calendar', '/reminders', '/notes', '/chat', '/photos', '/members', '/settings', '/search', '/stats', '/topics', '/server', '/ai', '/lore', '/admin/users', '/admin/identity', '/admin/archive']);

function normalizePath(pathname) {
  pathname = pathname.split('?')[0];
  if (pathname === '/') return '/home';
  if (pathname === '/demo') return '/chat';
  if (/^\/events\/\d+$/.test(pathname)) return pathname;
  if (/^\/notes\/\d+$/.test(pathname)) return pathname;
  if (/^\/profile(?:\/[^/]+)?$/.test(pathname)) return pathname;
  return routes.has(pathname) ? pathname : '/home';
}

function parseMessageIds(value) {
  if (!value) return [];
  return value
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isInteger(item) && item > 0);
}

function AuthenticatedApp() {
  const [currentPath, setCurrentPath] = useState(() => normalizePath(window.location.pathname));
  const [currentSearch, setCurrentSearch] = useState(() => window.location.search);
  const [searchQuery, setSearchQuery] = useState('');
  const { user } = useAuth();

  useEffect(() => {
    if (window.location.pathname !== currentPath) {
      window.history.replaceState({}, '', currentPath);
    }

    const handlePopState = () => {
      setCurrentPath(normalizePath(window.location.pathname));
      setCurrentSearch(window.location.search);
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigate = (path) => {
    const nextPath = normalizePath(path);
    window.history.pushState({}, '', path);
    setCurrentPath(nextPath);
    setCurrentSearch(window.location.search);
  };

  const handleSearch = (q) => {
    setSearchQuery(q);
    navigate('/search');
  };

  const renderRoute = () => {
    const eventMatch   = currentPath.match(/^\/events\/(\d+)$/);
    if (eventMatch) return <EventDetailPage eventId={Number(eventMatch[1])} onNavigate={navigate} />;

    const noteMatch = currentPath.match(/^\/notes\/(\d+)$/);
    if (noteMatch) return <NoteDetailPage noteId={Number(noteMatch[1])} onNavigate={navigate} />;

    const profileMatch = currentPath.match(/^\/profile(?:\/([^/]+))?$/);
    if (profileMatch) return <ProfilePage username={profileMatch[1]} onNavigate={navigate} />;

    switch (currentPath) {
      case '/chat': {
        const chatParams = new URLSearchParams(currentSearch);
        const targetMessageId = Number(chatParams.get('message')) || null;
        const highlightedMessageIds = [
          ...new Set([
            ...parseMessageIds(chatParams.get('highlight')),
            ...(targetMessageId ? [targetMessageId] : []),
          ]),
        ];
        return (
          <div className="page-chat">
            <Chat
              targetMessageId={targetMessageId}
              highlightedMessageIds={highlightedMessageIds}
              draftMessage={chatParams.get('draft') || ''}
            />
          </div>
        );
      }
      case '/items':
        return <ItemsPage onNavigate={navigate} />;
      case '/ideas':
        return <IdeasPage onNavigate={navigate} />;
      case '/polls':
        return <PollsPage onNavigate={navigate} />;
      case '/events':
        return <EventsPage onNavigate={navigate} />;
      case '/calendar':
        return <CalendarPage onNavigate={navigate} />;
      case '/reminders':
        return <RemindersPage onNavigate={navigate} />;
      case '/notes':
        return <NotesPage onNavigate={navigate} />;
      case '/photos':
        return <PhotosPage />;
      case '/members':
        return <MembersPage onNavigate={navigate} />;
      case '/settings':
        return <SettingsPage />;
      case '/stats':
        return <StatsPage onNavigate={navigate} />;
      case '/topics':
        return <TopicsPage onNavigate={navigate} />;
      case '/server':
        return <ServerPage />;
      case '/ai':
        return <AIPage />;
      case '/lore':
        return <GroupLorePage onNavigate={navigate} />;
      case '/admin/users':
        return user?.is_owner ? <AdminUsersPage /> : null;
      case '/admin/identity':
        return user?.is_owner ? <AdminIdentityPage /> : null;
      case '/admin/archive':
        return user?.is_owner ? <ArchivePage /> : null;
      case '/search':
        return <SearchPage query={searchQuery} onNavigate={navigate} />;
      case '/home':
      default:
        return <HomePage onNavigate={navigate} />;
    }
  };

  return (
    <AppShell currentPath={currentPath} onNavigate={navigate} onSearch={handleSearch}>
      {currentPath !== '/chat' && <GlobalChatNotifications onNavigate={navigate} />}
      {renderRoute()}
    </AppShell>
  );
}

function AppContent() {
  const { isLoading, isAuthenticated } = useAuth();
  const inviteMatch = window.location.pathname.match(/^\/join\/([^/]+)$/);
  const demoPath = window.location.pathname === '/demo';

  const leaveJoinRoute = () => {
    window.history.replaceState({}, '', '/');
  };

  if (isLoading) return null;
  if (!isAuthenticated) {
    if (inviteMatch) {
      return <JoinPage inviteCode={decodeURIComponent(inviteMatch[1])} onExpired={leaveJoinRoute} />;
    }
    return <WelcomePage />;
  }
  // Authenticated: if we arrived via a /join link (e.g. an already-logged-in user
  // tapped an invite), drop the join path so normal routing takes over.
  if (inviteMatch) leaveJoinRoute();
  return <AuthenticatedApp />;
}

function App() {
  return (
    <AuthProvider>
      <ThemeProvider>
        <InstallPrompt />
        <AppContent />
      </ThemeProvider>
    </AuthProvider>
  );
}

export default App;
