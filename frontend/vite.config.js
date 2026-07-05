import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' keeps asset URLs relative so the app works both at
// http://127.0.0.1:8010/ and behind nginx at /signal-dashboard/.
export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8010' },
  },
})
