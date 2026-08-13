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
import { ChatPage } from '@/pages/chat';
import { CredentialPage } from '@/pages/credential';
import { EngineeringKnowledgePage } from '@/pages/engineering-knowledge';
import { KnowledgePage } from '@/pages/knowledge';
import { PlatformAuditPage } from '@/pages/platform-audit';
import { PlatformSettingsPage } from '@/pages/platform-settings';
import { SchedulePage } from '@/pages/schedule';
import { SetupPage } from '@/pages/setup';

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
					{ path: '/', element: <Navigate to="/chat" replace /> },
					{
						path: '/chat/:agentId?/:sessionId?/:memberId?',
						element: <ChatPage />,
					},
					{ path: '/schedule', element: <SchedulePage /> },
					{ path: '/credential', element: <CredentialPage /> },
					{ path: '/platform-settings', element: <PlatformSettingsPage /> },
					{ path: '/platform-audit', element: <PlatformAuditPage /> },
					{
						path: '/engineering-knowledge',
						element: <EngineeringKnowledgePage />,
					},
					{ path: '/knowledge', element: <KnowledgePage /> },
					{ path: '/knowledge/:kbId', element: <KnowledgePage /> },
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
