import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      reportsDirectory: './coverage',
      thresholds: {
        lines: 60,
        functions: 60,
        branches: 60,
        statements: 60,
      },
      exclude: [
        'src/types/**',
        'src/App.tsx',
        '**/*.d.ts',
        '**/*.stories.{ts,tsx}',
        '**/*.test.{ts,tsx}',
        '**/*.spec.{ts,tsx}',
      ],
    },
  },
});
