# TASK — yt-trend-radar

> SPEC v1.0 (2026-07-30 확정) / PLAN v0.1 (초안) 기준. PLAN 확정 후 P0 착수.
> **Phase 완료마다 `python tools/gen_progress.py` 실행 → 진행 대시보드 아티팩트 갱신·게시** (SDD 규칙 4).

## P0. 스캐폴딩
- [x] 저장소 구조 생성 (collector/, config/, db/, tools/)
- [x] collector `.venv` 생성 + 의존성 고정 (requirements.txt — 순수 파이썬만)
- [x] `.env.example` 작성, `.gitignore`에 `.env` 확인
- [x] Supabase 스키마 마이그레이션 적용 (001_init 27문장 + 002_grants 5문장)
- [x] `ytr_` 접두어 정책 확립 (공유 프로젝트 — 기존 67 테이블과 충돌 방지) + 강제 테스트
- [x] RLS·권한 검증 13/13 PASS (`tools/verify_rls.py`)
- [x] `config/categories.yaml` — 5개 대분류 × 국내/해외 + 키워드
- [x] `core.config` / `core.models` / `core.db` (harness + PostgREST) 구현
- [x] 테스트 게이트 분리: 기본 18 passed (외부 호출 0) / `-m live` 4 passed
- [x] `jobs/sync_config` 로 카테고리·지역 DB 반영 확인
- [x] `config/seeds.yaml` — **실제 채널 90개**(6카테고리 × 15, 중복 0), ID 형식 위반 0건
- [x] 시드 편향 수정 — 구독자 층화 추출 + 롱테일 질의 + 인기영상 경로 (10만 이하 8개 → **56개(62%)**)
- [x] 카테고리 추가: **바이브코딩·AI** (`aicoding`) — YAML 만으로 추가, tech 키워드 이관
- [x] 한국어 필터 (`looks_korean`) — aicoding 후보 196개 중 비한국어 73개 제외
- [x] `--only` 옵션 — 카테고리 추가 시 전체 쿼터 재소모 없이 부분 재발굴(700u)
- [x] YouTube Data API 키 발급 + 라이브 검증 (키 제한: YouTube Data API v3 전용)
- [x] `docs/DESIGN.md` 작성 (내부 도구 파트) + 팔레트 검증 기록·탈락안 2건
- [x] `tools/gen_seeds_review.py` — 시드 검토 페이지 (링크·필터·검색, 라이트/다크)
- [ ] Supabase CA 인증서 내려받아 `--ca` 로 마이그레이션 검증 전환 (현재 `--insecure`)
- [ ] 🔴 `SUPABASE_SERVICE_ROLE_KEY` 재발급 (채팅 노출분 무효화)

## P1. Core 수집기 (TDD)
- [x] tests: yt_client harness 모드 (fixtures 응답 3영상/2채널)
- [x] tests: rss_watcher (fixture XML 파싱 + UC 접두어 quirk 회귀)
- [x] tests: 스냅샷 저장 / 30일 purge / naive datetime 거부
- [x] tests: 쿼터 원장 (배치 50, search 100u, 예산 초과 차단)
- [x] 구현: `core.models`, `core.quota`, `core.db`(업서트·스냅샷·purge)
- [x] 구현: `sources.yt_client` (harness/live), `sources.rss_watcher` (harness/live)
- [x] 구현: `jobs/purge` (RETENTION_DAYS, --dry-run)
- [x] live 테스트 분리 확인 — 기본 **73 passed / 외부 호출 0 (0.47초)**, `-m live` **9 passed**
- [x] 실측 버그 1건 수정: RSS 루트 `yt:channelId` 의 `UC` 접두어 누락 → entry·링크에서 복원

## P2. 지수 엔진 (TDD)
- [x] tests: 정규화 velocity 산식 41건 — α/floor, 실측 Δt, 결측·역행·0분모 방어
- [x] tests: 4종 랭킹 — 정렬·순위·표시필드·나이상한·카테고리 필터·결정적 동점처리
- [x] tests: 벌크 조회 + 게시 경로 13건 (원자적 교체, JSON 직렬화)
- [x] 구현: `engine/trend_engine` — ScoreConfig(frozen) + 4보드 + `build_boards`
- [x] 구현: `core.db` 벌크 조회 (`fetch_all_channels` / `*_since`, PostgREST 페이징)
- [x] 구현: `jobs/compute` — 산출 → `ytr_trend_scores` 원자적 교체
- [x] **α 교정** — 시연에서 α=0.7 rising 이 구독자 내림차순이 되는 결함 발견 → **α=1.0**
      (`score ∝ 구독자^(1-α)`, α=1 에서만 규모 중립). 회귀 테스트로 고정
- [x] **PostgREST 타임스탬프 인코딩 버그 수정** — ISO 의 `+00:00` 이 쿼리에서 공백으로
      해석돼 400. **purge 도 같은 경로**라 ToS 삭제가 실패할 수 있었다 (`encode_ts`)
- [x] 안전 규약: 스냅샷 0건이면 **기존 랭킹을 지우지 않고 종료** (빈 보드 서빙 방지)
- [ ] 콜드스타트 실데이터로 α·window 재조정 (P4 가동 후)
- [ ] Shorts/롱폼 보드 분리 여부 결정 — 실데이터 필요 (현재 혼재, `is_short` 는 수집됨)

## P3. 분류·발굴 (TDD)
- [x] tests: search 예산 가드 (유닛 상한 + 호출 횟수 예산, 차단 시 미소모)
- [x] tests: 층화 추출 로직 9건 (구간 판정·쿼터·보충·중복제거)
- [x] 구현: `yt_client.search_channels` / `search_channels_via_videos` + `jobs/bootstrap_seeds`
- [x] tests: classifier 키워드 규칙 32건 (한 글자 경계·exclude·가중치·채널 판정·실측 회귀)
- [x] 구현: `engine/classifier` — 키워드 매칭 + 채널 단위 판정(`ChannelVerdict`)
- [x] 구현: `tools/verify_seeds.py` — RSS 실검증 (**쿼터 0**), 판정 JSON 산출
- [x] 키워드 결함 2건 수정 — tech 의 일반어(`리뷰`·`언박싱`) 제거, food 에 구체 음식명 보강
      → 정당한 채널 구제: 득템 27%→60%, cho.eat 20%→53%
- [x] **탈락 39건 검토 완료** — 진짜 노이즈 vs 키워드 부족 구분, 근거 제목 전수 확인
- [x] **분류기 회귀 수정** — food 키워드 보강 부작용으로 캠핑·육아·여행 채널을 food 가 흡수했다.
      점수에 `MAX_COUNTED_HITS=3` 상한 도입 (키워드 수 많은 카테고리의 무조건 승리 방지)
- [x] fitness 키워드 보강 — 산행·명산·완등·암릉·트레킹 + 영어 용어 + 주요 명산 19개
      (등산 채널은 '등산'이 아니라 '지리산 암릉 코스'라고 쓴다)
- [x] travel/vlog 키워드 보강 — 차박·캠핑장·여행지·휴가 / 삼시세끼·출근·워킹맘 등
- [x] `jobs/refill_seeds.py` — 탈락분 교체. **RSS 검증 통과분만 채택**, 결손 해소 시 검색 조기 중단
- [x] 시드 보충 1차 — 83개 전부 **RSS 검증 통과 (83/83, 탈락 0)**
- [x] **시드 보충 완료 (2026-08-03)** — **6개 카테고리 × 15개 = 90개**, RSS 검증 86/90 통과
- [x] `--fill-any-tier` 옵션 — 대형(100만+) 후보가 고갈된 카테고리에서 15개 달성을 우선
      (해당 규모의 한국 채널 수는 유한하므로 티어 목표에 매달리면 영원히 못 채운다)
- [ ] 적중률 미달 4건 판단 — UNDERkg 27% · 테크노사우루스 27% · 미드나잇로그 27% · 자취남 20%.
      **모두 카테고리는 맞고 적중률만 낮다** (오분류 아님) → 임계값 조정 vs 키워드 보강 vs 유지
- [ ] 기업·기관 채널 처리 방침 — CU 씨유튜브·KNN NEWS·한국관광공사TV 는 '유튜버'가 아니다
- [ ] 구현: sources/discover (증분 발굴)
- [ ] 수동 오버라이드 경로 (`category_override` 컬럼 활용)
- [ ] **채널 1개 = 카테고리 1개 결정 규칙** — 시드 발굴에서 3개 채널이 travel/vlog 양쪽에 잡혔다. DB 는 `category_id` 단일 컬럼이므로 우선순위 규칙 필요(가중치·영상 다수결)
- [ ] **인기영상 경로 노이즈 교정** — 대형 예능·뉴스 채널이 아무 질의에나 걸린다: travel 에 ILLIT(591만)·뜬뜬(330만), vlog 에 KNN NEWS(128만), fitness 에 한국관광공사TV, food 에 다람냥(슬라임). 영상 제목·태그 기반 재분류 필요
- [x] **비한국어 채널 배제** — `looks_korean()` (country=KR OR 한글) 구현·테스트 5건. 실측: aicoding 73개 제외, 나머지 카테고리는 ShortCircuit 1건뿐
- [ ] tech 시드의 ShortCircuit(영어권) 수동 제거 또는 tech 부분 재발굴(700u)
- [ ] 분류 정확도 수동 스팟체크 30건

## P4. 파이프라인 통합
- [x] `jobs/collect` 통합 (채널배치 → RSS 감지 → 영상배치 → 분류 → 스냅샷 → 쿼터기록)
- [x] tests: 수집 규약 18건 — 추적창·재스냅샷 누적·분류 폴백·쿼터 소진 시 부분저장
- [x] `ytr_quota_usage` 적재 (`record_quota_usage`, 덮어쓰기 아닌 **합산**) — P2 에서 겪은
      "원장이 프로세스마다 0에서 시작" 문제의 해결. 실측 확인: `오늘 쿼터 12/9500u`
- [x] **첫 실수집 성공 (2026-08-03)** — 채널 90 · 영상 479 · **쿼터 12u**
- [x] GitHub Actions `collect.yml` (cron 3회/일 + workflow_dispatch, concurrency 잠금)
- [x] **유지보수 스텝 이어붙이기** — collect → compute → verify_seeds → 리포트 → 커밋
- [x] 검증·리포트 스텝 `continue-on-error`, compute 도 (콜드스타트 0행은 장애가 아님)
- [x] 리포트 산출물: **저장소 커밋** (`docs/*.html`, `[skip ci]`)
- [x] 12시간 무수집 알림 — `tools/check_freshness.py` + **독립 워크플로 `health.yml`**
      (수집 워크플로 안에 두면 cron 이 통째로 멈췄을 때 알림도 함께 죽는다)
- [x] **배포 전 보안 검토 (2026-08-03)** — 아래 §보안 검토 기록 참조. 결과: **조건부 통과**
- [x] git 저장소 초기화 + 최초 커밋 (로컬) — 68파일, `.env` 스테이징 제외 실증, 이력 시크릿 0건
- [x] `.gitattributes` — CI(Linux)/개발(Windows) 줄바꿈 통일
- [x] **전용 Secret key 전환 (2026-08-03)** — 공유 프로젝트라 레거시 `service_role` Reset 은
      다른 앱을 끊는다. `sb_secret_*` 전용 키를 발급해 이 앱만 교체. 검증: check_env HTTP 200,
      RLS **13/13 PASS**, compute 읽기·게시 180행 정상
- [x] **지수 설정 단일화** — 엔진이 α 를 하드코딩하고 `.env` 에도 별도 값(0.35/0.75)이 있어
      `.env` 쪽이 **죽은 설정**이었다. 게다가 그 값이 α≥1.0 규약을 위반해, 연결하는 순간
      '신규 뜨는' 보드가 조용히 구독자 순으로 되돌아갈 상태였다.
      → `configs_from(TrendParams)` 로 일원화 + `ScoreConfig.kind` 도입 + **α<1 은 생성 시 예외**
- [ ] 레거시 `service_role` 키 정리 — 다른 앱들도 전용 키로 옮긴 뒤 일괄 폐기 (별도 작업)
- [ ] GitHub 저장소 생성 + Secrets 등록 (YT_API_KEY / SUPABASE_URL / SUPABASE_SERVICE_KEY)
- [ ] 저장소 공개 범위 결정 (private 권장 — 공개 시 시드 목록·질의가 그대로 노출)
- [ ] Actions 3일 연속 무인 성공 → **콜드스타트 시작일: 2026-08-03 (로컬 1회차 완료)**

## P7. 운영·유지보수 (FR-9)
- [x] `tools/_theme.py` — 내부 도구 공통 토큰 (3개 생성기의 중복 정의 제거)
- [x] `tools/gen_admin.py` — 운영 콘솔: 상태 타일·자동 점검 7종·카테고리 현황·런북 6단계
- [x] 자동 점검 구현 — 시드 공백/검증 노후/통과율 저조/무수집 12h/보관정책 위반/랭킹 공백/쿼터 80%
- [x] DB 장애 내성 확인 (`--offline`, 조회 실패 시 해당 항목만 '조회 불가')
- [x] `gen_progress.py`·`gen_seeds_review.py` 를 `_theme.py` 로 이관 — 세 페이지의 색 토큰이
      **완전히 동일**함을 해시로 검증(24개 토큰 일치). 레이아웃 CSS 는 페이지마다 형태가 달라
      각자 유지한다(진행 920px, 콘솔·검토 1040px) — 색만 단일 정의점으로 모았다
- [x] 운영 콘솔 확장 — **콜드스타트 진행률**(경과/14일 + 공개 목표일), **최근 수집 회차**(시각·건수),
      **보드 충전 상태**(카테고리 × 6종 보드 교차표)
- [x] **알림 연동** — 콘솔의 점검 로직을 그대로 쓴다(`gen_admin.py --strict`, 심각 항목 시 exit 1).
      `health.yml` 에 연결 → 워크플로 실패 → GitHub 메일.
      *콘솔이 심각을 띄워도 누군가 페이지를 열어야만 안다면 감시가 아니다.*
      점검 정의를 두 벌 만들지 않아 어긋날 여지가 없다
- [x] 카테고리 추가 런북 — **실주행됨**. aicoding 추가 때 6단계를 전부 실제로 거쳤다
      (YAML 추가 → `--only` 발굴 700u → sync_config → RSS 검증 → 리포트 → purge).
      별도 리허설을 다시 하지 않는 이유: 같은 경로를 한 번 더 도는 데 700u 가 든다
- [ ] (보류) 버튼 실행형 admin — 인증·감사로그·workflow_dispatch. 배포(P6) 이후 별도 Phase

## P5. 웹 프론트 (DESIGN 선행)
- [x] **docs/DESIGN.md §1~§5** — 토큰·티어 램프·마크 규격·상호작용·접근성 (내부 도구 파트)
- [x] validate_palette.js 라이트/다크 ALL PASS + 탈락안 2건 실측 기록
- [x] **docs/DESIGN.md §6 서비스 UI 확정** — 정보구조·형식분리·점수표현·색·타이포·그래프·문구·ToS
- [x] **롱폼/Shorts 보드 분리** — 실측 근거(추적 영상 63%가 Shorts, 보드의 67% 차지).
      `004_board_format.sql` + 엔진 `video_format` + 테스트 5건. 산출 180→**496행**
- [x] Next.js 셋업 (포터블 Node 22 + Next 15.5.22 + TS 5.9.3) — 빌드·타입체크 통과
- [x] 홈: 카테고리 칩 + 형식 토글 + 4개 보드 (실데이터 렌더 확인)
- [x] 채널 상세: 구독자·조회수 **별도** 추이 차트(이중축 금지) + 급상승 영상
- [x] 개인정보처리방침 페이지 (ToS·공개 서비스 요건)
- [x] 라이트/다크 토큰, YouTube 링크·자체 지표 고지
- [x] 접근성 체크리스트 (DESIGN §6.10) — 앵커 중첩 제거, alt 규칙 수정
- [x] **웹 의존성 취약점 3건 상향** — next 15.5.4→15.5.22(CVE-2025-66478),
      sharp 0.34.5→0.35.3, postcss→8.5.25. `npm audit` **0건**
- [ ] Vercel 배포 (P6 보안 검토 후)
- [ ] OG 이미지·사이트맵·robots
- [ ] 실제 화면 눈으로 검수 (`cd web && npm run dev`)

## P6. 콜드스타트·배포
- [x] **배포 전 보안 검토 2차 (2026-08-03, 웹 표면 포함)** — §보안 검토 기록 참조
- [x] **anon 키 클라이언트 유출 검사** — 빌드 산출물 `.next/static` 전수 grep, **0건**
      (`NEXT_PUBLIC_` 접두어를 쓰지 않아 서버 전용으로 격리됨)
- [x] `robots.ts` / `sitemap.ts` — **콜드스타트 중 색인 차단이 기본값**.
      얇은 보드가 검색 첫인상이 되면 이후 개선돼도 평가가 따라오지 않는다.
      `SITE_PUBLIC=true` 로 전환 (코드 변경 아님). 양쪽 모드 실동작 검증
- [x] OG/Twitter 메타 + `metadataBase`
- [x] 개인정보처리방침에 **제3자 요청 명시** — YouTube(썸네일)·jsDelivr(서체)·Vercel(호스팅).
      "제3자 제공 없음"만 적어두면 실제와 어긋난다
- [ ] **2주 데이터 축적** — 수집 시작 2026-08-03 → 목표 **2026-08-17**
      (현재 3회차, 약 3시간분. 이 항목이 공개 전환의 전제다)
- [ ] 개인정보처리방침 페이지
- [ ] **보안 검토 게이트** (CLAUDE.md §Security Review — 키·클라이언트 노출·PII·의존성·엔드포인트·API 예의) → 결과 보고
- [ ] Vercel 배포 + 배포 후 스모크
- [ ] 완료 일시 기록

## 보안 검토 기록 (2026-08-03, 원격 push 전)

워크스페이스 CLAUDE.md §Security Review 절차. 결과 **조건부 통과** — 키 재발급 1건이 잔여.

| 항목 | 결과 | 근거 |
|------|------|------|
| **인증키·시크릿** | ✅ | 커밋 대상 68파일 전수 스캔 — Google API key/JWT/postgres URL 패턴 **0건**. `.env`는 `.gitignore` 규칙 존재 + **실제 스테이징 제외를 실증**. `.env.example` 실값 없음 |
| **커밋 이력** | ✅ | 신규 저장소라 오염 이력 자체가 없음. `git log -p --all` 재검사 0건 |
| **클라이언트 노출** | ✅ | 현재 브라우저로 나가는 코드 없음(P5 예정). 산출물 `docs/*.html` 스캔 시크릿 0건. 설계상 웹은 **anon key + RLS 읽기 전용**만 사용 |
| **PII** | ✅ | 공개 채널 메타·공개 영상 통계만 수집. 시청자 개인정보·계정·로그인 없음 |
| **의존성** | ✅ (조치함) | pip-audit **취약점 3건 발견** → 전부 상향: requests 2.32.4→2.33.0, python-dotenv 1.1.0→1.2.2, pytest 8.4.1→9.0.3. 재감사 0건, 테스트 234 통과 |
| **엔드포인트·권한** | ✅ | `verify_rls.py` **13/13 PASS** — anon SELECT 7테이블 허용, anon INSERT/UPDATE/DELETE 401 차단, `ytr_quota_usage` 비노출, service 키만 쓰기 |
| **공공 API 예의** | ✅ | YouTube API 하루 **36u / 9,500u (0.4%)**. RSS 폴링 하루 3회 · 요청 간 0.25초. 검증 스크립트 0.3초 |
| **저장소 식별자** | ✅ | Supabase 프로젝트 ref 가 커밋 대상 파일에 없음 (PLAN.md 는 리전 풀러 호스트명만 언급) |

### 2차 검토 (2026-08-03, P5 웹 표면 추가 후)

| 항목 | 결과 | 근거 |
|------|------|------|
| **클라이언트 번들 유출** | ✅ | 빌드 산출물 `.next/static` 에서 anon 키·Supabase URL **0건**. `NEXT_PUBLIC_` 을 쓰지 않아 서버 전용으로 격리 |
| **웹 의존성** | ✅ (조치함) | 취약점 3건 발견·상향 — next 15.5.4→15.5.22(CVE-2025-66478), sharp→0.35.3(libvips CVE), postcss→8.5.25(XSS·경로순회). `npm audit` 운영·개발 **모두 0건** |
| **파이썬 의존성** | ✅ | pip-audit 0건 |
| **RLS·권한** | ✅ | 13/13 PASS (재검증) |
| **시크릿 스캔** | ✅ | 커밋 대상 93파일 0건, `.env`·`web/.env.local` 스테이징 제외 실증 |
| **제3자 리소스** | ✅ (문서화) | YouTube·jsDelivr·Vercel 3곳. 개인정보처리방침에 명시. 추적 식별자 없음 |
| **색인 제어** | ✅ | 콜드스타트 중 `noindex` 가 **기본값**, 양쪽 모드 실동작 검증 |

**미해결 위험 없음.** 잔여는 아래 사용자 조치 1건과 축적 대기뿐이다.

### 🔴 잔여 조치 (사용자)

**service_role 키 재발급** — 이 대화에 값이 노출된 이력이 있다. 유출된 키를 그대로 CI Secrets 에
등록하면 검토의 의미가 없으므로, **재발급 전에는 원격 push 를 진행하지 않는다.**
절차: Supabase → Settings → API Keys → service_role → Reset → `.env` 갱신 → `tools/check_env.py` 확인.

## 완료 기록
| Phase | 완료 일시 |
|-------|-----------|
| P0 | 진행 중 — 코드/DB 완료, 사용자 대기 4건 |
| P1 | 2026-07-30 |
| P2 | |
| P3 | |
| P4 | |
| P5 | |
| P6 | |
| P7 | 2026-08-03 — 콘솔·런북·알림·테마 통일 완료 (버튼 실행형 admin 은 배포 후 별도 Phase) |
