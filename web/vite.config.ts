import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  base: "/static/panel/",
  build: {
    outDir: "../static/panel",
    emptyOutDir: true,
    manifest: "manifest.json",
    rollupOptions: { input: "src/main.ts" },
    target: "es2022",
  },
});
