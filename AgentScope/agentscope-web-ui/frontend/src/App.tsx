import { Onborda, OnbordaProvider } from 'onborda';
import { useMemo, useState } from 'react';
import { createBrowserRouter, Navigate, RouterProvider, useNavigate } from 'react-router-dom';
import { Toaster } from 'sonner';

import { hasValidAuthSession } from '@/api/client';
import { RouteError } from '@/components/error/RouteError';
import { AppLayout } from '@/components/layout/AppLayout';
import { buildChatTour } from '@/components/tour/chatTourSteps';
import { TourCard } from '@/components/tour/TourCard';
import { UploadProvider } from '@/context/UploadContext';
import { useTranslation } from '@/i18n/useI18n';
import { AgentWorkbenchPage } from '@/pages/agents';
import { ChatPage } from '@/pages/chat';
import { CredentialPage } from '@/pages/credential';
import { EngineeringKnowledgePage } from '@/pages/engineering-knowledge';
import { MemoryManagementPage } from '@/pages/memory-management';
import { MemorySettingsPage } from '@/pages/memory-settings';
import { PermissionReviewPage } from '@/pages/permission-review';
import { PlatformAuditPage } from '@/pages/platform-audit';
import { SchedulePage } from '@/pages/schedule';
import { SetupPage } from '@/pages/setup';
import { SystemToolsPage } from '@/pages/system-tools';

function SetupPageRoute() {
	const navigate = useNavigate();
	return (
		<>
			<div className="h-screen">
				<SetupPage onComplete={() => navigate('/')} />
			</div>
			<Toaster richColors position="top-right" />
		</>
	);
}

const router = createBrowserRouter([
	{
		element: <AppLayout />,
		errorElement: <RouteError />,
		children: [
			{
				// Content-level boundary: a crash in a page replaces only
				// the Outlet area, so AppLayout (the icon rail / nav) stays
				// usable. The parent route keeps its own errorElement as a
				// last-resort catch-all for AppLayout/AppSidebar crashes.
				errorElement: <RouteError />,
				children: [
					{ path: '/', element: <Navigate to="/platform-agents" replace /> },
					{
						path: '/chat/:agentId?/:sessionId?/:memberId?',
						element: <ChatPage />,
					},
					{ path: '/schedule', element: <SchedulePage /> },
					{ path: '/credential', element: <CredentialPage /> },
					{ path: '/permission-review', element: <PermissionReviewPage /> },
					{ path: '/system-tools', element: <SystemToolsPage /> },
					{
						path: '/platform-settings',
						element: <Navigate to="/platform-agents" replace />,
					},
					{
						path: '/platform-agents/:selection?',
						element: <AgentWorkbenchPage key="primary" mode="primary" />,
					},
					{
						path: '/business-tools/:selection?',
						element: <AgentWorkbenchPage key="business" mode="business" />,
					},
					{ path: '/memory-settings', element: <MemorySettingsPage /> },
					{ path: '/memory-management', element: <MemoryManagementPage /> },
					{ path: '/platform-audit', element: <PlatformAuditPage /> },
					{
						path: '/engineering-knowledge',
						element: <EngineeringKnowledgePage />,
					},
					{
						path: '/knowledge',
						element: <Navigate to="/engineering-knowledge" replace />,
					},
					{
						path: '/knowledge/:kbId',
						element: <Navigate to="/engineering-knowledge" replace />,
					},
				],
			},
		],
	},
	{ path: '/setup', element: <SetupPageRoute />, errorElement: <RouteError /> },
]);

function App() {
	const { t } = useTranslation();
	const [setupComplete, setSetupComplete] = useState(() => hasValidAuthSession());
	const tours = useMemo(() => [buildChatTour(t)], [t]);

	if (!setupComplete) {
		return (
			<SetupPage
				onComplete={() => {
					window.history.replaceState(null, '', '/');
					setSetupComplete(true);
				}}
			/>
		);
	}

	return (
		<OnbordaProvider>
			<Onborda
				steps={tours}
				cardComponent={TourCard}
				shadowOpacity="0.6"
				cardTransition={{ type: 'spring', duration: 0.4 }}
			>
				<UploadProvider>
					<RouterProvider router={router} />
				</UploadProvider>
				<Toaster richColors position="top-right" />
			</Onborda>
		</OnbordaProvider>
	);
}

export default App;
