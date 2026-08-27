import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 38429,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:38430',
      '/health': 'http://127.0.0.1:38430',
    },
  },
})
