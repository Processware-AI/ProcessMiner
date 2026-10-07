import { expect, type Page, test } from "@playwright/test";

import { createConsultant, fillSection, login, logout, purgeTenant, unique } from "./helpers";

const shot = (name: string) => ({ path: `e2e/screenshots/tailoring-${name}.png` });

const created: string[] = [];
test.afterEach(() => {
  for (const slug of created.splice(0)) purgeTenant(slug);
});

/** API 로 문서를 만들고 본문을 채워 검토를 요청한다. 개정판 id 를 돌려준다. */
async function submitted(page: Page, tenant: string, body: Record<string, unknown>) {
  const response = await page.request.post(`/api/t/${tenant}/systems/ims/documents`, { data: body });
  expect(response.status()).toBe(201);
  const detail = await response.json();
  await fillAndSubmit(page, tenant, detail.open, "기준선 내용");
  return { documentId: detail.document.id as string, revisionId: detail.open.id as string };
}

async function fillAndSubmit(
  page: Page,
  tenant: string,
  revision: { id: string; sections: { key: string }[] },
  text: string,
) {
  const sections = revision.sections.map((section) => ({ ...section, body_md: text }));
  const path = `/api/t/${tenant}/revisions/${revision.id}`;
  expect((await page.request.patch(path, { data: { sections } })).status()).toBe(200);
  expect((await page.request.post(`${path}/submit`)).status()).toBe(200);
}

async function approveAll(page: Page, tenant: string, revisionIds: string[]) {
  const response = await page.request.post(`/api/t/${tenant}/review-batch`, {
    data: { action: "approve", revision_ids: revisionIds },
  });
  expect((await response.json()).failed).toBe(0);
}

// S3 완료 기준: 조직 한 곳이 문서 일부만 바꾼 체계를 갖고, 기준선 개정이 반영·표시된다.
test("하위 체계에서 문서를 재정의·제외하고, 기준선 개정을 확인한다", async ({ page }) => {
  const tag = unique();
  const consultant = `consultant-${tag}@e2e.example`;
  const qmr = `qmr-${tag}@e2e.example`;
  const tenant = `e2e-${tag}`;
  created.push(tenant);
  createConsultant(consultant, "김컨설턴트");

  // ── 기준선 체계와 승인된 문서, 그리고 그 하위 체계 ──
  await login(page, consultant);
  const post = (path: string, data: unknown) => page.request.post(`/api${path}`, { data });
  expect((await post("/tenants", { slug: tenant, name: "테일러 주식회사" })).status()).toBe(201);
  const orgUnits = await (await page.request.get(`/api/t/${tenant}/org-units`)).json();
  const org = orgUnits[0].id;
  const baseline = await (
    await post(`/t/${tenant}/systems`, { slug: "ims", name: "전사 표준 체계", org_unit_id: org })
  ).json();
  await post(`/t/${tenant}/systems`, {
    slug: "dev",
    name: "개발본부 체계",
    org_unit_id: org,
    parent_system_id: baseline.id,
  });
  await post(`/t/${tenant}/members`, { email: qmr, name: "박품질", roles: [{ role: "qmr" }] });

  const policy = await submitted(page, tenant, { doc_type: "POL", title: "품질 방침", scope_code: "QMS" });
  const procedure = await submitted(page, tenant, {
    doc_type: "PRO",
    title: "문서 관리 절차",
    parent_id: policy.documentId,
  });
  const revise = await submitted(page, tenant, {
    doc_type: "WI",
    title: "개정 지침",
    parent_id: procedure.documentId,
  });
  const release = await submitted(page, tenant, {
    doc_type: "WI",
    title: "배포 지침",
    parent_id: procedure.documentId,
  });
  await logout(page);
  await login(page, qmr);
  await approveAll(page, tenant, [policy, procedure, revise, release].map((d) => d.revisionId));
  await logout(page);

  // ── 하위 체계는 기준선 문서를 그대로 물려받는다 ──
  await login(page, consultant);
  await page.goto(`/${tenant}/s/dev`);
  await expect(page.getByText("그대로 쓰는 문서 4건 · 재정의 0건 · 추가 0건 · 제외 0건")).toBeVisible();
  await expect(page.getByText("상속", { exact: true })).toHaveCount(4);

  // ── 지침 하나를 이 체계에 맞게 재정의한다 ──
  await page.getByRole("link", { name: /개정 지침/ }).click();
  await expect(page.getByText("의 문서를 그대로 쓰고 있습니다")).toBeVisible();
  await page.getByRole("button", { name: "이 체계에 맞게 재정의" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("사유").fill("개발본부는 코드 리뷰 도구로 개정을 관리한다");
  await dialog.getByRole("button", { name: "재정의", exact: true }).click();
  await expect(page.getByText("이 체계에 맞게 재정의한 문서입니다")).toBeVisible();
  await expect(page.getByText("사유: 개발본부는 코드 리뷰 도구로 개정을 관리한다")).toBeVisible();
  // 상위 승인판의 내용에서 시작하는 초안이다.
  await expect(page.getByRole("textbox", { name: "업무 목적", exact: true })).toHaveValue("기준선 내용");
  await fillSection(page, "업무 목적", "개발본부는 병합 요청으로 개정한다.");
  await expect(page.getByText("저장됨")).toBeVisible();
  // 오른쪽의 상위 문서 목록으로 위로 이동할 수 있다.
  const rail = page.getByRole("complementary");
  await expect(rail.getByRole("link", { name: /문서 관리 절차/ })).toBeVisible();
  await expect(rail.getByRole("link", { name: /품질 방침/ })).toBeVisible();
  await page.screenshot(shot("01-override"));
  const overrideUrl = page.url();

  // ── 다른 지침은 이 체계에서 제외한다 ──
  await page.goto(`/${tenant}/s/dev`);
  await page.getByRole("link", { name: /배포 지침/ }).click();
  await page.getByRole("button", { name: "제외", exact: true }).click();
  await dialog.getByLabel("사유").fill("배포는 운영본부가 한다");
  await dialog.getByRole("button", { name: "제외", exact: true }).click();
  await expect(page.getByText("이 체계에는 적용하지 않는 문서입니다.")).toBeVisible();
  await expect(page.getByRole("button", { name: "다시 적용" })).toBeVisible();

  await page.goto(`/${tenant}/s/dev`);
  await expect(page.getByText("그대로 쓰는 문서 2건 · 재정의 1건 · 추가 0건 · 제외 1건")).toBeVisible();
  await page.screenshot(shot("02-library"));
  // 기준선 체계는 그대로다.
  await page.goto(`/${tenant}/s/ims`);
  await expect(page.getByText("승인v1.0")).toHaveCount(4);
  await expect(page.getByText("재정의", { exact: true })).toHaveCount(0);

  // ── 기준선 지침이 개정되면 재정의한 문서에 표시된다 ──
  const started = await (
    await post(`/t/${tenant}/documents/${revise.documentId}/revisions`, {
      change_kind: "minor",
      change_summary: "승인권자 명시",
    })
  ).json();
  await fillAndSubmit(page, tenant, started, "기준선 보완: 승인권자를 명시한다");
  await logout(page);
  await login(page, qmr);
  await approveAll(page, tenant, [started.id]);
  await logout(page);

  await login(page, consultant);
  await page.goto(`/${tenant}/s/dev`);
  await expect(page.getByText("상위 문서가 바뀐 재정의 1건")).toBeVisible();
  await expect(page.getByText("상위 변경됨")).toBeVisible();
  await page.goto(overrideUrl);
  await expect(page.getByText("재정의한 뒤 상위 문서가 개정됐습니다 (v1.0 → v1.1)")).toBeVisible();
  await page.getByRole("button", { name: "변경 내용 보기" }).click();
  await expect(dialog.getByText("승인권자를 명시한다").first()).toBeVisible();
  await page.screenshot(shot("03-base-changed"));
  // 상위 신판과 이 체계 문서의 차이도 볼 수 있다.
  await dialog.getByRole("button", { name: "상위 신판과 이 체계 문서의 차이" }).click();
  await expect(dialog.getByText("병합", { exact: true }).first()).toBeVisible();
  await dialog.getByRole("button", { name: "변경을 확인했습니다" }).click();
  await expect(page.getByText("재정의한 뒤 상위 문서가 개정됐습니다")).toHaveCount(0);
});
