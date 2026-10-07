import { expect, type Page, test } from "@playwright/test";

import { createConsultant, login, logout, purgeTenant, unique } from "./helpers";

const shot = (name: string) => ({ path: `e2e/screenshots/drafts-${name}.png` });

const created: string[] = [];
test.afterEach(() => {
  for (const slug of created.splice(0)) purgeTenant(slug);
});

/** 화면을 거치지 않고 API 로 초안을 만든다(로그인한 브라우저의 쿠키를 쓴다). */
async function draft(page: Page, tenant: string, body: Record<string, unknown>, text: string) {
  const response = await page.request.post(`/api/t/${tenant}/systems/ims/documents`, { data: body });
  expect(response.status()).toBe(201);
  const detail = await response.json();
  const sections = detail.open.sections.map((section: { key: string }, index: number) => ({
    ...section,
    body_md: index === 0 ? text : "내용",
  }));
  const saved = await page.request.patch(`/api/t/${tenant}/revisions/${detail.open.id}`, {
    data: { sections },
  });
  expect(saved.status()).toBe(200);
  return detail.document.id as string;
}

// 표준에서 생성한 초안을 기준으로 만드는 과정: 정할 항목을 채우고, 한 번에 검토 요청하고, 한 번에 승인한다.
test("초안의 정할 항목을 채우고 여러 건을 한 번에 검토 요청·승인한다", async ({ page }) => {
  const tag = unique();
  const consultant = `consultant-${tag}@e2e.example`;
  const qmr = `qmr-${tag}@e2e.example`;
  const tenant = `e2e-${tag}`;
  created.push(tenant);
  createConsultant(consultant, "김컨설턴트");

  await login(page, consultant);
  const api = (path: string, data: unknown) => page.request.post(`/api${path}`, { data });
  expect((await api("/tenants", { slug: tenant, name: "초안 주식회사" })).status()).toBe(201);
  const orgUnits = await (await page.request.get(`/api/t/${tenant}/org-units`)).json();
  await api(`/t/${tenant}/systems`, { slug: "ims", name: "통합경영체계", org_unit_id: orgUnits[0].id });
  await api(`/t/${tenant}/members`, { email: qmr, name: "박품질", roles: [{ role: "qmr" }] });

  const open = "이 정책은 〔조직 결정: 검토 주기〕마다 검토한다.";
  const policy = await draft(page, tenant, { doc_type: "POL", title: "문서 관리 정책", scope_code: "QMS" }, open);
  await draft(page, tenant, { doc_type: "PRO", title: "문서 관리 절차", parent_id: policy }, open);

  // ── 정할 항목이 남아 있으면 검토를 요청할 수 없다 ──
  await page.goto(`/${tenant}/s/ims`);
  await expect(page.getByText("2건에 조직이 정할 항목이 2곳 남아 있습니다")).toBeVisible();
  await expect(page.getByRole("button", { name: /검토 요청/ })).toHaveCount(0);
  await page.screenshot(shot("01-library"));

  // ── 같은 이름의 항목을 한 번에 채운다 ──
  await page.getByRole("button", { name: "정할 항목 채우기" }).click();
  await expect(page.getByRole("heading", { name: "조직이 정할 항목" })).toBeVisible();
  await expect(page.getByText("남은 항목 2곳 · 문서 2건")).toBeVisible();
  await page.screenshot(shot("02-decisions"));
  await page.getByLabel("모든 곳에 같은 내용으로").fill("연 1회");
  await page.getByRole("button", { name: "2곳 모두 채우기" }).click();
  await expect(page.getByText("정할 항목이 남아 있지 않습니다")).toBeVisible();

  // ── 한 번에 검토 요청 ──
  await page.getByRole("button", { name: "문서 목록으로" }).click();
  await page.getByRole("button", { name: "2건 검토 요청" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "2건 검토 요청" }).click();
  await expect(dialog.getByText("2건 검토 요청 완료")).toBeVisible();
  await dialog.getByRole("button", { name: "닫기" }).first().click();
  await expect(page.getByText("검토 중v1.0")).toHaveCount(2);

  // ── 검토자가 골라서 한 번에 승인 ──
  await logout(page);
  await login(page, qmr);
  await page.getByRole("link", { name: /초안 주식회사/ }).click();
  await expect(page.getByRole("heading", { name: "검토 요청" })).toBeVisible();
  await expect(page.getByRole("button", { name: "선택한 문서 승인" })).toBeDisabled();
  await page.getByLabel("모두 선택").check();
  await page.screenshot(shot("03-inbox"));
  await page.getByRole("button", { name: "선택한 2건 승인" }).click();
  await dialog.getByLabel("검토 의견").fill("일괄 검토");
  await dialog.getByRole("button", { name: "2건 승인" }).click();
  await expect(dialog.getByText("2건 승인 완료")).toBeVisible();
  await dialog.getByRole("button", { name: "닫기" }).first().click();
  await expect(page.getByText("처리할 일이 없습니다")).toBeVisible();

  // 채운 내용이 승인된 본문에 들어가 있다.
  await page.goto(`/${tenant}/s/ims/docs/${policy}`);
  await expect(page.getByText("이 정책은 연 1회마다 검토한다.")).toBeVisible();
  await expect(page.getByText("승인v1.0").first()).toBeVisible();
});

// 검토 요청 단계를 건너뛰고 초안을 바로 승인한다. 작성자·검토자 분리를 끈 회사에서 작성자가 직접 한다.
test("검토 없이 초안을 한 번에 승인한다", async ({ page }) => {
  const tag = unique();
  const consultant = `consultant-${tag}@e2e.example`;
  const tenant = `e2e-${tag}`;
  created.push(tenant);
  createConsultant(consultant, "김컨설턴트");

  await login(page, consultant);
  const api = (path: string, data: unknown) => page.request.post(`/api${path}`, { data });
  expect((await api("/tenants", { slug: tenant, name: "승인 주식회사" })).status()).toBe(201);
  const orgUnits = await (await page.request.get(`/api/t/${tenant}/org-units`)).json();
  await api(`/t/${tenant}/systems`, { slug: "ims", name: "통합경영체계", org_unit_id: orgUnits[0].id });
  const policy = await draft(page, tenant, { doc_type: "POL", title: "문서 관리 정책", scope_code: "QMS" }, "내용");
  await draft(page, tenant, { doc_type: "PRO", title: "문서 관리 절차", parent_id: policy }, "내용");

  // 작성자 본인이므로 분리 규칙이 켜져 있으면 승인되지 않는다.
  await page.goto(`/${tenant}/s/ims`);
  await page.getByRole("button", { name: "검토 없이 2건 승인" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "2건 승인" }).click();
  await expect(dialog.getByText("0건 승인 완료, 2건은 하지 못했습니다")).toBeVisible();
  await expect(dialog.getByText("작성자는 자기 개정판을 검토할 수 없습니다.").first()).toBeVisible();
  await dialog.getByRole("button", { name: "닫기" }).first().click();

  await page.request.patch(`/api/t/${tenant}`, { data: { four_eyes: false } });
  await page.reload();
  await page.getByRole("button", { name: "검토 없이 2건 승인" }).click();
  await dialog.getByLabel("검토 의견").fill("초기 기준선 일괄 승인");
  await page.screenshot(shot("04-fast-approve"));
  await dialog.getByRole("button", { name: "2건 승인" }).click();
  await expect(dialog.getByText("2건 승인 완료")).toBeVisible();
  await dialog.getByRole("button", { name: "닫기" }).first().click();
  await expect(page.getByText("승인v1.0")).toHaveCount(2);
});
