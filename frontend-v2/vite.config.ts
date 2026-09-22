import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // The Python gateway exposes /assets/<name> while resolving the file from
  // the WebUI root. Keep built JS/CSS flat and address them through /assets/.
  base: "/assets/",
  build: {
    outDir: "../gateway/webui-v2",
    emptyOutDir: true,
    assetsDir: "",
    sourcemap: false,
    target: "es2022",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/state.json": "http://127.0.0.1:8080",
      "/history.json": "http://127.0.0.1:8080",
    },
  },
});
