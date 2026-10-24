// vite preview for the verify checks (Issue #243): serves a built frontend and forwards /api
// to the API under test. Everything comes from the environment, so CI and a local run pick
// their own ports:
//   VERIFY_DIST      the build's output directory (vite build --outDir)
//   VERIFY_WEB_PORT  port to listen on (127.0.0.1)
//   VERIFY_API_URL   API origin, e.g. http://127.0.0.1:18000
// No imports from node_modules, so vite loads it from outside frontend/.
import { fileURLToPath } from 'node:url'

function required(name) {
  const value = process.env[name]
  if (!value) throw new Error(`vite.preview.mjs: set ${name}`)
  return value
}

export default {
  root: fileURLToPath(new URL('../../frontend', import.meta.url)),
  build: { outDir: required('VERIFY_DIST') },
  preview: {
    host: '127.0.0.1',
    port: Number(required('VERIFY_WEB_PORT')),
    strictPort: true,
    proxy: { '/api': required('VERIFY_API_URL') },
  },
}
