import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5173,
    // The Rust API runs on :7878; proxy so the browser sees one origin.
    proxy: { '/api': 'http://127.0.0.1:7878' },
  },
})
