import type { Artifact } from "@/lib/api";

/** 산출물이 지금 어느 단계에 있는지. 사람이 해야 할 일이 드러나게 이름 붙인다. */
export const ARTIFACT_STATE: Record<string, { label: string; style: string }> = {
  processing: { label: "처리 중", style: "bg-sky-500/12 text-sky-700 dark:text-sky-300" },
  needs_template: { label: "양식 선택 필요", style: "bg-amber-500/12 text-amber-700 dark:text-amber-300" },
  needs_confirm: { label: "양식 확인 필요", style: "bg-amber-500/12 text-amber-700 dark:text-amber-300" },
  review: { label: "검토 중", style: "bg-violet-500/12 text-violet-700 dark:text-violet-300" },
  published: { label: "발행됨", style: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300" },
};

type Counts = NonNullable<Artifact["record"]>["counts"];

/** 기록에서 사람의 손이 필요한 항목 수. 없으면 아무것도 그리지 않는다. */
export function RecordCountsNote({ counts }: { counts: Counts }) {
  if (counts.unverified === 0 && counts.empty === 0) return null;
  return (
    <span className="text-xs whitespace-nowrap text-amber-700 dark:text-amber-300">
      {[
        counts.unverified > 0 && `확인 ${counts.unverified}`,
        counts.empty > 0 && `빈 항목 ${counts.empty}`,
      ]
        .filter(Boolean)
        .join(" · ")}
    </span>
  );
}
