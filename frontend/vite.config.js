import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Must match backend.app.config.API_PORT
const API_TARGET = 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
})
