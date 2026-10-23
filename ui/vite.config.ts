/// <reference types="vitest/config" />
// Configuration de Vite (compilation de l'interface) et de Vitest (tests de l'interface).
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Chemins relatifs dans index.html : l'interface compilée peut être servie
  // depuis n'importe quel dossier (pywebview, application installée).
  base: './',
  server: {
    // Même port que DEV_SERVER_URL dans src/recomuse/app.py.
    port: 5173,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})
