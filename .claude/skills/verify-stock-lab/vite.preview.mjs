// vite preview for verify-stock-lab: serves .local/verify/dist on 127.0.0.1:4227 and
// forwards /api to the API on 127.0.0.1:8227. No imports from node_modules, so vite
// loads it from outside frontend/. Ports are fixed in SKILL.md.
import { fileURLToPath } from 'node:url'

export default {
  root: fileURLToPath(new URL('../../../frontend', import.meta.url)),
  build: { outDir: fileURLToPath(new URL('../../../.local/verify/dist', import.meta.url)) },
  preview: {
    host: '127.0.0.1',
    port: 4227,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8227' },
  },
}
