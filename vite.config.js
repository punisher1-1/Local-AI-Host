import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import renderer from 'vite-plugin-electron-renderer'

// https://vite.dev/config/
//
// During `npm run dev`, the Vite dev server proxies the API paths to a running
// backend so the browser can use the SAME same-origin relative URLs it uses in
// the nginx web deployment. Point it at your backend with VITE_API_TARGET
// (defaults to a local serve.py on :8088).
const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8088'

export default defineConfig({
  server: {
    proxy: {
      '/v1': { target: API_TARGET, changeOrigin: true },
      '/search': { target: API_TARGET, changeOrigin: true },
      '/health': { target: API_TARGET, changeOrigin: true },
    },
  },
  plugins: [
    react(),
    electron([
      {
        entry: 'electron/main.js',
      },
      {
        entry: 'electron/preload.mjs',
        onstart(options) {
          options.reload()
        },
      },
    ]),
    renderer(),
  ],
})
