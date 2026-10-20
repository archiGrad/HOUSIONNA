import { defineConfig } from 'vite';

export default defineConfig({
  // Relative, so the same build works under /digital-twin/ locally and from any folder on a web host.
  base: './',
  build: {
    outDir: '../viewer/digital-twin-dist',
    emptyOutDir: true,
    sourcemap: true,
  },
});
