import { defineConfig } from 'vite';

export default defineConfig({
  base: '/digital-twin/',
  build: {
    outDir: '../viewer/digital-twin-dist',
    emptyOutDir: true,
    sourcemap: true,
  },
});
