import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { apiFixtures } from './fixtures/plugin.js'

// `npm run dev:fixtures` sets this. It replaces the backend proxy with the
// recorded responses in fixtures/api, so the UI runs anywhere -- the real
// backend needs the producer data and the gateway, which only exist on the
// deployment box. See fixtures/README.md.
const useFixtures = process.env.API_FIXTURES === '1'

// base './' keeps asset URLs relative so the app works both at
// http://127.0.0.1:8010/ and behind nginx at /signal-dashboard/.
export default defineConfig({
  base: './',
  plugins: [
    react(),
    ...(useFixtures ? [apiFixtures({ delayMs: Number(process.env.API_FIXTURES_DELAY_MS || 0) })] : []),
  ],
  server: {
    proxy: useFixtures ? undefined : { '/api': 'http://127.0.0.1:8010' },
  },
})
