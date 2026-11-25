import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { mockBackendPlugin } from "./src/dev/mockBackend";

export default defineConfig({
  plugins: [react(), tailwindcss(), mockBackendPlugin()],
  build: {
    outDir: "dist",
    rollupOptions: {
      input: ["index.html", "playground.html", "parent.html"],
    },
  },
  server: {
    host: "127.0.0.1",
  },
});
