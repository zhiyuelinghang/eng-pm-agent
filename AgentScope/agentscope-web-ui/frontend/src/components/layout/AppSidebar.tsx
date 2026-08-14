import {
	BotMessageSquare,
	BrainCircuit,
	Calendars,
	Compass,
	Crown,
	Database,
	KeyRound,
	Languages,
	LibraryBig,
	LogOut,
	MessageSquareText,
} from 'lucide-react';
import { useOnborda } from 'onborda';
import { useNavigate, useLocation } from 'react-router-dom';

import { clearAuthSession } from '@/api/client';
import { CHAT_TOUR_NAME } from '@/components/tour/chatTourSteps';
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarGroupContent,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
} from '@/components/ui/sidebar';
import i18n from '@/i18n';
import { useTranslation } from '@/i18n/useI18n';

export function AppSidebar() {
	const navigate = useNavigate();
	const location = useLocation();
	const { t } = useTranslation();
	const { startOnborda } = useOnborda();

	const handleStartTour = () => {
		if (!location.pathname.startsWith('/chat')) {
			// Page not mounted yet — leave a flag, navigate, and let the
			// ChatTourController auto-trigger after ChatPage mounts.
			sessionStorage.setItem('force_tour', '1');
			navigate('/chat');
		} else {
			startOnborda(CHAT_TOUR_NAME);
		}
	};

	const handleToggleLanguage = () => {
		const next = i18n.language.startsWith('zh') ? 'en' : 'zh';
		i18n.changeLanguage(next);
	};

	const handleLogout = () => {
		clearAuthSession();
		navigate('/setup', { replace: true });
	};

	return (
		<Sidebar collapsible="none" className="w-[calc(var(--sidebar-width-icon)+1px)]! border-r">
			<SidebarHeader>
				<div className="flex items-center justify-center h-12 mt-2">
					<img
						src="/dobby.svg"
						alt="Dobby"
						title={t('brand.managementCenter')}
						className="size-8 rounded-[10px] shadow-[0_5px_14px_rgba(201,86,34,0.24)]"
					/>
				</div>
			</SidebarHeader>
			<SidebarContent>
				<SidebarGroup>
					<SidebarGroupContent>
						<SidebarMenu>
							<SidebarMenuItem key={'chat'}>
								<SidebarMenuButton
									tooltip={{ children: t('common.chat'), hidden: false }}
									isActive={
										location.pathname === '/chat' ||
										location.pathname.startsWith('/chat/')
									}
									onClick={() => navigate('/chat')}
									className="px-2.5 md:px-2"
								>
									<BotMessageSquare />
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{
										children: t('common.platformAudit'),
										hidden: false,
									}}
									isActive={location.pathname === '/platform-audit'}
									onClick={() => navigate('/platform-audit')}
									className="px-2"
								>
									<MessageSquareText />
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{
										children: t('common.platformSettings'),
										hidden: false,
									}}
									isActive={location.pathname === '/platform-settings'}
									onClick={() => navigate('/platform-settings')}
									className="px-2"
								>
									<Crown />
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{
										children: t('common.memorySettings'),
										hidden: false,
									}}
									isActive={location.pathname === '/memory-settings'}
									onClick={() => navigate('/memory-settings')}
									className="px-2"
								>
									<BrainCircuit />
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.schedule'), hidden: false }}
									isActive={location.pathname === '/schedule'}
									onClick={() => navigate('/schedule')}
									className="px-2"
								>
									<Calendars />
								</SidebarMenuButton>
							</SidebarMenuItem>
						</SidebarMenu>
					</SidebarGroupContent>
				</SidebarGroup>
				<SidebarGroup>
					<SidebarGroupContent>
						<SidebarMenu>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.credential'), hidden: false }}
									isActive={location.pathname === '/credential'}
									onClick={() => navigate('/credential')}
									className="px-2"
								>
									<KeyRound />
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{
										children: t('common.engineeringKnowledge'),
										hidden: false,
									}}
									isActive={location.pathname === '/engineering-knowledge'}
									onClick={() => navigate('/engineering-knowledge')}
									aria-label={t('common.engineeringKnowledge')}
									className="px-2"
								>
									<Database />
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip={{ children: t('common.knowledge'), hidden: false }}
									isActive={location.pathname === '/knowledge'}
									onClick={() => navigate('/knowledge')}
									className="px-2"
								>
									<LibraryBig />
								</SidebarMenuButton>
							</SidebarMenuItem>
						</SidebarMenu>
					</SidebarGroupContent>
				</SidebarGroup>
			</SidebarContent>
			<SidebarFooter>
				<SidebarMenu>
					<SidebarMenuItem>
						<SidebarMenuButton
							tooltip={{
								children: i18n.language.startsWith('zh')
									? t('common.switchToEn')
									: t('common.switchToZh'),
								hidden: false,
							}}
							onClick={handleToggleLanguage}
							className="px-2"
						>
							<Languages />
						</SidebarMenuButton>
					</SidebarMenuItem>
					<SidebarMenuItem>
						<SidebarMenuButton
							tooltip={{ children: t('tour.trigger'), hidden: false }}
							onClick={handleStartTour}
							className="px-2"
						>
							<Compass />
						</SidebarMenuButton>
					</SidebarMenuItem>
					<SidebarMenuItem>
						<SidebarMenuButton
							tooltip={{ children: t('common.logout'), hidden: false }}
							onClick={handleLogout}
							className="px-2"
						>
							<LogOut />
						</SidebarMenuButton>
					</SidebarMenuItem>
				</SidebarMenu>
			</SidebarFooter>
		</Sidebar>
	);
}
