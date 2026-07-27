import path from 'path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import svgr from 'vite-plugin-svgr';

const webUiPort = Number(process.env.AGENTSCOPE_WEBUI_PORT || 25173);
const helperPort = Number(process.env.AGENTSCOPE_WEBUI_HELPER_PORT || 23000);

export default defineConfig({
	plugins: [react(), tailwindcss(), svgr()],
	server: {
		host: '127.0.0.1',
		port: webUiPort,
		strictPort: true,
		proxy: {
			'/api': `http://127.0.0.1:${helperPort}`,
		},
	},
	resolve: {
		alias: {
			'@': path.resolve(__dirname, './src'),
			'next/navigation': path.resolve(__dirname, './src/lib/next-navigation-shim.ts'),
		},
	},
	optimizeDeps: {
		include: ['mime-types'],
	},
});
