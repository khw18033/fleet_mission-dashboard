import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:30005'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': API_TARGET,
      '/health': API_TARGET,
      '/broadcast-mission': API_TARGET,
      '/mission-results': API_TARGET,
      '/ws/dashboard': {
        target: API_TARGET,
        ws: true,
      },
      '/ws/mqtt': {
        target: API_TARGET,
        ws: true,
      },
    },
  },
  build: { outDir: 'dist' },
})
