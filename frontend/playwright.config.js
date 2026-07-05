import { defineConfig } from '@playwright/test'

const frontendPort = Number(process.env.E2E_FRONTEND_PORT || 5173)
const backendPort = Number(process.env.E2E_BACKEND_PORT || 8000)

// E2E: real backend (8000) + vite dev (5173, /api proxy). Specs build their own
// throwaway vault fixtures under /tmp; nothing touches a real notes vault.
export default defineConfig({
  testDir: './tests/ui',
  timeout: 30_000,
  fullyParallel: true,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    viewport: { width: 1280, height: 900 },
    // Capture objective behavioral evidence on failure (acting-evaluator: the
    // screenshot/trace IS the evidence a human reviews, instead of re-running by hand).
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `VIDEO_INTAKE_FASTAPI_PORT=${backendPort} bash ../backend/run_e2e_backend.sh`,
      url: `http://127.0.0.1:${backendPort}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `VITE_DEV_PORT=${frontendPort} VITE_BACKEND_PORT=${backendPort} npm run dev`,
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
