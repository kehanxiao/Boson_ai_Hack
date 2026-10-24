import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const repoRoot = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig({
  plugins: [react()],
  // Read VITE_* vars from the repo-root .env (only VITE_-prefixed vars reach the browser).
  envDir: repoRoot,
  // The dev-only fake agent imports fixtures from ../demo.
  server: { port: 5173, fs: { allow: [repoRoot] } },
})
