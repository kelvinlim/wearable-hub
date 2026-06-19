import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// App version sourced from package.json so the UI and packaging stay in sync.
const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url)));

// Served under /wearable/ on the lnpitask.umn.edu host (host nginx strips the prefix). Dev
// proxies the API to the backend. See docs/ui-redesign-plan.md.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/wearable/",
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
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
