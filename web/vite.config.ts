import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En développement, /api est relayé vers le serveur FastAPI (port 8000).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
});
