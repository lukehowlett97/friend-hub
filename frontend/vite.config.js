import path from 'node:path'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig(({ mode }) => {
  const rootEnv = loadEnv(mode, path.resolve(__dirname, '..'), '')
  const giphyApiKey = rootEnv.VITE_GIPHY_API_KEY || rootEnv.GIPHY_API_KEY || ''

  return {
    define: {
      'import.meta.env.VITE_GIPHY_API_KEY': JSON.stringify(giphyApiKey),
    },

    plugins: [
      react(),

      VitePWA({
        // We own the service worker file so push + notificationclick handlers
        // are loaded identically in dev and prod (the generateSW dev SW skips
        // workbox.importScripts, which silently breaks push delivery).
        strategies: 'injectManifest',
        srcDir: 'src',
        filename: 'sw.js',
        registerType: 'autoUpdate',

        manifest: false,

        devOptions: {
          enabled: true,
          type: 'module',
          navigateFallback: 'index.html',
        },

        injectManifest: {
          globPatterns: ['**/*.{js,css,html,ico,png,svg,webmanifest}'],
        },
      }),
    ],

    server: {
      port: 3000,
      host: '::',  // dual-stack so localhost works in all browsers on WSL2
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
        '/ws': {
          target: 'ws://localhost:8000',
          ws: true,
          changeOrigin: true,
        },
        '/uploads': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    }
  }
})
