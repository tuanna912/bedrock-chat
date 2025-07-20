import App from './App.tsx';
import ChatPage from './pages/ChatPage.tsx';
import NotFound from './pages/NotFound.tsx';
import BotExplorePage from './pages/BotExplorePage.tsx';
import BotKbEditPage from './features/knowledgeBase/pages/BotKbEditPage.tsx';
import BotApiSettingsPage from './pages/BotApiSettingsPage.tsx';
import AdminSharedBotAnalyticsPage from './pages/AdminSharedBotAnalyticsPage.tsx';
import AdminApiManagementPage from './pages/AdminApiManagementPage.tsx';
import AdminBotManagementPage from './pages/AdminBotManagementPage.tsx';
import { useTranslation } from 'react-i18next';
import {
  createBrowserRouter,
  matchRoutes,
  RouteObject,
  useLocation,
  Navigate,
} from 'react-router-dom';
import React, { useMemo } from 'react';
import BotDiscoverPage from './features/discover/pages/BotDiscoverPage.tsx';
import BotRecentlyUsedPage from './pages/BotRecentlyUsedPage.tsx';
import BotStarredPage from './pages/BotStarredPage.tsx';
import ConversationHistoryPage from './pages/ConversationHistoryPage.tsx';
import useLoginUser from './hooks/useLoginUser';

// Component để bảo vệ các routes cần quyền CreatingBotAllowed hoặc Admin
const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAllowCreatingBot, isAdmin } = useLoginUser();
  
  // Nếu user chỉ có PublishAllowed mà không có CreatingBotAllowed hoặc Admin
  // thì redirect về trang admin hoặc trang khác phù hợp
  if (!isAllowCreatingBot && !isAdmin) {
    return <Navigate to="/admin/api-management" replace />;
  }
  
  return <>{children}</>;
};

const rootChildren = [
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <ChatPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/bot/my',
    element: (
      <ProtectedRoute>
        <BotExplorePage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/bot/recently-used',
    element: (
      <ProtectedRoute>
        <BotRecentlyUsedPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/bot/starred',
    element: (
      <ProtectedRoute>
        <BotStarredPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/bot/discover',
    element: (
      <ProtectedRoute>
        <BotDiscoverPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/bot/new',
    element: (
      <ProtectedRoute>
        <BotKbEditPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/bot/edit/:botId',
    element: (
      <ProtectedRoute>
        <BotKbEditPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/bot/api-settings/:botId',
    element: <BotApiSettingsPage />,
  },
  {
    path: '/bot/:botId',
    element: (
      <ProtectedRoute>
        <ChatPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/conversations',
    element: (
      <ProtectedRoute>
        <ConversationHistoryPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/admin/shared-bot-analytics',
    element: <AdminSharedBotAnalyticsPage />,
  },
  {
    path: '/admin/api-management',
    element: <AdminApiManagementPage />,
  },
  {
    path: '/admin/bot/:botId',
    element: <AdminBotManagementPage />,
  },
  {
    path: '/:conversationId',
    element: (
      <ProtectedRoute>
        <ChatPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '*',
    element: <NotFound />,
  },
] as const;

const routes = [
  {
    path: '/',
    element: <App />,
    children: rootChildren,
  },
];

type AllPaths = (typeof rootChildren)[number]['path'];

const getAllPaths = (routes: typeof rootChildren): AllPaths[] =>
  routes.map(({ path }) => path);

export const allPaths = getAllPaths(rootChildren);

export const usePageLabel = () => {
  const { t } = useTranslation();
  const pageLabel: { path: (typeof allPaths)[number]; label: string }[] = [
    { path: '/bot/my', label: t('bot.my.label.pageTitle') },
    { path: '/bot/discover', label: t('discover.pageTitle') },
    {
      path: '/admin/shared-bot-analytics',
      label: t('admin.botAnalytics.label.pageTitle'),
    },
    {
      path: '/admin/api-management',
      label: t('admin.apiManagement.label.pageTitle'),
    },
  ];

  const getPageLabel = (pagePath: (typeof allPaths)[number]) =>
    pageLabel.find(({ path }) => path === pagePath)?.label;
  return { pageLabel, getPageLabel };
};

export const router = createBrowserRouter(routes as unknown as RouteObject[]);

type ConversationRoutes = { path: (typeof allPaths)[number] }[];

export const usePageTitlePathPattern = () => {
  const location = useLocation();

  const conversationRoutes: ConversationRoutes = useMemo(
    () => [
      { path: '/:conversationId' },
      { path: '/bot/:botId' },
      { path: '/' },
      { path: '*' },
    ],
    []
  );
  const notConversationRoutes = useMemo(
    () =>
      allPaths
        .filter(
          (pattern) => !conversationRoutes.find(({ path }) => path === pattern)
        )
        .map((pattern) => ({ path: pattern })),
    [conversationRoutes]
  );
  const matchedRoutes = useMemo(() => {
    return matchRoutes(notConversationRoutes, location);
  }, [location, notConversationRoutes]);

  const pathPattern = useMemo(
    () => matchedRoutes?.[0]?.route.path ?? '/',
    [matchedRoutes]
  );

  const isConversationOrNewChat = useMemo(
    () => !matchedRoutes?.length,
    [matchedRoutes]
  );
  return { isConversationOrNewChat, pathPattern };
};
