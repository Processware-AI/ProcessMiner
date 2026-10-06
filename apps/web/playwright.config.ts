import { defineConfig, devices } from "@playwright/test";

// 실행 전에 API(58000)와 웹(3000)이 떠 있어야 하고, API 는 PM_AUTH_DEV_ECHO=true 여야 한다.
// 사용자 준비는 e2e/helpers.ts 가 API 의 CLI 로 한다.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.WEB_BASE_URL ?? "http://localhost:3000",
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1360, height: 900 } },
      testIgnore: /mobile.spec.ts/,
    },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
});
