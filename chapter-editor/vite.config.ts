import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// Builds one ES module + one stylesheet with fixed names into Django's static dir.
// nt_chapter.html loads them with ?v=<file mtime> for cache busting.
// (An app build rather than lib mode: lib mode leaves ES output unminified.)
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, '../static/chapter-editor'),
    emptyOutDir: true,
    cssCodeSplit: false,
    modulePreload: false,
    rollupOptions: {
      input: resolve(__dirname, 'src/main.tsx'),
      output: {
        entryFileNames: 'chapter-editor.js',
        assetFileNames: 'chapter-editor[extname]',
      },
    },
  },
})
