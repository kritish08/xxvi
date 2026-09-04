/// <reference types="vitest/config" />
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// AUTHORING-ONLY SECOND ENTRY. `audio-preview.html` is a bench for judging
// the music bed and the sound effects without playing an eight-segment run
// to reach them. It is a separate Rollup entry, so none of it is reachable
// from the app's own bundle, and it renders no run content of any kind --
// only bed-state names and effect names, which give away nothing.
//
// It ships in the production build deliberately: the stack he plays on is
// the Docker/Caddy one, so a dev-server-only page could not be heard where
// it actually matters. DELETE THIS ENTRY AND THE HTML FILE BEFORE THE 20TH
// -- it is a tool for building the thing, not part of the thing.
const AUTHORING_PAGES = {
  main: resolve(import.meta.dirname, "index.html"),
  "audio-preview": resolve(import.meta.dirname, "audio-preview.html"),
};

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { input: AUTHORING_PAGES } },
  server: {
    proxy: {
      // Dev-only: puts the SPA and the API on one origin so the session
      // cookie (SameSite=Lax) works without CORS. In production this same
      // job is done by Caddy (see ../Caddyfile) reverse-proxying /api/* to
      // the api service.
      "/api": { target: "http://localhost:8000", changeOrigin: true, ws: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // Vitest's default is 5000ms, which is not a margin for this suite --
    // several games run on REAL timers because they animate, and the tests
    // drive them at real speed on purpose. SimonSays alone spends
    // STEP_MS * (length + 1) just showing the sequence: ~1.84s before
    // "your turn" appears for a length-3 run, before a single key is
    // pressed. Individual `waitFor` calls are themselves allowed 5000ms,
    // so one of them could consume the entire default budget on its own.
    //
    // That is exactly what happened: green locally, red in CI with
    // "Test timed out in 5000ms" on a runner executing 33 test files at
    // once. The tests were never wrong -- the budget was.
    testTimeout: 20000,
    hookTimeout: 20000,
  },
});
