import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dedicated dev ports so this project never collides with other local apps
// on the common defaults (5173 / 8000). strictPort: fail loudly if taken.
const API_PORT = process.env.API_PORT ?? 8001

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5180,
    strictPort: true,
    // During development, forward /api calls to the FastAPI server.
    // In production FastAPI serves both the built app and /api, so no proxy is needed.
    proxy: {
      '/api': `http://127.0.0.1:${API_PORT}`,
    },
  },
})
