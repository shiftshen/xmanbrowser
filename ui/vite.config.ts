import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// XMan UI. In dev, proxy /api to the local FastAPI control service so the
// browser and the Tauri webview hit the same origin.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 5191,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8723",
    },
  },
  build: { outDir: "dist" },
});
