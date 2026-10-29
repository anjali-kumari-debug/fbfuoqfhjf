import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // During development, forward /api calls to the FastAPI server.
    // In production FastAPI serves both the built app and /api, so no proxy is needed.
    // Set API_PORT if port 8000 is already used on your machine.
    proxy: {
      '/api': `http://127.0.0.1:${process.env.API_PORT ?? 8000}`,
    },
  },
})
