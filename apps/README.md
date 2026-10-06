# 웹 플랫폼

여러 회사·여러 조직의 프로세스 자산을 한곳에서 관리하는 웹 애플리케이션.
CLI 하네스(`.claude/`, `vault/`)에서 검증한 개념을 다중 사용자 시스템으로 옮긴다.

| 경로 | 내용 |
|---|---|
| `apps/api/` | FastAPI + SQLAlchemy + Postgres. 업무 규칙, 권한, 회사 간 격리 |
| `apps/web/` | Next.js(App Router) + Tailwind + shadcn/ui. 반응형 웹, PWA |
| `seed/` | 플랫폼 참조 데이터: 문서 유형과 섹션 구성, 영역코드, 표준 분류 |
| `docker-compose.yml` | 로컬 인프라(Postgres, MinIO)와 전체 실행 구성 |

## 실행

```bash
# 1. 인프라 (Postgres 는 호스트 55432 포트)
docker compose up -d

# 2. API
cd apps/api
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # macOS·Linux: .venv/bin/python
cp .env.example .env
.venv/Scripts/python -m app.cli migrate              # 스키마
.venv/Scripts/python -m app.cli seed                 # 참조 데이터
.venv/Scripts/python -m app.cli demo                 # 데모 회사 (선택)
.venv/Scripts/python -m uvicorn app.main:app --port 58000

# 3. 웹
cd apps/web
pnpm install
pnpm dev                                             # http://localhost:3000
```

요건 도출과 문서 생성을 쓰려면 `apps/api/.env` 에 `PM_ANTHROPIC_API_KEY` 를 넣는다.
IEC 62304(82쪽) 기준으로 요건 도출은 약 2분·1달러, 문서 71건 전체 생성은 약 15분·6달러였다.

로그인은 이메일 링크 방식이고 가입은 없다. 등록된 사용자만 들어올 수 있다.
`PM_AUTH_DEV_ECHO=true` 면 메일 대신 화면에 "바로 로그인" 버튼이 나온다.

- 데모 사용자: `admin@example.com`(플랫폼 관리자), `owner@example.com`(프로세스 오너),
  `qmr@example.com`(품질 책임자), `member@example.com`(일반 구성원)
- 새 사용자: `python -m app.cli create-user EMAIL 이름 --platform-role consultant`

전체를 컨테이너로 띄우려면 `docker compose --profile full up -d --build` (웹 3000, API 58000).

> Windows 에서 `uvicorn --reload` 는 재시작에 실패한 채 예전 코드로 계속 응답하는 경우가 있었다.
> API 코드를 바꾼 뒤에는 서버를 직접 껐다 켜는 편이 안전하다.

## 검증

```bash
cd apps/api && .venv/Scripts/python -m pytest        # Postgres 필요 (임시 DB 를 만들어 쓴다)
cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
cd apps/web && pnpm lint && pnpm typecheck
cd apps/web && pnpm exec playwright test             # API·웹이 떠 있고 데모 회사가 있어야 한다
```

API 의 요청·응답 형식을 바꾸면 웹의 타입을 다시 만든다.

```bash
cd apps/api && .venv/Scripts/python -m app.cli openapi --out ../web/openapi.json
cd apps/web && pnpm gen:api
```

## 구조에서 알아둘 것

- **회사 간 격리는 DB 가 한다.** 회사 데이터 테이블에는 모두 `tenant_id` 가 있고 Postgres 행 수준
  보안으로 막는다. API 는 슈퍼유저가 아닌 역할(`pm_app`)로 접속하고, 요청마다
  `app/deps.py` 의 `tenant_context` 가 회사를 지정한다. 새 테이블을 만들면 마이그레이션에서
  정책을 함께 추가한다(`migrations/versions/0002_tenant_isolation.py` 참고).
- **문서 번호는 서버가 발급한다.** 형식 규칙은 `app/domain/doc_ids.py`, 발급은
  `app/services/numbering.py`. 번호는 체계의 상속 계보 안에서 유일하다.
- **승인된 개정판은 바뀌지 않는다.** DB 트리거가 막는다. 바꾸려면 새 개정판을 만든다.
- **감사 기록은 추가만 된다.** 회사별로 앞 기록의 지문을 이어 붙여 변조를 탐지한다.
- **커밋은 응답 전에 한다.** `app/db.py` 의 `CommitRoute` 가 요청 처리 직후 커밋한다.
  새 라우터는 `route_class=CommitRoute` 로 만든다.
- **권한은 한 함수로 판단한다.** `app/domain/permissions.py` 의 `can()`. 화면은 API 가 내려주는
  `actions` 목록으로 버튼을 정하고, 스스로 권한을 계산하지 않는다.
- **회사는 보관한 뒤에만 지울 수 있다.** 보관(회사 관리자)은 읽기 전용으로 만들 뿐 되돌릴 수 있고,
  완전 삭제(플랫폼 관리자)는 DB 함수 `purge_tenant()` 로만 한다. 감사 기록까지 지워지므로
  지웠다는 사실은 `deleted_tenant` 에 남는다. 테스트로 만든 회사는
  `python -m app.cli purge-tenant SLUG --actor EMAIL --yes` 로 정리한다.
- **요건의 근거는 코드가 확인한다.** 모델은 원문을 그대로 옮겨 적고(`quote`), 그 문장이 실제로
  조항에 있는지는 `app/pipelines/mining.py` 의 `verify` 가 대조한다. 대조되지 않은 요건은 확정할 수 없다.
- **문서 생성에는 근거 게이트가 있다.** `app/pipelines/planning.py` 의 `check_written` 이 통과시킨
  본문만 저장된다: 섹션이 그 문서에 배정된 요건을 근거로 댔는지, 배정된 요건이 모두 쓰였는지.
  섹션별 근거는 `document_requirement` 에 남고, 문서 화면에서 원문 인용과 함께 볼 수 있다.
- **여러 표준을 한 체계로 통합할 수 있다.** 설계안 하나가 원문 여럿을 근거로 삼는다(`plan_source`).
  설계안 안에서 요건은 `원문약칭 번호`(예: `IEC62304 5.1.1-01`)로 부르고, 문서는 표준이 아니라
  업무 기준으로 나눠 같은 활동에 관한 요건을 표준이 달라도 한 문서에 배정한다. 표준 사이의 대응은
  따로 저장하지 않는다. 같은 문서에 배정됐다는 사실이 곧 대응이고, 사람이 설계안에서 확인한다.
- **초안은 사람이 기준으로 만든다.** 표준이 값을 정하지 않은 곳은 본문에 `〔조직 결정: …〕` 으로
  남는다. 이 표시가 남은 개정판은 검토를 요청할 수 없고(`app/domain/revisions.py`), 체계별로 모아
  채우면 누가 무엇을 정했는지 개정판(`structured.decisions`)과 감사 기록에 남는다. 여러 건을 한 번에
  검토 요청·승인할 수 있지만(`/review-batch`) 규칙은 건마다 따로 판단한다. 설계안은 문서를 생성하기
  전까지 사람이 고칠 수 있다(이름, 구성, 요건 배정).
- **하위 체계는 상위 체계의 문서를 물려받는다.** 문서마다 상속(그대로)·재정의(이 체계의 문서로
  대체)·제외(사유 필수)·추가 가운데 하나다. 한 체계에서 실제로 쓰이는 문서는
  `app/services/tailoring.py` 의 `effective_documents` 한 곳에서 계산하고, 문서 목록과 커버리지가
  이것을 쓴다. 재정의는 상위 승인판을 복사한 초안에서 시작해 자기 개정 이력을 갖고, 상위 문서가
  그 뒤 개정되면 "상위 변경됨"으로 표시된다. 상속 문서는 상위 개정을 그대로 따라간다.
- **커버리지는 저장하지 않고 센다.** 표준의 요건이 어느 문서에서 이행되는지는 문서 섹션의 근거
  링크(`document_requirement`)에서 그때그때 계산한다(`app/services/coverage.py`). 승인된 판이
  인용하면 이행, 승인 전 판만 인용하면 초안, 인용한 문서가 없으면 미이행이다.
- **오래 걸리는 일은 작업(run)으로 돈다.** 대기열은 DB 의 `run` 테이블이고 작업자는
  `app/worker.py` 다. 기본은 API 프로세스 안의 스레드이며(`PM_RUN_WORKER_IN_API`), 따로 띄우려면
  `python -m app.worker`. 요건 도출과 문서 생성은 실패한 부분만 다시 돌릴 수 있다.
- **모델 호출은 한곳에서 한다.** `app/llm.py` 의 `structured()`. 모델은 `PM_LLM_MODEL` 로 바꾼다.
- **원문 파일은 회사별로 보관한다.** 지금은 `var/storage/{회사 id}/`(git 제외). 표준 원문은
  저작권이 있으므로 회사 사이에 공유하지 않는다.
- **문서 유형과 섹션 구성은 데이터다.** `seed/doc_types.yaml` 을 고치고 `seed` 를 다시 실행한다.

## 진행 상황

- [x] Phase 0 — 기반: 회사·조직·체계, 로그인, 역할, 참조 데이터, 화면 셸
- [x] S1 — 자산: 문서 계층과 번호, 작성·검토·승인, 개정과 변경 비교, 감사 기록
- [x] S2 — 구축: 원문 업로드 → 조항 분석 → 요건 도출·확정 → 적용요건 승인 → 구조 설계 → 문서 생성
  - 여러 표준 통합 설계(예: IEC 62304 + IEC 81001-5-1)와 표준 간 요건 대응 확인 포함
  - 초안 정리 포함: 조직이 정할 항목 모아 채우기, 여러 건 검토 요청·승인, 설계안 직접 편집
  - 남은 것: PDF 외 형식(DOCX·HWPX)과 스캔 문서, 번호 체계가 없는 문서,
    이미 만든 체계에 표준 추가, 조항 번호가 없는 표준(ASPICE 등)
- [x] S3 — 테일러링: 하위 체계의 상속·재정의·제외·추가, 상위 변경 표시와 비교
  - 남은 것: 승인된 재정의를 상속으로 되돌리기, 섹션 단위 재정의, 매개변수(역할명·기한만 다른 경우),
    하위 체계만의 요건 제외
- [ ] S4 — 정합화: 기존 산출물을 표준 양식의 기록으로
- [ ] S5 — 심사 뷰: 조항별 증적 묶음과 내보내기
  - 먼저 된 것: 표준별 커버리지(요건 → 이행 문서, 이행·초안·미이행·제외)와 CSV 내려받기
  - 남은 것: 기록(증적)까지 이어지는 묶음, 기간·조직 선택, XLSX·PDF
