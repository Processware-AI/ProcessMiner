import { expect, test } from "@playwright/test";

import { login, openDocument } from "./helpers";

const shot = (name: string) => ({ path: `e2e/screenshots/mobile-${name}.png` });

// 데모 회사(python -m app.cli demo)를 읽기만 한다.
test("휴대폰 화면에서 받은 일과 문서를 본다", async ({ page }) => {
  await login(page, "qmr@example.com");
  await page.getByRole("link", { name: /데모 주식회사/ }).click();

  // 좁은 화면에서는 옆 메뉴 대신 아래쪽 내비게이션을 쓴다.
  const bottomNav = page.getByRole("navigation").filter({ hasText: "받은 일" }).last();
  await expect(bottomNav).toBeVisible();
  await expect(page.getByRole("heading", { name: "검토 요청" })).toBeVisible();
  await page.screenshot(shot("01-inbox"));

  await bottomNav.getByRole("link", { name: "문서" }).click();
  await expect(page.getByRole("link", { name: /문서화된 정보 관리 정책/ })).toBeVisible();
  await page.screenshot(shot("02-library"));

  await openDocument(page, /개정 및 버전 관리 지침/);
  await expect(page.getByRole("button", { name: "승인", exact: true })).toBeVisible();
  await page.screenshot(shot("03-document"));

  // 가로로 넘치는 요소가 없어야 한다.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);

  await page.getByRole("button", { name: "메뉴" }).last().click();
  await expect(page.getByRole("dialog").getByRole("link", { name: "구성원" })).toBeVisible();
  // 열리는 애니메이션이 끝난 뒤의 모습을 남긴다.
  await page.getByRole("dialog").evaluate((el) =>
    Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)),
  );
  await page.screenshot(shot("04-menu"));
});
