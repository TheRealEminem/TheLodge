// The web app lives in core/web; modules' web code is pulled in from modules/*/web (see core/web/registry.ts), and
// the app's own look from identity/ (@identity: tokens, artwork, copy; identity/public: the favicon).
// Development: `npm run dev` serves it on :5173 and passes /api to the server on the port in app.json.
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import identity from "./app.json";

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  root: here("./core/web"),
  plugins: [react()],
  publicDir: here("./identity/public"),
  resolve: { alias: { "@core": here("./core/web"), "@identity": here("./identity") } },
  build: { outDir: here("./dist"), emptyOutDir: true },
  server: {
    port: 5173,
    fs: { allow: [here(".")] },
    proxy: { "^/api/": { target: process.env.API_URL ?? `http://127.0.0.1:${identity.port}` } },
  },
});
