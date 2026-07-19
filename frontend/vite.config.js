import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const devPort = Number(process.env.VITE_DEV_PORT || 5173)
// Tauri dev starts the source-backed sidecar on 8766. Playwright overrides this
// explicitly to 8000 because it owns a hermetic uvicorn process there.
const backendPort = Number(process.env.VITE_BACKEND_PORT || 8766)

export default defineConfig({
  plugins: [react()],
  server: {
    // 127.0.0.1 only: the /api proxy would otherwise expose every backend
    // endpoint (note writes, key clearing, paid calls) to the whole LAN.
    host: '127.0.0.1',
    port: devPort,
    strictPort: true,
    proxy: {
      // ws:true 讓即時擷取 Half-2 的 WS（/api/app/realtime-asr）在 dev 也能升級
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
