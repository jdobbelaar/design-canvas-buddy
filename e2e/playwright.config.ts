/**
 * End-to-end tests: real browsers against the real docker-compose.yaml stack
 * (FastAPI serving the built frontend, plus Postgres). Nothing is mocked.
 *
 *   make test-e2e                      # from the repo root
 *   cd e2e && npm test                 # chromium only
 *   cd e2e && npm run test:all-browsers
 *
 * First time: `cd e2e && npm install && npm run install:browsers`.
 *
 * By default global-setup.ts starts its own throwaway stack (unique compose
 * project name, random free port, removed afterwards) so it can't collide with a
 * stack you run yourself. To test one that is already running instead:
 *
 *   E2E_BASE_URL=http://localhost:8000 npx playwright test --project=chromium
 */
import { randomBytes } from 'node:crypto';
import net from 'node:net';
import { defineConfig, devices } from '@playwright/test';

const freePort = () =>
  new Promise<number>((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as net.AddressInfo;
      server.close(() => resolve(port));
    });
  });

// Decided once, here, and shared with global-setup.ts through the environment
// (workers inherit it, and `??=` keeps a re-evaluated config consistent).
const external = process.env.E2E_BASE_URL;
if (!external) {
  process.env.E2E_PORT ??= String(await freePort());
  process.env.E2E_PROJECT ??= `dcb-e2e-${randomBytes(4).toString('hex')}`;
}
// 127.0.0.1, not "localhost": Docker publishes on IPv4 and IPv6, and on some
// machines another process answers on ::1.
const baseURL = external ?? `http://127.0.0.1:${process.env.E2E_PORT}`;

export default defineConfig({
  testDir: './tests',
  globalSetup: './global-setup.ts',
  // Tests share one stack but each creates its own session; a single worker
  // keeps runs deterministic and the Postgres container unstressed.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
