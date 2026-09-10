import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          // VITE_API_TARGET 可在 .env.development 中配置
          // 本地后端: http://localhost:8990
          // Apifox Mock: http://127.0.0.1:4523/mock/xxx
          target: env.VITE_API_TARGET || 'http://localhost:8990',
          changeOrigin: true,
        },
      },
    },
  };
});