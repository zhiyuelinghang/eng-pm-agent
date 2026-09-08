import { Outlet } from 'react-router-dom';

import { AppSidebar } from '@/components/layout/AppSidebar';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';

export function AppLayout() {
	return (
		<div className="h-screen flex">
			<SidebarProvider>
				<AppSidebar />
				<SidebarInset className="min-w-0 flex-1 overflow-hidden">
					<Outlet />
				</SidebarInset>
			</SidebarProvider>
		</div>
	);
}
