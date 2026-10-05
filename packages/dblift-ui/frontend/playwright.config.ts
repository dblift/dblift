import { defineConfig } from "@playwright/test";

// This file runs in Node; the project's types are the browser's, so declare the one Node global used here.
declare const process: { env: Record<string, string | undefined> };

const PORT = 8799;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  webServer: {
    // Needs a Python environment with dblift-ui installed and a built interface.
    command: `${process.env.PYTHON ?? "python"} e2e/serve.py ${PORT}`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 30_000,
    // Stop the server with a signal it handles, so it removes its seeded projects (see e2e/serve.py).
    gracefulShutdown: { signal: "SIGINT", timeout: 5_000 },
  },
});
