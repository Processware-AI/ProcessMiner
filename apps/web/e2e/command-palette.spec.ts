import { expect, test } from "@playwright/test";

import { login } from "./helpers";

// 데모 회사(python -m app.cli demo)를 읽기만 한다.
test("검색 팔레트로 문서와 화면을 찾아 이동한다", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await login(page, "qmr@example.com");
  await page.getByRole("link", { name: /데모 주식회사/ }).click();
  await expect(page.getByRole("heading", { name: "받은 일" })).toBeVisible();

  // 단축키로 열고, 화면 이름으로 찾아 이동한다.
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog");
  const input = palette.getByPlaceholder("문서 번호·제목 또는 화면 이름");
  await expect(input).toBeVisible();
  await input.fill("구성원");
  await expect(palette.getByRole("option")).toHaveCount(1);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/demo\/members$/);
  await expect(palette).toBeHidden();

  // 옆 메뉴의 검색 버튼으로도 열리고, 문서를 제목으로 찾는다.
  await page.getByRole("button", { name: /검색 또는 이동/ }).click();
  await input.fill("문서화된 정보 관리 정책");
  await palette.getByRole("option", { name: /문서화된 정보 관리 정책/ }).first().click();
  await expect(page.getByRole("navigation", { name: "위치" })).toBeVisible();

  expect(errors).toEqual([]);
});
