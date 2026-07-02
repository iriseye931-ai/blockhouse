import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In docker-compose the backend is reachable at http://backend:8000, not
// localhost — the compose file sets BACKEND_URL accordingly.
const backend = process.env.BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: process.env.BACKEND_URL ? '0.0.0.0' : '127.0.0.1',
    port: 3000,
    strictPort: true,
    proxy: {
      '/ws': {
        target: backend.replace(/^http/, 'ws'),
        ws: true,
        changeOrigin: true,
      },
      '/api': {
        target: backend,
        changeOrigin: true,
      }
    }
  }
})
