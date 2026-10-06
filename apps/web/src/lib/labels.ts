// 화면에 쓰는 이름과 색. 코드 값 → 사람이 읽는 말.

export const STATUS_LABEL: Record<string, string> = {
  draft: "초안",
  in_review: "검토 중",
  approved: "승인",
  superseded: "대체됨",
};

export const STATUS_STYLE: Record<string, string> = {
  draft: "bg-amber-500/12 text-amber-700 dark:text-amber-300",
  in_review: "bg-sky-500/12 text-sky-700 dark:text-sky-300",
  approved: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
  superseded: "bg-muted text-muted-foreground",
};

export const DOC_TYPE_STYLE: Record<string, string> = {
  POL: "bg-violet-500/12 text-violet-700 dark:text-violet-300",
  PRO: "bg-blue-500/12 text-blue-700 dark:text-blue-300",
  WI: "bg-teal-500/12 text-teal-700 dark:text-teal-300",
  TMP: "bg-amber-500/12 text-amber-700 dark:text-amber-300",
  EX: "bg-pink-500/12 text-pink-700 dark:text-pink-300",
  REF: "bg-slate-500/12 text-slate-700 dark:text-slate-300",
};

export const ORG_KIND_LABEL: Record<string, string> = {
  company: "회사",
  division: "본부",
  team: "팀",
  project: "프로젝트",
};

export const TENANT_ROLE_LABEL: Record<string, string> = {
  tenant_admin: "관리자",
  member: "구성원",
};

export const SYSTEM_ROLE_LABEL: Record<string, string> = {
  process_owner: "프로세스 오너",
  qmr: "품질 책임자",
  admin: "체계 관리자",
  executor: "실행자",
  auditor: "심사원",
  viewer: "열람자",
};

export const SYSTEM_ROLE_HINT: Record<string, string> = {
  process_owner: "문서 작성·개정·검토",
  qmr: "문서 검토·승인",
  admin: "문서 작성·개정·검토",
  executor: "열람 (실행 기능은 이후 제공)",
  auditor: "열람 (심사 기능은 이후 제공)",
  viewer: "열람",
};

export const SOURCE_STATUS_LABEL: Record<string, string> = {
  extracted: "조항 분석 완료",
  mining: "요건 도출 중",
  mined: "검토 대기",
  confirmed: "요건 확정",
};

export const SOURCE_STATUS_STYLE: Record<string, string> = {
  extracted: "bg-muted text-muted-foreground",
  mining: "bg-sky-500/12 text-sky-700 dark:text-sky-300",
  mined: "bg-amber-500/12 text-amber-700 dark:text-amber-300",
  confirmed: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
};

export const OBLIGATION_LABEL: Record<string, string> = {
  shall: "필수",
  should: "권고",
  may: "허용",
};

export const OBLIGATION_STYLE: Record<string, string> = {
  shall: "bg-rose-500/12 text-rose-700 dark:text-rose-300",
  should: "bg-amber-500/12 text-amber-700 dark:text-amber-300",
  may: "bg-muted text-muted-foreground",
};

export const REQUIREMENT_CATEGORY_LABEL: Record<string, string> = {
  process: "활동",
  documentation: "문서화",
  verification: "검증",
  record: "기록",
  other: "기타",
};

export const CHANGE_KIND_LABEL: Record<string, string> = {
  minor: "경미 개정",
  major: "주요 개정",
};

export const AUDIT_ACTION_LABEL: Record<string, string> = {
  "tenant.create": "회사 생성",
  "tenant.update": "회사 설정 변경",
  "tenant.archive": "회사 보관",
  "tenant.restore": "회사 복원",
  "org_unit.create": "조직 추가",
  "org_unit.delete": "조직 삭제",
  "system.create": "체계 생성",
  "member.add": "구성원 추가",
  "member.update": "구성원 권한 변경",
  "source.upload": "원문 등록",
  "source.mine": "요건 도출 시작",
  "source.confirm": "요건 확정",
  "source.delete": "원문 삭제",
  "basis.attach": "근거 원문 추가",
  "basis.detach": "근거 원문 제외",
  "basis.approve": "적용요건 승인",
  "basis.reopen": "적용요건 승인 취소",
  "plan.design": "문서 구조 설계",
  "plan.write": "요건에서 문서 생성",
  "plan.discard": "설계안 폐기",
  "document.create": "문서 생성",
  "document.delete": "문서 삭제",
  "revision.start": "개정 시작",
  "revision.discard": "초안 폐기",
  "revision.submit": "검토 요청",
  "revision.withdraw": "검토 요청 회수",
  "revision.approve": "승인",
  "revision.reject": "반려",
};

const dateFormat = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" });
const dateTimeFormat = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" });
const relativeFormat = new Intl.RelativeTimeFormat("ko-KR", { numeric: "auto" });

export function formatDate(value: string | null | undefined): string {
  return value ? dateFormat.format(new Date(value)) : "";
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? dateTimeFormat.format(new Date(value)) : "";
}

export function formatRelative(value: string): string {
  const seconds = (new Date(value).getTime() - Date.now()) / 1000;
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) {
      const amount = Math.round(seconds / size);
      // 한 달이 넘으면 날짜로 보여주는 편이 읽기 쉽다.
      if (unit === "day" && Math.abs(amount) > 30) return formatDate(value);
      return relativeFormat.format(amount, unit);
    }
  }
  return "방금";
}
