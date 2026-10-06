import { expect, test } from "@playwright/test";

import {
  createConsultant,
  fillAllRequired,
  fillSection,
  login,
  logout,
  openDocument,
  purgeTenant,
  unique,
} from "./helpers";

const shot = (name: string) => ({ path: `e2e/screenshots/${name}.png`, fullPage: true });

// 테스트가 만든 회사는 끝나면 지운다(개발 DB 에 쌓이지 않게).
const created: string[] = [];
test.afterEach(() => {
  for (const slug of created.splice(0)) purgeTenant(slug);
});

// S1 완료 기준: 손으로 문서를 만들고, 다른 사람이 승인하고, 개정해서 다시 승인받는다.
test("회사를 만들고 정책서를 제정·개정한다", async ({ page }) => {
  const tag = unique();
  const consultant = `consultant-${tag}@e2e.example`;
  const qmr = `qmr-${tag}@e2e.example`;
  const tenant = `e2e-${tag}`;
  created.push(tenant);
  createConsultant(consultant, "김컨설턴트");

  // ── 회사와 체계 ──
  await login(page, consultant);
  await page.getByRole("button", { name: "새 회사" }).click();
  await page.getByLabel("회사 이름").fill("이투이 주식회사");
  await page.getByLabel("주소").fill(tenant);
  await page.getByRole("button", { name: "만들기" }).click();
  await expect(page.getByRole("heading", { name: "조직·체계" })).toBeVisible();

  await page.getByRole("button", { name: "이투이 주식회사 아래에 조직 추가" }).click();
  await page.getByLabel("이름").fill("개발본부");
  await page.getByRole("button", { name: "추가", exact: true }).click();
  await expect(page.getByText("개발본부")).toBeVisible();

  await page.getByRole("button", { name: "새 체계" }).click();
  await page.getByLabel("이름").fill("통합경영체계");
  await page.getByLabel("주소").fill("ims");
  await page.getByRole("button", { name: "만들기" }).click();
  await expect(page.getByRole("link", { name: /통합경영체계/ }).first()).toBeVisible();
  await page.screenshot(shot("01-org"));

  // ── 검토자 추가 ──
  await page.getByRole("link", { name: "구성원" }).click();
  await page.getByRole("button", { name: "구성원 추가" }).click();
  await page.getByLabel("이메일").fill(qmr);
  await page.getByLabel("이름").fill("박품질");
  await page.getByRole("button", { name: "역할 추가" }).click();
  await page.getByLabel("역할", { exact: true }).selectOption("qmr");
  await page.getByRole("button", { name: "추가", exact: true }).click();
  await expect(page.getByText("박품질")).toBeVisible();
  await expect(page.getByText("품질 책임자 · 회사 전체")).toBeVisible();

  // ── 정책서 작성 ──
  await page.getByRole("link", { name: "통합경영체계" }).click();
  await expect(page.getByText("아직 문서가 없습니다")).toBeVisible();
  await page.getByRole("button", { name: "첫 문서 만들기" }).click();
  await page.getByLabel("제목").fill("문서 관리 정책");
  await page.getByLabel("영역").selectOption("QMS");
  await page.getByRole("button", { name: "만들고 작성 시작" }).click();

  await expect(page.getByText("POL-QMS-01")).toBeVisible();
  await expect(page.getByRole("button", { name: "검토 요청" })).toBeDisabled();
  await fillAllRequired(page, {
    목적: "문서가 **최신 상태**로 유지되도록 관리 원칙을 정한다.",
    "적용 범위": "전사의 모든 프로세스 문서.",
    "정책 원칙": "1. 승인되지 않은 문서는 기준으로 쓰지 않는다.\n2. 승인된 판은 수정하지 않는다.",
    "역할과 책임": "| 역할 | 책임 |\n|---|---|\n| 프로세스 오너 | 작성·개정 |\n| 품질 책임자 | 검토·승인 |",
  });
  await page.screenshot(shot("02-editor"));
  await page.getByRole("button", { name: "검토 요청" }).click();
  await expect(page.getByText("검토 중입니다")).toBeVisible();
  // 작성자에게는 승인 버튼이 없다.
  await expect(page.getByRole("button", { name: "승인", exact: true })).toHaveCount(0);

  // ── 다른 사람이 승인 ──
  await logout(page);
  await login(page, qmr);
  await page.getByRole("link", { name: /이투이 주식회사/ }).click();
  await expect(page.getByRole("heading", { name: "검토 요청" })).toBeVisible();
  await page.screenshot(shot("03-inbox"));
  await openDocument(page, /문서 관리 정책/);
  await expect(page.getByRole("table")).toBeVisible(); // Markdown 표가 그려진다
  await page.screenshot(shot("04-review"));
  await page.getByRole("button", { name: "승인", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "승인" }).click();
  await expect(page.getByText("승인v1.0").first()).toBeVisible();

  // ── 개정 ──
  await logout(page);
  await login(page, consultant);
  await page.getByRole("link", { name: /이투이 주식회사/ }).click();
  await page.getByRole("link", { name: "통합경영체계" }).first().click();
  await openDocument(page, /문서 관리 정책/);
  await page.getByRole("button", { name: "개정 시작" }).click();
  await page.getByRole("button", { name: /경미 개정/ }).click();
  await page.getByRole("button", { name: "초안 만들기" }).click();
  await fillSection(page, "적용 범위", "전사의 모든 프로세스 문서와 그에 따른 기록.");
  await page.getByLabel("변경 요약").fill("적용 범위에 기록을 추가");
  await expect(page.getByText("저장됨")).toBeVisible();

  await page.getByRole("button", { name: "변경 비교" }).click();
  await expect(page.getByText("v1.0 → v1.1 · 바뀐 곳 1")).toBeVisible();
  await expect(page.locator("ins")).toContainText("기록");
  await page.screenshot(shot("05-compare"));

  await page.getByRole("button", { name: /진행 중 v1\.1/ }).click();
  await page.getByRole("button", { name: "검토 요청" }).click();
  await expect(page.getByText("검토 중입니다")).toBeVisible();

  await logout(page);
  await login(page, qmr);
  await page.getByRole("link", { name: /이투이 주식회사/ }).click();
  await openDocument(page, /문서 관리 정책/);
  await page.getByRole("button", { name: "승인", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "승인" }).click();
  await expect(page.getByText("승인v1.1").first()).toBeVisible();
  // 이전 판은 이력에 '대체됨' 으로 남는다.
  await expect(page.getByRole("button", { name: /대체됨 v1\.0/ })).toBeVisible();
  await page.screenshot(shot("06-approved"));

  // ── 하위 문서와 감사 기록 ──
  await logout(page);
  await login(page, consultant);
  await page.getByRole("link", { name: /이투이 주식회사/ }).click();
  await page.getByRole("link", { name: "통합경영체계" }).first().click();
  await openDocument(page, /문서 관리 정책/);
  await page.getByRole("button", { name: "하위 문서 추가" }).click();
  await page.getByLabel("제목").fill("문서 개정 절차");
  await page.getByRole("button", { name: "만들고 작성 시작" }).click();
  await expect(page.getByText("PRO-QMS-01-01").first()).toBeVisible();

  await page.getByRole("link", { name: "통합경영체계" }).first().click();
  await expect(page.getByRole("link", { name: /문서 개정 절차/ })).toBeVisible();
  await page.screenshot(shot("07-library"));

  await page.getByRole("link", { name: "감사 기록" }).click();
  await expect(page.getByText("기록이 온전합니다")).toBeVisible();
  await expect(page.getByRole("cell", { name: "승인", exact: true })).toHaveCount(2);
  await page.screenshot(shot("08-audit"));
});
