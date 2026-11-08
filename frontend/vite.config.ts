import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    fs: { allow: [".", "../shared"] },
    proxy: {
      // Override to point a second dev server at another backend (e.g. API_PROXY=http://localhost:8001).
      "/api": process.env.API_PROXY ?? "http://localhost:8000",
    },
  },
});
