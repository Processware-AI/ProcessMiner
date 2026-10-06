import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

const API_DIR = path.resolve(__dirname, "../../api");
const PYTHON =
  process.env.API_PYTHON ??
  path.join(API_DIR, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

function cli(...args: string[]) {
  execFileSync(PYTHON, ["-m", "app.cli", ...args], { cwd: API_DIR, stdio: "pipe" });
}

/** 테스트마다 겹치지 않는 짧은 꼬리표. */
export function unique(): string {
  return Math.random().toString(36).slice(2, 8);
}

/** 회사를 만들 수 있는 사용자를 준비한다. */
export function createConsultant(email: string, name: string) {
  cli("create-user", email, name, "--platform-role", "consultant");
}

/** 테스트가 만든 회사를 지운다. 이미 지워졌으면 아무 일도 하지 않는다. */
export function purgeTenant(slug: string) {
  try {
    cli("purge-tenant", slug, "--actor", "admin@example.com", "--yes");
  } catch {
    // 테스트 안에서 이미 지운 회사
  }
}

/** 이메일 링크 흐름으로 로그인한다(개발 설정에서는 링크가 화면에 나온다). */
export async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("이메일").fill(email);
  await page.getByRole("button", { name: "로그인 링크 받기" }).click();
  await page.getByRole("button", { name: "바로 로그인" }).click();
  await expect(page.getByRole("heading", { name: "회사" })).toBeVisible();
}

export async function logout(page: Page) {
  await page.context().clearCookies();
}

/** 편집기의 한 섹션에 본문을 채운다. */
export async function fillSection(page: Page, title: string, body: string) {
  await page.getByRole("textbox", { name: title, exact: true }).fill(body);
}

export async function fillAllRequired(page: Page, sections: Record<string, string>) {
  for (const [title, body] of Object.entries(sections)) await fillSection(page, title, body);
  await expect(page.getByText("저장됨")).toBeVisible();
}

/** 목록에서 문서를 열고, 문서 화면으로 바뀔 때까지 기다린다. */
export async function openDocument(page: Page, title: RegExp) {
  await page.getByRole("link", { name: title }).click();
  await expect(page.getByRole("navigation", { name: "위치" })).toBeVisible();
}
