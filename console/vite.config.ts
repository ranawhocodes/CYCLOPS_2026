import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const CONSOLE_PORT = Number(process.env.CYCLOPS_CONSOLE_PORT ?? 5180);
const API_PORT = Number(process.env.CYCLOPS_API_PORT ?? 8000);

export default defineConfig({
  plugins: [react()],
  server: {
    // Not 5173. That is Vite's default, so any other Vite project running on the
    // same laptop takes it first and silently shadows this one — which is a
    // spectacular way to demo somebody else's app to a judge.
    port: CONSOLE_PORT,
    strictPort: true,      // fail loudly instead of quietly picking another port
    host: "127.0.0.1",
    // Proxy so the console makes same-origin requests. No CORS surprises, and
    // the API host is configured in exactly one place.
    proxy: {
      "/v1": { target: `http://127.0.0.1:${API_PORT}`, changeOrigin: true, ws: true },
    },
  },
});
