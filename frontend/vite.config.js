import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the backend (run `npm run dev` locally). In the container
// the same paths are reverse-proxied by nginx (see frontend/nginx.conf), so the app always
// talks to a same-origin `/admin` and `/enroll`.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/admin": "http://localhost:8010",
      "/enroll": "http://localhost:8010",
      "/health": "http://localhost:8010",
    },
  },
});
