import { expect, test } from "@playwright/test";

import { createConsultant, login, purgeTenant, unique } from "./helpers";

const shot = (name: string) => ({ path: `e2e/screenshots/records-${name}.png` });

const created: string[] = [];
test.afterEach(() => {
  for (const slug of created.splice(0)) purgeTenant(slug);
});

const REPORT = [
  "위험통제 검증 결과 보고",
  "작성: 김개발 (2024-03-05)",
  "",
  "대상: 주입펌프 제어 SW v2.3",
  "결과: 합격. 경보 지연 없음.",
].join("\n");

// S4: 기존 산출물을 표준 양식의 기록으로 옮긴다. 회사가 AI 처리에 동의하지 않은 상태(기본값)에서는
// 산출물이 밖으로 나가지 않고, 사람이 양식을 고르고 항목을 채운다.
test("산출물을 올려 양식을 고르고, 항목을 채워 기록으로 발행한다", async ({ page }) => {
  const tag = unique();
  const consultant = `consultant-${tag}@e2e.example`;
  const tenant = `e2e-${tag}`;
  created.push(tenant);
  createConsultant(consultant, "김컨설턴트");

  await login(page, consultant);
  const post = (path: string, data: unknown) => page.request.post(`/api${path}`, { data });
  expect((await post("/tenants", { slug: tenant, name: "기록 주식회사" })).status()).toBe(201);
  const orgUnits = await (await page.request.get(`/api/t/${tenant}/org-units`)).json();
  await post(`/t/${tenant}/systems`, { slug: "ims", name: "통합경영체계", org_unit_id: orgUnits[0].id });
  let parent: string | undefined;
  for (const [docType, title] of [
    ["POL", "품질 방침"],
    ["PRO", "검증 절차"],
    ["WI", "검증 지침"],
    ["TMP", "검증 기록"],
  ]) {
    const response = await post(`/t/${tenant}/systems/ims/documents`, {
      doc_type: docType,
      title,
      ...(parent ? { parent_id: parent } : { scope_code: "QMS" }),
    });
    expect(response.status()).toBe(201);
    parent = (await response.json()).document.id;
  }

  // ── 산출물을 올린다 ──
  await page.goto(`/${tenant}/s/ims`);
  await page.getByRole("button", { name: "기록", exact: true }).click();
  await expect(page.getByText("산출물의 AI 처리가 꺼져 있어")).toBeVisible();
  await page.getByLabel("산출물 파일").setInputFiles({
    name: "검증결과보고.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(REPORT, "utf8"),
  });
  await expect(page.getByText("양식 선택 필요")).toBeVisible();
  await page.screenshot(shot("01-list"));

  // ── 원본을 보며 양식을 고른다 ──
  await page.getByRole("link", { name: /검증결과보고/ }).click();
  await expect(page.getByText("결과: 합격. 경보 지연 없음.")).toBeVisible();
  await page.getByLabel("기록 양식").selectOption({ label: "검증 기록 · 검증 지침 (TMP-QMS-01-01-01-01)" });
  await expect(page.getByText("아직 승인되지 않은 양식입니다")).toBeVisible();
  await page.getByRole("button", { name: "이 양식으로 정하기" }).click();

  // ── 항목을 채운다. 사람이 채운 값은 따로 표시된다 ──
  await expect(page.getByText("비어 있음")).toHaveCount(5);
  await expect(page.getByRole("button", { name: "기록으로 발행" })).toBeDisabled();
  await page.getByRole("textbox", { name: "작성자", exact: true }).fill("김개발");
  await page.getByRole("textbox", { name: "내용", exact: true }).fill("합격. 경보 지연 없음.");
  await page.getByLabel("기록 제목").fill("주입펌프 제어 SW 위험통제 검증 결과");
  await page.getByLabel("수행한 날").fill("2024-03-05");
  await page.getByLabel("수행한 날").blur();
  await expect(page.getByText("사람 입력")).toHaveCount(2);
  await expect(page.getByText("김컨설턴트 입력").first()).toBeVisible();
  await page.screenshot(shot("02-review"));

  // ── 발행하면 번호가 발급되고 바뀌지 않는다 ──
  await page.getByRole("button", { name: "기록으로 발행" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("빈 항목 3개는 빈 채로 남습니다")).toBeVisible();
  await dialog.getByRole("button", { name: "발행", exact: true }).click();
  await expect(page.getByText("발행한 기록은 바뀌지 않습니다")).toBeVisible();
  await expect(page.getByText("REC-QMS-01-01-01-01-001").first()).toBeVisible();
  await expect(page.getByRole("textbox", { name: "작성자", exact: true })).toHaveCount(0);

  await page.getByRole("link", { name: "기록", exact: true }).click();
  await expect(page.getByText("정리할 산출물이 없습니다")).toBeVisible();
  await expect(page.getByRole("link", { name: /주입펌프 제어 SW 위험통제 검증 결과/ })).toBeVisible();
  await expect(page.getByText("수행 2024. 3. 5.")).toBeVisible();
});
