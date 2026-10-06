import { expect, test } from "@playwright/test";

import { createConsultant, login, logout, purgeTenant, unique } from "./helpers";

const shot = (name: string) => ({ path: `e2e/screenshots/lifecycle-${name}.png` });

const created: string[] = [];
test.afterEach(() => {
  for (const slug of created.splice(0)) purgeTenant(slug);
});

test("회사를 보관하고, 복원하고, 보관한 뒤 완전히 삭제한다", async ({ page }) => {
  const tag = unique();
  const consultant = `consultant-${tag}@e2e.example`;
  const tenant = `e2e-${tag}`;
  const name = `정리 대상 ${tag}`;
  created.push(tenant);
  createConsultant(consultant, "김컨설턴트");

  await login(page, consultant);
  await page.getByRole("button", { name: "새 회사" }).click();
  await page.getByLabel("회사 이름").fill(name);
  await page.getByLabel("주소").fill(tenant);
  await page.getByRole("button", { name: "만들기" }).click();
  await expect(page.getByRole("heading", { name: "조직·체계" })).toBeVisible();
  await expect(page.getByRole("button", { name: "새 체계" })).toBeVisible();

  // ── 보관 ──
  await page.getByRole("link", { name: "설정" }).click();
  await page.getByRole("button", { name: "회사 보관" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "보관", exact: true }).click();
  await expect(page.getByText("보관된 회사입니다. 읽기만 가능합니다.")).toBeVisible();
  // 회사 관리자는 복원할 수 있지만 완전 삭제는 할 수 없다.
  await expect(page.getByRole("button", { name: "회사 복원" })).toBeVisible();
  await expect(page.getByText("완전 삭제는 플랫폼 관리자만 할 수 있습니다.")).toBeVisible();
  await page.screenshot(shot("01-archived"));

  // 보관된 회사에서는 만들거나 고치는 버튼이 사라진다.
  await page.getByRole("link", { name: "조직·체계" }).click();
  await expect(page.getByRole("heading", { name: "조직·체계" })).toBeVisible();
  await expect(page.getByRole("button", { name: "새 체계" })).toHaveCount(0);

  // ── 복원 ──
  await page.getByRole("link", { name: "복원 또는 삭제" }).click();
  await page.getByRole("button", { name: "회사 복원" }).click();
  await expect(page.getByText("보관된 회사입니다. 읽기만 가능합니다.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "회사 보관" })).toBeVisible();

  // ── 다시 보관하고 플랫폼 관리자가 삭제 ──
  await page.getByRole("button", { name: "회사 보관" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "보관", exact: true }).click();
  await expect(page.getByRole("button", { name: "회사 복원" })).toBeVisible();

  await logout(page);
  await login(page, "admin@example.com");
  const row = page.getByRole("link", { name: new RegExp(name) });
  await expect(row).toContainText("보관됨");
  await row.click();
  await page.getByRole("link", { name: "복원 또는 삭제" }).click();
  await page.getByRole("button", { name: "완전 삭제" }).click();

  const dialog = page.getByRole("dialog");
  const confirm = dialog.getByRole("button", { name: "완전 삭제" });
  await expect(confirm).toBeDisabled(); // 주소를 입력하기 전에는 누를 수 없다
  await dialog.getByLabel("회사 주소").fill("wrong");
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("회사 주소").fill(tenant);
  await page.screenshot(shot("02-confirm"));
  await confirm.click();

  await expect(page.getByRole("heading", { name: "회사" })).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(name) })).toHaveCount(0);
  // 지운 회사의 주소로 들어가도 찾을 수 없다.
  await page.goto(`/${tenant}`);
  await expect(page.getByText("회사를 찾을 수 없습니다.")).toBeVisible();
});
