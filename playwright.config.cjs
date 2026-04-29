const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.BACKEND_URL || 'http://127.0.0.1:8000',
  },
});
