import {
	Bot,
	BrainCircuit,
	BookUser,
	Compass,
	Database,
	KeyRound,
	Languages,
	LayoutGrid,
	LogOut,
	MessageSquareText,
	ShieldCheck,
	Wrench,
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
	const { pathname } = useLocation();
	const { t } = useTranslation();
	const { startOnborda } = useOnborda();
	const zh = i18n.language.startsWith('zh');
	const groups = [
		[
			{
				path: '/platform-agents',
				label: zh ? '平台主智能体' : 'Platform agents',
				icon: LayoutGrid,
			},
			{ path: '/business-tools', label: zh ? '业务智能体' : 'Business agents', icon: Bot },
			{ path: '/permission-review', label: t('credential.permissionReviewer.title'), icon: ShieldCheck },
			{ path: '/memory-settings', label: t('common.memorySettings'), icon: BrainCircuit },
		],
		[
			{ path: '/system-tools', label: zh ? '系统工具' : 'System tools', icon: Wrench },
			{
				path: '/credential',
				label: zh ? '模型与连接' : 'Models & connections',
				icon: KeyRound,
			},
			{
				path: '/engineering-knowledge',
				label: zh ? '外部知识库' : 'External knowledge',
				icon: Database,
			},
			{ path: '/memory-management', label: t('common.memoryManagement'), icon: BookUser },
			{ path: '/platform-audit', label: t('common.platformAudit'), icon: MessageSquareText },
		],
	];
	return (
		<Sidebar collapsible="none" className="!w-44 shrink-0 border-r md:!w-52">
			<SidebarHeader>
				<div className="flex min-h-20 items-center gap-3 px-3 py-4">
					<img src="/dobby.svg" alt="Dobby" className="size-9 shrink-0 rounded-xl" />
					<span className="text-sm font-semibold leading-5">
						{t('brand.managementCenter')}
					</span>
				</div>
			</SidebarHeader>
			<SidebarContent>
				{groups.map((items, index) => (
					<SidebarGroup key={index} className={index ? 'mt-4 border-t pt-5' : ''}>
						<SidebarGroupContent>
							<SidebarMenu>
								{items.map(({ path, label, icon: Icon }) => (
									<SidebarMenuItem key={path}>
										<SidebarMenuButton
											isActive={
												pathname === path || pathname.startsWith(`${path}/`)
											}
											onClick={() => navigate(path)}
											className="h-auto min-h-11 gap-3 px-3 py-3 text-sm data-[active=true]:bg-[#c95622]/8 data-[active=true]:text-[#c95622] [&>span:last-child]:whitespace-normal"
										>
											<Icon />
											<span>{label}</span>
										</SidebarMenuButton>
									</SidebarMenuItem>
								))}
							</SidebarMenu>
						</SidebarGroupContent>
					</SidebarGroup>
				))}
			</SidebarContent>
			<SidebarFooter>
				<SidebarMenu>
					<SidebarMenuItem>
						<SidebarMenuButton
							onClick={() => i18n.changeLanguage(zh ? 'en' : 'zh')}
							className="min-h-10 px-3 text-sm"
						>
							<Languages />
							<span>{zh ? t('common.switchToEn') : t('common.switchToZh')}</span>
						</SidebarMenuButton>
					</SidebarMenuItem>
					{pathname.startsWith('/chat/') && (
						<SidebarMenuItem>
							<SidebarMenuButton
								onClick={() => startOnborda(CHAT_TOUR_NAME)}
								className="min-h-10 px-3 text-sm"
							>
								<Compass />
								<span>{t('tour.trigger')}</span>
							</SidebarMenuButton>
						</SidebarMenuItem>
					)}
					<SidebarMenuItem>
						<SidebarMenuButton
							onClick={() => {
								clearAuthSession();
								navigate('/setup', { replace: true });
							}}
							className="min-h-10 px-3 text-sm"
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
