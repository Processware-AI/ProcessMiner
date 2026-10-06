# 4차원 PDCA AI 자동화 플랫폼 (Claude Code + Obsidian)

국제/국내 표준(ISO·IEC·KS·IATF 등)의 **수립(Plan) → 이행(Do) → 심사(Check) → 제·개정(Act)** 4 차원 전체를 AI 에이전트로 자동화하는 플랫폼. **4차원 PDCA 폐쇄 루프** PoC 검증 완료 (Plan→Do→Check→Act→Plan' 사이클로 KPI 회복 실증).

본 메인 repo 의 본업은 **코어 vault — 조직 표준 프로세스 자산 (POL/PRO/WI/TMP/EX/MAT/REF) 구축**.
입력은 국제표준·법규·해설서·산업가이드·기존 조직 자산 같은 **영속 기준** 만 받는다. RFP·발주문서·SoW 등 1회성 사업 명세는 본 repo 가 아니라 **별도 repo 의 파생 프로덕트** 영역:

- 파생 ①: [processware-rfp-to-proposal](https://github.com/Processware-AI/processware-rfp-to-proposal) — RFP → 응시자 제안서(Proposal) 자동 작성
- 파생 ② (향후): Project Asset Generator — 채택 제안서 + 코어 vault → 사업 산출물

> 상위 개념: `AI-Driven CMMI Operating Platform.md` (Layer 1/2/3 비전) · `표준프로세스_AI관리체계_4차원PDCA.md` (4차원 PDCA 설계)
> 파생 프로덕트 비전: `docs/architecture/derivative-products.md` (3-Vault 생태계 — 코어 + RFP-to-Proposal + Project Asset Generator)
> 차원별 운영 가이드: `표준_빌드_워크플로우_가이드.md` (1) · `표준_프로세스_실행_가이드.md` (2) · `표준_프로세스_심사_가이드.md` (3) · `표준_프로세스_제개정_가이드.md` (4)

## 웹 플랫폼 (개발 중)

여러 회사·여러 조직의 체계를 한 저장소에서 운영하기 위해, 아래 CLI 하네스에서 검증한 개념을 웹 애플리케이션으로 옮기는 중이다. 코드는 `apps/`(API·웹)와 `seed/`(참조 데이터)에 있고, 실행 방법과 진행 상황은 [`apps/README.md`](apps/README.md) 에 있다. 이 문서의 나머지는 기존 CLI 하네스(`.claude/`, `vault/`, `publish/`)를 설명한다.

## 5단계 자동화 매트릭스

| 차원 | 슬래시 | 에이전트 | 핵심 산출물 |
|---|---|---|---|
| **0 (Ingest)** 표준 전처리 | `/process-ingest` | flow-proposer (1) | inputs/ 요건 패키지 (requirements.yaml · structure.yaml) + business_flow.yaml |
| **1 (Plan)** 표준 수립 | `/process-plan` | standard-analyzer · process-designer · wi-tmp-writer · qa-reviewer · traceability-mapper · flow-mapper (6) | POL / PRO / WI / TMP / EX / MAT / REF + MAT-010 프로세스 플로우맵 |
| **2 (Do)** 프로세스 실행 | `/process-do` | process-router · process-executor · hitl-gatekeeper · rec-writer · escalation-coordinator (5) | REC + MAT-005 §실행기록 + MAT-007 카탈로그 |
| **2 (Backfill)** 레거시 변환 | `/process-backfill` | backfill-matcher · rec-writer (2) | REC (verdict_type: legacy_evidence) + MAT-005 §실행기록 |
| **3 (Check)** 이행 심사·KPI | `/process-check` (`--kpi` `--act-queue` `--rbac-check`) | audit-planner · evidence-collector · compliance-checker · audit-reporter · ncr-drafter · kpi-collector · kpi-analyzer · independence-guard · act-trigger (9) | REC-AUDIT / REC-NCR + MAT-008 KPI 대시보드 + MAT-009 NCR 관리대장 + act queue |
| **3 (Audit)** 외부 표준 GAP | `/process-audit` | gap-analyzer · gap-reporter · gap-exporter (3) | REC-GAP + MAT-002 §GAP 분석 + act queue (critical/major GAP) + exports/ (XLSX·HTML·PDF) |
| **4 (Act)** 제·개정 | `/process-act` | rca-analyzer · revision-planner · pcb-gatekeeper · act-coordinator (4) | As-Is 입력 + MAT-001 §개정이력 + 차원 1 재트리거 명령 |

**총 29 에이전트 / 7 슬래시 + 2 통합 스킬** — 모든 차원이 단일 브랜치(main)에 통합되어 운영.

> **Phase 5 (외부 시스템 연동)**: `/vault-push`, `/workspace-create` — vault → Redmine 단방향 Push 구현 완료. `publish/redmine/` 참조.

## 특징

### 차원 0 (Ingest) — 표준 전처리
- **8단계 파이프라인**: Source Intake → Text Extraction → Structural Parsing → Requirement Mining → Classification → Traceability → QA Review → Handoff
- **Phase 9 (flow-proposer)**: 요구사항 분석 결과로 업무 시나리오 도출 → HITL 선택 → `inputs/06_목표흐름/business_flow.yaml` 생성
- **이중 레이어 출력**: `requirements.yaml` (표준 요건) + `business_flow.yaml` (조직 업무 시나리오)
- **HITL 강제 검토**: Phase 7 QA 완료 후 `/process-ingest --confirm` 전까지 차단
- **delta 모드**: 표준 개정 시 ADD/MODIFIED/DEPRECATED 상태로 요건 갱신

### 차원 1 (Plan) — 표준 수립
- **8종 문서 유형 체계**: POL / PRO / WI / TMP / EX / REC / MAT / REF
- **유형별 엄격한 분리**: 템플릿↔기록↔예시 분리, 정책↔절차↔지침 분리
- **계층 번호 체계**: `POL-{영역}-{###}` → `PRO-{P}{##}` → `WI-{POL}-{PRO}-{##}` 계보 추적
- **Business / Process Flow 이중 레이어**: ingest의 `business_flow.yaml` 기반으로 PRO 간 선후관계(`follows`/`precedes`) + WI 시퀀스(`wi_sequence[]`) 설계 → Phase 3.5 `flow-mapper`가 MAT-010 프로세스 플로우맵 파생 생성
- **통합 MAT 10종 운영** (MAT-001~009 + MAT-010 프로세스 플로우맵)
- **표준 분류 레지스트리**: Layer(L1/L2/L3)·Structure·Integration Mode 3축 분류
- **표준 무관(standard-agnostic)**: ISO·IEC·KS·IATF·CMMI·법규·사내규정·고객 요구사항 등 어떤 구조화 문서든 `/process-ingest`로 편입 가능
- **표준-프로세스 양방향 추적성** + `source_citation` 기반 감사증적
- **체크포인트/재개** (`_state.yaml`): 실패 지점부터 이어 실행
- **자가수정 루프**: QA Fail → 담당 에이전트 자동 재호출 (max 3 attempts)
- **골든샘플**: POL/PRO/WI 품질 하한선 참조

### 차원 2 (Do) — 프로세스 실행
- **WI 이중 포맷**: WI MD (사람용) + WI steps.yaml (Agent 실행용) 짝 자동 생성
- **HITL 다단계 승인**: review → approve → final 자동 chain (WI §2 RACI 자동 추출)
- **타임아웃·에스컬레이션**: SLA 만료 시 escalate_to[] 체인 자동 발송
- **자연어 라우팅**: "작업산출물 평가" → WI-CMMI-04-01-03 자동 매칭 (MAT-007 프로세스 카탈로그)
- **반려 처리**: REC.status: rejected + MAT-005 ❌ 표기 + 시정조치 후 재실행 흐름

### 차원 2B (Backfill) — 레거시 REC 변환
- **자동 WI 매칭**: DOCX/XLSX/PDF/PPT → MAT-007 기반 4-신호 유사도 분석 (키워드·산출물유형·제목·표헤더)
- **confidence 임계값**: ≥75% ✅ 자동 확정 / 50~74% ⚠️ HITL 수정 권장 / <50% ❌ 제외
- **배치 HITL 단일화**: 전체 파일 결과를 한 테이블로 한 번만 제시
- **legacy_evidence 마킹**: 모든 백필 REC 에 `verdict_type: legacy_evidence` 자동 기록
- **심사 연동**: `/process-check` 에서 legacy_evidence = partial 로 계산, NCR 미발행, 별도 집계

### 차원 3 (Check) — 심사·KPI·NCR
- **REC ↔ PRO/WI 요건 자동 대조**: 4-tier verdict (conformant / partial / nonconformant / not_assessed)
- **NCR 자동 발행**: finding 별 REC-NCR + SLA 휴리스틱 (critical 20영업일 / major 60일 / minor 90일) + R/A 자동 추정
- **KPI 대시보드**: PRO/WI §KPI 자동 추출 + 메타 KPI 5종 + 회귀 탐지 (default ±5%p) + Mermaid 시계열 시각화
- **ISO §9.2 독립성 강제**: independence-guard 가 audit 진입 시 auditor ≠ trace.executed_by 자동 검증
- **RBAC 6 역할**: auditor / executor / process_owner / qmr / admin / viewer

### 차원 3 (Audit) — 외부 표준 GAP 분석
- **외부 표준 대조**: 표준 조항 ↔ 내부 POL/PRO/WI 커버리지 자동 판정 (COVERED / PARTIAL / GAP / N/A)
- **strictness 3단계**: strict (THIN 포함) / normal / lenient 모드
- **LLM fallback**: inputs/ 없을 때 LLM 내부 지식으로 조항 추출 (낮은 신뢰도 표시)
- **GAP → act 자동 트리거**: confirm 후 critical/major GAP을 `kind: gap_remediation` 큐로 자동 push (--no-act-queue 억제 가능)
- **외부 인증기관 내보내기**: `--export --format xlsx|html|pdf` — openpyxl 3시트 스크립트(커버리지 요약·부합성 매트릭스·GAP 상세) 또는 Noto Sans KR A4 HTML

### 차원 4 (Act) — 제·개정
- **5-Why / Fishbone RCA**: queue → primary_root_cause + confidence + secondary
- **개정 범위 결정**: 5종 rebuild_mode (manual_edit / rec_only / `--from write` / `--from design` / `--restart`)
- **PCB 승인 게이트**: HITL drop-out + Phase 4.5 다단계 quorum (4 모드)
- **차원 1 재트리거 인계**: As-Is 입력 파일 자동 작성 → 사용자가 `/process-plan --from write` 실행
- **다중 큐 일괄** (Phase 2): merged_root_cause + Mermaid 의존성 그래프 + 통합 As-Is

### 폐쇄 루프 (4차원 통합)
- **act queue 자동 발행**: 차원 3 의 NCR + critical KPI + critical/major GAP → `.claude/queues/process-act/queue-q*.yaml` 자동 push
- **차원 4 인계 큐**: act-trigger 가 confirm/kpi-finalize/gap-confirm 직후 자동 발행 (NCR · KPI · GAP 3종 통합 휴리스틱)
- **PoC 실증**: queue-qa1b2c3d4 (NCR-001 critical) → PRO v1.0 → v1.1 → CAPA REC → NCR close → KPI round 2 회복 (critical 4→1, healthy 3→6, recovering 0→2)

### Phase 5 (외부 시스템 연동) — Redmine 구현 완료

- **Headless CMS 모델**: vault = 콘텐츠 저장소, Redmine = API 소비자. 단방향 Push (vault SSoT → Redmine, 역방향 없음)
- **Process Library**: `lib-{scope_code}` Redmine 프로젝트로 구성. PRO별 Library Module (`lib-{scope_code}-{pro_slug}`) 서브프로젝트. vault push 관리, 직접 편집 금지
- **Workspace**: 현업 업무 단위 가상 공간. `ws-{slug}` 상위 프로젝트 + PRO 단위 서브프로젝트로 구성. Library 복사본이므로 팀 자율 편집 가능
- **자동화**: git post-commit hook + GitHub Actions (`feat/*-output`, `main` 브랜치 + `vault/**/*.md` 경로 트리거)
- **sync_map SQLite DB**: vault_doc_id ↔ Redmine resource 매핑, 변경분 추적
- **이슈 동기화**: REC → Redmine Issue (프로세스기록 Tracker), REC-NCR → Issue (NCR Tracker) + STATUS_MAP/PRIORITY_MAP

### Phase 4.5 명세 (외부 인프라 연동 준비)
- **RBAC extensions**: external_idp (OIDC) + delegation + audit_log + external_notifications (이메일/Slack/Jira)
- **한국 영업일 계산기** (`.claude/utils/business_days_kr.md`): 공휴일 14개 + add_business_days 알고리즘
- **PCB 다단계 quorum** (`.claude/utils/pcb_quorum.md`): simple_majority / supermajority / unanimous / chair_veto
- **자동 트렌드 Mermaid** (`.claude/utils/auto_trend_mermaid.md`): round ≥ 2 부터 라인/bar/graph TD 자동 생성

## 디렉터리 구조
```
STD_Process_Builder/
├── README.md
├── docs/
│   └── architecture/
│       └── derivative-products.md           ← 파생 프로덕트 3-Vault 비전 + 분리 로드맵
├── (subproducts/ 없음 — 모든 파생은 별도 repo 운영)
├── AI-Driven CMMI Operating Platform.md     ← Layer 1/2/3 비전 (ML3→ML4→ML5)
├── 표준프로세스_AI관리체계_4차원PDCA.md      ← 4차원 PDCA 설계
├── 전용AI에이전트_프레임워크_설계안.md       ← 차원 1 독립 제품화 설계 (Python/SDK)
├── 표준_빌드_워크플로우_가이드.md           ← 차원 1 운영 가이드 (worktree 정책)
├── 표준_프로세스_실행_가이드.md             ← 차원 2 운영 가이드 (Phase 1~4 + 2.5/3.5)
├── 표준_프로세스_심사_가이드.md             ← 차원 3 운영 가이드 (Phase 1~4 + 4.5 명세)
├── 표준_프로세스_제개정_가이드.md           ← 차원 4 운영 가이드 (Phase 1~2 + 4.5 명세)
├── .claude/                                 ← 4차원 자동화 인프라
│   ├── commands/                            ← 슬래시 커맨드 7 + 통합 스킬 2
│   │   ├── process-ingest.md               ← 차원 0 (9 Phase + flow-proposer)
│   │   ├── process-plan.md                 ← 차원 1 (Phase 3.5 + --flow 포함)
│   │   ├── process-do.md                   ← 차원 2 (8 진입 모드)
│   │   ├── process-backfill.md             ← 차원 2B (레거시 → REC 백필, 7 Phase)
│   │   ├── process-check.md                ← 차원 3 (--kpi, --act-queue, --rbac-check)
│   │   ├── process-audit.md                ← 차원 3 Audit (외부 표준 GAP 분석)
│   │   ├── process-act.md                  ← 차원 4 (7 진입 모드 + --batch)
│   │   ├── vault-push.md                   ← Phase 5 (vault → Redmine Library 단방향 Push)
│   │   └── workspace-create.md             ← Phase 5 (Workspace 생성·동기화·관리)
│   ├── agents/                              ← 29 에이전트 (차원별 1/6/5+2/9+3/4)
│   │   ├── flow-proposer.md                 ← 차원 0 Phase 9 (시나리오 도출 HITL → business_flow.yaml)
│   │   ├── standard-analyzer.md             ← 차원 1
│   │   ├── process-designer.md
│   │   ├── wi-tmp-writer.md
│   │   ├── qa-reviewer.md
│   │   ├── traceability-mapper.md
│   │   ├── flow-mapper.md                   ← 차원 1 Phase 3.5 (MAT-010 프로세스 플로우맵 파생)
│   │   ├── process-router.md                ← 차원 2 (Phase 3 자연어 라우팅)
│   │   ├── process-executor.md              ← 차원 2 (Phase 4 steps.yaml 우선순위)
│   │   ├── hitl-gatekeeper.md               ← 차원 2 (Phase 2/2.5 다단계)
│   │   ├── rec-writer.md                    ← 차원 2 + 차원 2B (backfill 모드 포함)
│   │   ├── escalation-coordinator.md        ← 차원 2 Phase 2.5
│   │   ├── backfill-matcher.md              ← 차원 2B Phase 3 (MAT-007 기반 WI 자동 매칭)
│   │   ├── audit-planner.md                 ← 차원 3 Phase 1
│   │   ├── evidence-collector.md
│   │   ├── compliance-checker.md
│   │   ├── audit-reporter.md
│   │   ├── ncr-drafter.md                   ← 차원 3 Phase 2 (issue / close)
│   │   ├── kpi-collector.md                 ← 차원 3 Phase 3
│   │   ├── kpi-analyzer.md
│   │   ├── independence-guard.md            ← 차원 3 Phase 4 (ISO §9.2 + RBAC)
│   │   ├── act-trigger.md                   ← 차원 3 → 4 인계 큐 발행
│   │   ├── gap-analyzer.md                  ← 차원 3 Audit Phase 1 (외부 표준 GAP 분석)
│   │   ├── gap-reporter.md                  ← 차원 3 Audit Phase 2 (REC-GAP + MAT-002 갱신)
│   │   ├── gap-exporter.md                  ← 차원 3 Audit Phase 3 (XLSX·HTML·PDF 내보내기)
│   │   ├── rca-analyzer.md                  ← 차원 4 Phase 1 (5-Why / Fishbone)
│   │   ├── revision-planner.md              ← 차원 4 Phase 2 (Mermaid 의존성 그래프)
│   │   ├── pcb-gatekeeper.md                ← 차원 4 Phase 1 (HITL + 4.5 quorum)
│   │   └── act-coordinator.md               ← 차원 4 Phase 1 (As-Is + MAT-001)
│   ├── rbac/
│   │   └── policy.yaml                      ← 6 역할 + Phase 4.5 extensions 4종
│   ├── queues/
│   │   └── act/                             ← 차원 4 인계 큐 (queue-q*)
│   ├── runs/                                ← 실행 trace (5 prefix)
│   │   ├── run-{hex}/                       ← 차원 2 do trace
│   │   ├── run-a*/                          ← 차원 3 audit trace
│   │   ├── run-k*/                          ← 차원 3 kpi trace
│   │   ├── run-g*/                          ← 차원 3 audit (GAP 분석) trace
│   │   └── run-c*/                          ← 차원 4 act trace
│   └── utils/                               ← Phase 4.5 명세 (3)
│       ├── business_days_kr.md              ← 한국 영업일 (KST 공휴일 14개)
│       ├── pcb_quorum.md                    ← PCB 다단계 quorum (4 모드)
│       └── auto_trend_mermaid.md            ← round ≥ 2 자동 트렌드
├── publish/                            ← Phase 5 외부 시스템 연동
│   └── redmine/                             ← Redmine 단방향 Push (Headless CMS 모델)
│       ├── config.yaml                      ← Redmine URL/API KEY + project_mapping + sync_rules
│       ├── requirements.txt                 ← python-frontmatter, requests, PyYAML
│       ├── redmine_client.py                ← RedmineClient (project, wiki, issue CRUD)
│       ├── db.py                            ← sync_map + workspace_map SQLite DB
│       ├── transformer.py                   ← Obsidian → Redmine 변환 (wikilink, 헤더)
│       ├── sync.py                          ← 메인 CLI: --setup, --changed, --dry-run 등
│       ├── library_setup.py                 ← lib-* 프로젝트 계층 자동 생성
│       ├── issue_sync.py                    ← REC/NCR → Redmine Issue 동기화
│       ├── workspace.py                     ← Workspace create/sync/list/status
│       ├── post-commit.hook                 ← git hook (vault/*.md 변경 감지 → 백그라운드 push)
│       └── install-hook.sh                  ← post-commit hook 설치 스크립트
├── .github/workflows/
│   └── vault-push.yml                       ← GitHub Actions (feat/*-output · main + vault/**/*.md)
└── vault/                                   ← Obsidian Vault 루트 (영구 자산)
    ├── 00_공통관리/                         ← 문서체계·번호체계·용어집·레지스트리
    ├── 00_MOC/                              ← 인덱스(Map of Content)
    ├── 01_구성원칙/                         ← 최상위 기준
    ├── 02_표준/                             ← 표준별 작업 공간
    │   ├── _scaffold/                       ← 새 표준 편입용 스캐폴드 템플릿
    │   │   └── _inputs/                     ← 카테고리별 입력자료 투하 폴더
    │   └── CMMI-DEV-ML3/                    ← (예시) 첫 편입 표준
    │       └── _inputs/04_AsIs/             ← 차원 4 As-Is 입력 (queue-q*.md 추적)
    ├── 03_POL_정책/                         ← POL-*
    ├── 04_PRO_절차/                         ← PRO-*
    ├── 05_WI_업무지침/                      ← WI-* + .cache/ steps.yaml fallback
    ├── 06_TMP_템플릿/                       ← TMP-*
    ├── 07_EX_작성예시/                      ← EX-*
    ├── 08_REC_기록/                         ← REC-* (차원 2 do 산출)
    │   └── AUDIT/                           ← REC sub-type AUDIT/NCR (차원 3 산출)
    ├── 09_REF_참고자료/                     ← REF-*
    ├── 90_MAT_통합매핑/                     ← MAT-001~010 전사 공통 + MAT-011~ 표준별
    │   └── MAT-010_프로세스_플로우맵.md     ← PRO 선후관계 + WI 시퀀스 (flow-mapper 파생)
    ├── 99_템플릿/                           ← Obsidian Templates
    │   └── _골든샘플/                       ← POL/PRO/WI 품질 하한선 참조 예시
    ├── 99_폐기_보관/                        ← 만료/폐지 문서 아카이브
    └── _inputs_common/                      ← 복수 표준 공통 입력자료
```

## 4차원 PDCA 폐쇄 루프 흐름 (전체)

```
[차원 1 Plan]                        [차원 2 Do]                       [차원 3 Check]
/process-plan ISO9001              /process-do WI-XXX                        /process-check start <PRO|WI|표준>
        │                                    │                                  │
        ▼                                    ▼                                  ▼
┌──────────────────┐                ┌──────────────────┐              ┌──────────────────┐
│ standard-analyzer│ → REF/MAT-002  │  process-router  │ ← MAT-007    │  audit-planner   │ → audit_plan
│ process-designer │ → POL/PRO       │ process-executor │ → REC payload│evidence-collector│ → evidence
│  wi-tmp-writer   │ → WI/TMP/EX    │  hitl-gatekeeper │ → 정지/승인  │compliance-checker│ → conformity
│  qa-reviewer     │ → §11-A 검증   │   rec-writer     │ → REC + MAT-005│ audit-reporter   │ → REC-AUDIT
│traceability-mapper│ → MAT-001~011 │escalation-coord. │ → 타임아웃   │  ncr-drafter     │ → REC-NCR + MAT-009
└──────────────────┘                └──────────────────┘              │  kpi-collector   │ → kpi_data
        │                                    │                       │  kpi-analyzer    │ → MAT-008
        ▼                                    ▼                       │independence-guard│ → ISO §9.2
   POL/PRO/WI/TMP/EX/MAT/REF              REC + MAT-005 §실행기록   │   act-trigger    │ → queue-q*
                                                                     └──────────────────┘
                                                                              │
                                                                              ▼
                                                             REC-AUDIT + REC-NCR + MAT-008 + queue-q*
                                                                              │
                                                            ┌─────────────────┴────────────┐
                                                            │                              │
                                                            ▼                              ▼
                                                   [차원 4 Act]                  [Phase 4.5 외부 알림]
                                                   /process-act start queue-q...         (이메일/Slack/Jira hook)
                                                            │
                                                            ▼
                                                   ┌──────────────────┐
                                                   │  rca-analyzer    │ → root_cause (5-Why / Fishbone)
                                                   │revision-planner  │ → revision_plan (Mermaid)
                                                   │ pcb-gatekeeper   │ → PCB HITL 승인
                                                   │ act-coordinator  │ → As-Is 입력 + MAT-001
                                                   └──────────────────┘
                                                            │
                                                            ▼
                                                vault/02_표준/{표준}/_inputs/04_AsIs/queue-q*.md
                                                            │
                                                            ▼
                                                   [차원 1 재실행 (사용자 명시 실행)]
                                                   /process-plan --from write --target {asset}
                                                            │
                                                            ▼
                                                       개정판 (v1.1) → 다음 사이클
```

> Plan→Do→Check→Act→Plan' 폐쇄 루프 PoC 검증 (run-c4f8a1b2 / queue-qa1b2c3d4 → PRO v1.0→v1.1 → KPI round 2 회복).
> **27 에이전트 / 6 슬래시 / 10 trace / 6 act queue / MAT 10종 운영**.

## 사용법

### 0. 사전 준비
1. Obsidian 에서 `vault/` 폴더를 **Open folder as vault** 로 열기.
2. **입력자료 배치 (권장)** — `vault/02_표준/{표준코드}/_inputs/` 에 표준원문·법규·해설서·As-Is 투하. 상세 규칙: `vault/00_공통관리/05_입력자료_규칙.md`

### 0-1. 차원 0 (Ingest) — 표준 전처리
```bash
/process-ingest sources/ISO9001_2015.pdf --standard ISO9001 --version 2015
/process-ingest sources/개인정보보호법.pdf --standard 개인정보보호법 --category 02
/process-ingest --confirm ISO9001                           # HITL 검토 완료 후 inputs/ 확정
/process-ingest --status ISO9001                            # 진행 상태 확인
/process-ingest --list                                      # 완료된 ingest 목록
```

> flow-proposer(Phase 9)가 업무 시나리오를 HITL로 확정 → `inputs/06_목표흐름/business_flow.yaml` 생성

### 1. 차원 1 (Plan) — 표준 수립
```bash
/process-plan ISO9001                                       # 단일 표준 편입
/process-plan ISO/IEC_27001 --cross                         # 교차 표준 통합 분석
/process-plan ISO9001 --resume                              # 현재 phase 부터 재개
/process-plan ISO9001 --from design                          # design phase 부터 강제 재시작
/process-plan ISO9001 --restart                              # 기존 state 폐기 후 처음부터
/process-plan ISO9001 --from write --target PRO-CMMI-04-01   # 차원 4 인계 후 부분 재실행
/process-plan ISO9001 --flow                                # Phase 3.5 (flow-mapper) 만 단독 실행 — MAT-010 재생성
/process-plan ISO9001 --max-attempts 5 --skip-qa            # 자가수정·QA 옵션
```

> 상세: `표준_빌드_워크플로우_가이드.md`

### 1-1. 차원 2B (Backfill) — 레거시 REC 변환
```bash
/process-backfill sources/old_docs/                                    # 배치 (폴더)
/process-backfill sources/sprint_review.docx                           # 단건 (자동 매칭)
/process-backfill sources/old.docx --wi WI-CMMI-04-01-03               # 단건 + 수동 WI 지정
/process-backfill sources/old_docs/ --backfiller "홍길동" --date 2026-03
/process-backfill --confirm run-b3f9c2b1                               # HITL 확정 → REC 생성
/process-backfill --resume run-b3f9c2b1                                # 중단된 trace 재개
/process-backfill --list                                               # 백필 이력
```

### 2. 차원 2 (Do) — 프로세스 실행
```bash
/process-do WI-CMMI-04-01-03                                           # 직접 WI 지정
/process-do "작업산출물 평가"                                          # 자연어 라우팅 (process-router)
/process-do --resume run-a3f9c2b1                                      # 정지된 trace 재개
/process-do --approve run-a3f9c2b1 --approver "박팀장"                 # HITL 승인
/process-do --reject run-a3f9c2b1 --reason "표본 부족"                 # HITL 반려
/process-do --status run-a3f9c2b1                                      # 상태 조회
/process-do --check-approvals                                          # drop-out 응답 일괄 회수
/process-do --check-timeouts                                           # SLA 만료·에스컬레이션 (cron 권장)
/process-do --rebuild-catalog --scope CMMI                             # MAT-007 카탈로그 재구축
```

> 상세: `표준_프로세스_실행_가이드.md`

### 3. 차원 3 (Check) — 심사·NCR·KPI
```bash
# 심사 (PRO/WI/표준 단위)
/process-check start PRO-CMMI-04-01 --auditor "이감사"
/process-check start CMMI-DEV-ML3 --auditor "이감사" --period 2026-01-01..2026-04-30
/process-check --confirm run-a1c2d3e4                                  # 매트릭스 확정 + NCR + 차원 4 큐 자동 발행
/process-check --confirm run-a1c2d3e4 --no-ncr --no-act-queue          # 보고서만 (NCR/큐 보류)
/process-check --reject-finding F-002 --reason "오탐" --trace run-a1c2d3e4

# NCR 관리 (Phase 2)
/process-check --list-ncr [--status open|closed] [--severity critical] [--overdue]
/process-check --close-ncr REC-NCR-04-01-2026-001 --capa REC-CMMI-04-01-04-01-2026-003

# KPI 대시보드 (Phase 3)
/process-check --kpi start CMMI-DEV-ML3 --period 2026-01-01..2026-04-30 [--baseline auto]
/process-check --kpi show CMMI-DEV-ML3 [--round 2]
/process-check --kpi check-regressions [--overdue]

# 차원 4 인계 큐 (Phase 4)
/process-check --act-queue list [--priority critical] [--kind ncr_capa]
/process-check --act-queue show queue-qa1b2c3d4
/process-check --act-queue dispatch queue-qa1b2c3d4 --to "박팀장"
/process-check --act-queue done queue-qa1b2c3d4 --capa REC-CMMI-...

# RBAC 권한 사전 검증 (Phase 4)
/process-check --rbac-check --action audit.confirm --target REC-AUDIT-...
```

> 상세: `표준_프로세스_심사_가이드.md`

### 4. 차원 4 (Act) — 제·개정
```bash
/process-act start queue-qa1b2c3d4                                     # 단일 큐
/process-act start queue-qa1b2c3d4 --rca-method both                   # 5-Why + Fishbone 모두
/process-act start queue-qa1b2c3d4 --auto-approve                      # PCB 즉시 승인 (PoC 한정)
/process-act start --batch queue-qe5f6a7b8,queue-q9d8c7b6a             # Phase 2 다중 큐 일괄
/process-act start --batch-related queue-qa1b2c3d4                     # related_to[] 자동 펼침
/process-act --resume run-c4f8a1b2
/process-act --approve run-c4f8a1b2 --approver "박상무 (PCB위원장)"     # PCB 승인 응답
/process-act --reject  run-c4f8a1b2 --reason "..."
/process-act --trigger-rebuild run-c4f8a1b2                             # 차원 1 재트리거 명령 stdout
/process-act --status run-c4f8a1b2
/process-act --list [--status pending|completed|...]
```

> 상세: `표준_프로세스_제개정_가이드.md`

### 5. Phase 5 (외부 시스템 연동) — Redmine

#### 5-A. 최초 설정 (1회)
```bash
# 1. 의존성 설치
pip3 install -r publish/redmine/requirements.txt

# 2. 환경변수 설정
export REDMINE_API_KEY=your_api_key
export REDMINE_URL=https://your-redmine.example.com

# 3. Redmine에 상위 Library 프로젝트 수동 생성 (예: lib-iso27001, lib-cmmi)
# 4. Library Module 서브프로젝트 자동 생성
/vault-push --setup               # Redmine 프로젝트 계층 자동 생성
/vault-push --setup --dry-run     # 생성 예정 미리보기

# 5. git hook 설치 (커밋 시 자동 push)
bash publish/redmine/install-hook.sh
```

#### 5-B. vault → Redmine 동기화
```bash
/vault-push                       # vault 전체 → Library 동기화
/vault-push --changed             # git diff 변경분만 (CI/CD 권장)
/vault-push WI-ISO27001-001-001-001  # 특정 문서 1건
/vault-push --type WI             # WI 전체
/vault-push --scope ISO27001      # 특정 표준 전체
/vault-push --dry-run             # 실제 전송 없이 미리보기
/vault-push --status              # 마지막 동기화 상태
```

#### 5-C. Workspace (현업 업무 단위) 생성·관리
```bash
/workspace-create create \
  --name "제품Alpha 개발" \
  --slug product-alpha \
  --modules PRO-ISO27001-001-001,PRO-ISO27001-001-002  # Library → Workspace 복사
/workspace-create create --dry-run --name "..." --slug "..." --modules "..."  # 미리보기

/workspace-create sync \
  --workspace ws-product-alpha \
  --module lib-iso27001-p001-001   # Library 최신 → Workspace 반영
/workspace-create list             # 전체 Workspace 목록
/workspace-create status --workspace ws-product-alpha  # 상세 조회
```

### 6. 폐쇄 루프 시나리오 (PoC 검증된 흐름)
```bash
# Plan: 표준 수립
/process-plan CMMI-DEV-ML3

# Do: WI 실행 → REC + MAT-005 §실행기록 자동
/process-do WI-CMMI-04-01-03                       # → REC-CMMI-04-01-03-01-2026-001

# Check: 심사 → NCR + KPI + 차원 4 큐 자동
/process-check start PRO-CMMI-04-01 --auditor "이감사"
/process-check --confirm run-a1c2d3e4              # → REC-AUDIT + NCR 4건 + queue 6건
/process-check --kpi start CMMI-DEV-ML3            # → MAT-008 round 1 (baseline seed)

# Act: 큐 처리 → As-Is 입력 + 차원 1 재트리거 명령
/process-act start queue-qa1b2c3d4 --auto-approve  # → vault/02_표준/.../_inputs/04_AsIs/queue-qa1b2c3d4.md

# Plan' (재실행): 차원 1 재트리거
/process-plan CMMI-DEV-ML3 --from write --target PRO-CMMI-04-01
                                            # → PRO v1.0 → v1.1 (As-Is 자동 read)

# Do (개정판 운영) + Check (NCR 종결 + KPI round 2)
/process-do WI-CMMI-04-01-04                       # → REC-...-2026-003 (CAPA)
/process-check --close-ncr REC-NCR-04-01-2026-001 --capa REC-CMMI-04-01-04-01-2026-003
/process-check --kpi start CMMI-DEV-ML3 --period 2026-04-01..06-30   # → KPI 회복 (verdict critical 4→1)
```

**주의**: `_inputs/` 없이 차원 1 실행 시 LLM 추정 모드로 동작하여 **감사 방어력이 낮습니다**. 프로덕션 용도는 반드시 입력자료를 배치하세요.

## 체크포인트·자가수정 (자동)
각 표준 편입 시 `vault/02_표준/{표준코드}/_state.yaml` 이 자동 생성·갱신됩니다.
- phase 별 `pending → running → done` 이력
- QA Fail 시 `qa_failures[]` 에 담당 에이전트(`assigned_to`)·수정 범위(`fix_scope`) 기록
- 오케스트레이터가 담당 에이전트를 재호출하여 자동 수정 (최대 3회)
- 수동 개입 필요 시 `assigned_to: manual` 로 에스컬레이션

상세 규약: `vault/00_공통관리/06_파이프라인_상태규약.md`

## 문서 유형 8종 (상세: `vault/00_공통관리/01_문서체계.md`)
| 코드 | 유형 | 역할 |
|---|---|---|
| POL | 정책서 | 원칙·방침·책임 |
| PRO | 절차서 | 업무 흐름·관리 절차 |
| WI  | 업무지침서 | 실무 수행 상세 |
| TMP | 템플릿 | 빈 양식 |
| EX  | 작성예시 | 교육용 샘플 |
| REC | 기록본 | 실제 수행 증빙 |
| MAT | 매핑/관리대장 | 추적성·목록·대조표 |
| REF | 참고자료 | 외부 규정·가이드 요약 |

## 파일명 규칙 (상세: `vault/00_공통관리/02_문서번호체계.md`)

POL 번호를 기준으로 하위 문서가 번호를 계승하여 코드만으로 문서 계보를 추적할 수 있다.

```
POL-{영역}-{###}
 └─ PRO-{영역}-{P}{##}                         P = POL 일련번호
      └─ WI-{영역}-{POL###}-{PRO##}-{##}
           ├─ TMP-{영역}-{POL###}-{PRO##}-{WI##}
           ├─ EX-{영역}-{POL###}-{PRO##}-{WI##}
           └─ REC-{영역}-{POL###}-{PRO##}-{WI##}-{YYYY}-{##}
```

예: `POL-QMS-001_품질방침_v1.0.md` → `PRO-QMS-101_품질기획_절차_v1.0.md` → `WI-QMS-001-01-02_문서_검토_및_승인_v1.0.md`

## 통합 MAT 10종 (현 운영, 상세: `vault/00_공통관리/02_문서번호체계.md` §MAT 번호 할당 원칙)

| 번호 | 문서 | 도입 차원 | 역할 |
|---|---|---|---|
| MAT-001 | 문서관리대장 | 1 + 4 (§개정 이력) | 전사 문서 인벤토리 + 차원 4 자동 누적 |
| MAT-002 | 규제요구사항 대조표 | 1 | 법규·표준 조항 매핑 |
| MAT-003 | 산출물 목록표 | 1 | 표준별 산출물 현황 |
| MAT-004 | RACI 통합표 | 1 | 역할·책임 매트릭스 |
| MAT-005 | 심사증적 인덱스 | 1 + 2 (§실행기록) + 3 (§심사이력) | 감사 증빙 인덱스 + 차원 2/3 자동 누적 |
| MAT-006 | 문서 계층 추적 매트릭스 | 1 | POL→PRO→WI→TMP→EX 경로 완결성 |
| MAT-007 | 프로세스 카탈로그 | 2 (Phase 3) | 자연어 → WI 라우팅 인덱스 |
| MAT-008 | KPI 대시보드 | 3 (Phase 3) + 4 (§차원 4 인계) | 표준별 KPI 시계열·회귀 알림 + act queue 인덱스 |
| MAT-009 | NCR 관리대장 | 3 (Phase 2) | NCR 발행/종결 두 섹션 + §통계 자동 |
| MAT-010 | 프로세스 플로우 맵 | 1 Phase 3.5 (flow-mapper 파생) | PRO 간 선후관계 + WI 시퀀스 통합 맵 (Mermaid) |
| MAT-011~ | 표준별 추적성 | 1 | 표준 편입 순서대로 순차 부여 |

## 입력 가능 레퍼런스

**이 플랫폼은 특정 표준에 한정되지 않는다.** `/process-ingest`가 구조화 문서를 파싱할 수 있으면 어떤 레퍼런스든 프로세스 자산의 입력이 된다.

| 유형 | 예시 |
|---|---|
| 국제 표준 | ISO 9001, ISO/IEC 27001, ISO 13485, ISO 26262, IATF 16949, IEC 62304 등 |
| 역량 모델 | CMMI-DEV ML3/ML5, ASPICE, COBIT 등 |
| 국내 표준·법규 | KS, 개인정보보호법, 전자금융감독규정 등 |
| 사내 규정 | 내부 품질 매뉴얼, 경영 방침, IT 보안 정책 등 |
| 고객·계약 요구사항 | SoW, RFP 요건, 고객 심사 체크리스트 등 |
| 산업 가이드라인 | NIST CSF, CIS Controls, OWASP 등 |

`/process-ingest sources/{문서}.pdf --standard {레이블}` 한 줄로 어떤 문서든 편입 가능. `standard-analyzer`가 문서 구조를 파싱하여 REQ-NNN 요건으로 정규화하고, 이후 `process-plan → process-do → process-check` 사이클이 동일하게 작동한다.

복수 레퍼런스를 동시에 편입하면 MAT-002 규제요구사항 대조표가 통합 추적성을 유지한다.

## 권장 Obsidian 플러그인
- Templates (코어) → `vault/99_템플릿/` 지정
- Dataview → MAT-001 문서관리대장 자동 수집
- Graph view → POL-PRO-WI-TMP 연결 시각화
- Mermaid → MAT-008 §시계열 시각화 (차원 3 KPI gantt + Phase 4.5 자동 트렌드 라인/bar/graph TD)

## RBAC (`.claude/rbac/policy.yaml`)

차원 3 Phase 4 부터 RBAC 정책으로 작업 권한을 강제. 6 역할 + Phase 4.5 extensions 4종.

| 역할 | 핵심 권한 | 적용 차원 |
|---|---|---|
| **auditor** | audit.start / confirm / reject-finding (ISO §9.2 독립성 강제 — 자기 업무 심사 불가) | 3 |
| **executor** | do.start / resume (audit / act 쓰기 deny) | 2 |
| **process_owner** | audit.close-ncr / act-queue.dispatch / build-process.start (자기 PRO 한정) | 3, 4, 1 (재실행) |
| **qmr** | audit.* + 모니터링 + RBAC read | 전 차원 |
| **admin** | * (모든 작업, 감사 로그 필수) | 전 차원 |
| **viewer** | *.start / write 모두 deny, 조회 전용 | 전 차원 (read-only) |

Phase 4.5 extensions (명세 활성화):
- `external_idp` — SAML/OIDC 연동 (group → role 매핑)
- `delegation` — 한시 권한 위임 (max 30일)
- `audit_log` — RBAC 거부/허용/위임 5년 보존
- `external_notifications` — 이메일/Slack/Jira 자동 알림 (PCB 회의·NCR·KPI 회귀)

## 폐쇄 루프 PoC 검증 결과

**시나리오**: NCR-001 critical (PRO §5-6 종결 추적 SLA 미정의) → 차원 4 사이클 → 차원 1 재실행 → KPI round 2

| Round | critical | watch | recovering | healthy | data_gap | 합계 |
|---|---|---|---|---|---|---|
| 1 (baseline seed) | 4 | 0 | 0 | 3 | 4 | 11 |
| 2 (PoC 결과) | **1** | 0 | **2** | **6** | **2** | 11 |
| 변화 | -3 | — | +2 | +3 | -2 | — |

단일 차원 4 사이클 (queue-qa1b2c3d4 → run-c4f8a1b2 → PRO v1.0→v1.1 → CAPA REC-003 → NCR-001 close) 로 critical 3건 회복 + data_gap 2건 해소.

상세: `표준_프로세스_심사_가이드.md` §7-C / `표준_프로세스_제개정_가이드.md` §6-A

## 독립 프레임워크 설계 (참고)

현재 Claude Code 하네스로 검증된 개념을 Python 기반 독립 실행 프레임워크로 승격하는 설계안이 `전용AI에이전트_프레임워크_설계안.md` 에 있습니다. Claude Agent SDK + LangGraph 하이브리드 구성을 1순위로 권장하며, 4단계 MVP 로드맵(Phase 1 : CLI 포팅 → Phase 4 : SaaS)이 제시되어 있습니다.

본 README 의 4 차원 자동화 (차원 2~4) 및 Phase 5 (외부 시스템 연동 — Redmine 구현 완료) 까지 포함한 전체 플랫폼을 독립 제품화 검토 단계. Phase 6 이상 (Notion/Codebeamer 연동, AI Agent Gateway) 실 구현 시 독립 패키지 분리 예정.

## 누적 통계 (main 기준)

- **에이전트**: 29 (차원별 1/6/5+2/9+3/4)
- **슬래시 커맨드**: 7 (`/process-ingest`, `/process-plan`, `/process-do`, `/process-backfill`, `/process-check`, `/process-audit`, `/process-act`)
- **통합 스킬**: 2 (`/vault-push`, `/workspace-create`) — Phase 5 Redmine 연동
- **운영 MAT**: 10 슬롯 (MAT-001~009 + MAT-010 프로세스 플로우맵)
- **PoC trace**: 10 (do 5, audit 1, kpi 2, act 2)
- **act queue**: 6 (3 done — 1 단일 + 2 batch / 3 pending)
- **가이드 문서**: 4 (빌드 / 실행 / 심사 / 제·개정)
- **Phase 4.5 명세**: 3 utils (영업일 / PCB quorum / 자동 트렌드) + RBAC extensions 4종
- **Phase 5 구현**: publish/redmine/ (11 파일) + .github/workflows/vault-push.yml + 2 스킬
