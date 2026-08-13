import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Must match backend.app.config.API_PORT
const API_TARGET = 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [vue()],
  server: {
    // Avoid PhotoProcesser / other Vite apps on 5173
    port: 5180,
    strictPort: true,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
})
