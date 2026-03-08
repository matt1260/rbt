import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    historyApiFallback: true,
  },
  preview: {
    historyApiFallback: true,
  },
  // Use relative asset paths so WordPress can serve from any base URL
  base: './',
  build: {
    // Output into the WordPress theme's react/ folder
    outDir: resolve(__dirname, '../rbt-sanctum/react'),
    emptyOutDir: true,
    // Use stable, predictable filenames (no hash) for WordPress enqueue
    rollupOptions: {
      input: resolve(__dirname, 'index.html'),
      output: {
        entryFileNames: 'sanctum.js',
        chunkFileNames: 'sanctum-[name].js',
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith('.css')) {
            return 'sanctum.css';
          }
          return 'assets/[name][extname]';
        },
      },
    },
  },
})
