import {defineConfig} from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
    plugins: [vue()],
    server: {
        proxy: {
            "/api": {
                target: process.env.QA_API_TARGET || "http://127.0.0.1:8000",
                changeOrigin: true,
                configure: (proxy) => {
                    proxy.on("proxyReq", (proxyReq) => {
                        proxyReq.setHeader("Cache-Control", "no-cache");
                        proxyReq.setHeader("Connection", "keep-alive");
                    });
                },
            },
        },
    },
});
