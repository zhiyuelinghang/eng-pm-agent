import {
	BotMessageSquare,
	BrainCircuit,
	BookUser,
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
		<Sidebar collapsible="none" className="w-44! shrink-0 border-r md:w-52!">
			<SidebarHeader>
				<div className="flex min-h-16 items-center gap-3 px-2 py-3">
					<img
						src="/dobby.svg"
						alt="Dobby"
						title={t('brand.managementCenter')}
						className="size-8 shrink-0 rounded-[10px] shadow-[0_5px_14px_rgba(201,86,34,0.24)]"
					/>
					<span className="text-sm font-semibold leading-5">{t('brand.managementCenter')}</span>
				</div>
			</SidebarHeader>
			<SidebarContent>
				<SidebarGroup>
					<SidebarGroupContent>
						<SidebarMenu>
							<SidebarMenuItem key={'chat'}>
								<SidebarMenuButton
									isActive={
										location.pathname === '/chat' ||
										location.pathname.startsWith('/chat/')
									}
									onClick={() => navigate('/chat')}
									className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
								>
									<BotMessageSquare />
									<span>{t('common.chat')}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									isActive={location.pathname === '/platform-audit'}
									onClick={() => navigate('/platform-audit')}
									className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
								>
									<MessageSquareText />
									<span>{t('common.platformAudit')}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									isActive={location.pathname === '/memory-management'}
									onClick={() => navigate('/memory-management')}
									className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
								>
									<BookUser />
									<span>{t('common.memoryManagement')}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									isActive={location.pathname === '/platform-settings'}
									onClick={() => navigate('/platform-settings')}
									className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
								>
									<Crown />
									<span>{t('common.platformSettings')}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									isActive={location.pathname === '/memory-settings'}
									onClick={() => navigate('/memory-settings')}
									className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
								>
									<BrainCircuit />
									<span>{t('common.memorySettings')}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									isActive={location.pathname === '/schedule'}
									onClick={() => navigate('/schedule')}
									className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
								>
									<Calendars />
									<span>{t('common.schedule')}</span>
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
									isActive={location.pathname === '/credential'}
									onClick={() => navigate('/credential')}
									className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
								>
									<KeyRound />
									<span>{t('common.credential')}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									isActive={location.pathname === '/engineering-knowledge'}
									onClick={() => navigate('/engineering-knowledge')}
									aria-label={t('common.engineeringKnowledge')}
									className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
								>
									<Database />
									<span>{t('common.engineeringKnowledge')}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
							<SidebarMenuItem>
								<SidebarMenuButton
									isActive={location.pathname === '/knowledge'}
									onClick={() => navigate('/knowledge')}
									className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
								>
									<LibraryBig />
									<span>{t('common.knowledge')}</span>
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
							onClick={handleToggleLanguage}
							className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
						>
							<Languages />
									<span>{i18n.language.startsWith('zh') ? t('common.switchToEn') : t('common.switchToZh')}</span>
						</SidebarMenuButton>
					</SidebarMenuItem>
					<SidebarMenuItem>
						<SidebarMenuButton
							onClick={handleStartTour}
							className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
						>
							<Compass />
									<span>{t('tour.trigger')}</span>
						</SidebarMenuButton>
					</SidebarMenuItem>
					<SidebarMenuItem>
						<SidebarMenuButton
							onClick={handleLogout}
							className="h-auto min-h-10 px-3 py-2 text-sm [&>span:last-child]:whitespace-normal [&>span:last-child]:overflow-visible"
						>
							<LogOut />
									<span>{t('common.logout')}</span>
						</SidebarMenuButton>
					</SidebarMenuItem>
				</SidebarMenu>
			</SidebarFooter>
		</Sidebar>
	);
}
