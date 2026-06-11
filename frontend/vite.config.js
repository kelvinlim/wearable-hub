import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served under /wearable/ on the omnikog host (host nginx strips the prefix before the
// frontend container; the SPA references assets + API under BASE_URL = "/wearable/").
// Dev (`npm run dev`) runs at http://localhost:5173/wearable/ with the API proxied below.
export default defineConfig({
  plugins: [react()],
  base: "/wearable/",
  server: {
    proxy: {
      "/wearable/admin": {
        target: "http://localhost:8010",
        rewrite: (p) => p.replace(/^\/wearable/, ""),
      },
      "/wearable/auth": {
        target: "http://localhost:8010",
        rewrite: (p) => p.replace(/^\/wearable/, ""),
      },
      "/enroll": "http://localhost:8010",
      "/health": "http://localhost:8010",
    },
  },
});
