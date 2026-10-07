interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_SAVED_PRICE_CHIPS_INTEGRATION?: string
  readonly VITE_SAVED_PRICE_CHIPS_FOCUS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
