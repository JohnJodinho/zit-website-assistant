import { defineConfig } from "vite";

export default defineConfig({
  publicDir: false,
  build: {
    outDir: "public",
    emptyOutDir: false,
    lib: {
      entry: "src/loader/loader.ts",
      formats: ["iife"],
      name: "ZitAssistantLoader",
      fileName: () => "loader.js",
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
});
