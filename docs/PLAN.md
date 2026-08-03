# PLAN — yt-trend-radar

> **상태: 확정 (v1.0, 2026-07-30) — SPEC v1.0 기반. P-D1~P-D3 결정 완료 (§7).**
> 방법론: SDD + TDD (Red→Green→Refactor) + Harness Engineering (Core 우선, 외부 의존성 mock 기본)

## 1. 아키텍처

```
┌─────────────── 수집 (GitHub Actions cron, 하루 3회) ───────────────┐
│                                                                    │
│  rss_watcher ──→ 새 영상 감지 (쿼터 0)                              │
│  yt_client   ──→ videos.list / channels.list 스냅샷 (배치 50)      │
│  discover    ──→ search.list 예산제 발굴 (초기 2주 집중)            │
│  classifier  ──→ 키워드 규칙 기반 카테고리 매핑                     │
│       │                                                            │
│       ▼                                                            │
│  Supabase (Postgres) ← trend_engine이 스냅샷 → trend_scores 산출   │
│  (30일 롤링 삭제: purge 잡)                                        │
└────────────────────────────────────────────────────────────────────┘
                                │ read-only (trend_scores, channels)
                                ▼
┌─────────────── 서빙 (Vercel) ──────────────────────────────────────┐
│  Next.js App Router — 홈(카테고리 → 4개 랭킹 보드), 채널 상세       │
│  API 키 없음. Supabase anon key(RLS read-only)만 사용               │
└────────────────────────────────────────────────────────────────────┘
```

### 모듈 의존관계 (Core → 바깥)

```
core/models, core/db  ←─ trend_engine ←─ jobs/compute
        ↑                   ↑
   yt_client (harness/live) │
        ↑                   │
   rss_watcher, discover, classifier ←─ jobs/collect
                                          ↑
                              GitHub Actions (cron 진입점)
web/ 은 core와 독립 — DB 스키마(trend_scores)만 계약으로 공유
```

- **Harness 모드**: `yt_client`는 `YT_MODE=harness`(기본)면 `tests/fixtures/`의 저장된 API 응답을 반환. 실 API 호출 테스트는 `@pytest.mark.live`로 격리.
- RSS도 동일 — fixture XML로 테스트, live는 마커.

## 2. 저장소 구조

```
yt-trend-radar/
├── docs/                  # SPEC, PLAN, DESIGN, TASK
├── collector/             # Python 수집기 (자체 .venv)
│   ├── core/              #   models, db, config
│   ├── sources/           #   yt_client, rss_watcher, discover
│   ├── engine/            #   trend_engine, classifier
│   ├── jobs/              #   collect.py, compute.py, purge.py (cron 진입점)
│   └── tests/             #   fixtures/ + test_{module}_{scenario}
├── web/                   # Next.js (포터블 Node 22 + TS5 — 워크스페이스 메모리)
├── config/
│   ├── categories.yaml    # 카테고리 정의 + 매핑 키워드 (확장형 체계의 진실)
│   └── seeds.yaml         # 수동 시드 채널 목록
├── db/migrations/         # 001_init.sql, 002_grants.sql (멱등 — 재실행 안전)
├── tools/
│   ├── _theme.py          # 내부 도구 공통 디자인 토큰 (근거는 docs/DESIGN.md)
│   ├── gen_admin.py       # 운영 콘솔 — 상황판 + 런북 (FR-9)
│   ├── gen_seeds_review.py# 시드 검토 페이지 (링크·필터·RSS 판정)
│   ├── gen_progress.py    # TASK.md → 진행 대시보드 (Phase 완료마다 실행·게시)
│   ├── verify_seeds.py    # RSS 실검증 (쿼터 0) → seeds_verdicts.json
│   ├── apply_migrations.py# psql 없이 pg8000 으로 DDL 적용
│   ├── check_env.py       # 연결 점검 (시크릿 비노출)
│   └── verify_rls.py      # RLS·권한 13항목 검증 (배포 전 게이트)
└── .github/workflows/     # collect.yml (cron), 별도 purge 스텝 포함
```

## 3. 데이터 모델 (상세)

> ⚠️ **이 Supabase 프로젝트는 다른 앱들과 공유된다** (public 스키마에 기존 67개 테이블 — `trend_data`,
> `trending_discoveries` 등 이름 충돌 위험 실존). 따라서 **모든 객체에 `ytr_` 접두어**를 쓴다.
> 접두어는 `collector/core/db.py`의 `TABLES` 한 곳에서만 정의하며, 테스트가 이를 강제한다
> (`test_db_tables_all_use_ytr_prefix`).

| 테이블 | 주요 컬럼 | 롤링 |
|--------|-----------|------|
| `ytr_categories` | id, name, weight, sort_order | — (YAML 동기화 사본) |
| `ytr_regions` | id, name | — |
| `ytr_channels` | id(UCxx), title, country, subscriber_count(캐시), category_id, region, `*_override`, is_seed | 비활성 90일 시 제외 |
| `ytr_channel_snapshots` | channel_id, ts, subscriber_count, view_count, video_count | **30일** |
| `ytr_videos` | id, channel_id, title, published_at, duration, is_short, category_id, region | **30일** (published 기준) |
| `ytr_video_snapshots` | video_id, ts, view_count, like_count, comment_count | **30일** |
| `ytr_trend_scores` | scope, kind, category_id, region, rank, score, target_id + **표시용 비정규화 필드** | 매 compute 주기 전량 교체 |
| `ytr_quota_usage` | day, endpoint, calls, units | 운영 데이터 (웹 비노출) |

- **랭킹 발행은 원자적 교체**: `ytr_publish_trend_scores(jsonb)` RPC 가 트랜잭션 안에서 delete+insert.
  전량 교체이므로 `ytr_trend_scores` 는 항상 최신 → ToS 30일 규정에 자동으로 안전하다.
- **RLS/권한 (2단 방어)**: anon 은 조회 대상 7개 테이블 **SELECT만**(정책 + `grant select`),
  쓰기 권한은 `revoke`, `ytr_quota_usage` 는 anon 접근 전면 회수, RPC 는 service_role 만 실행.
  검증은 `tools/verify_rls.py` (13항목) — 배포 전 게이트.
- 지수 파라미터(α, floor)는 `.env` 에 두고 재계산 가능하게 (`TREND_*`).

### 시드 발굴 전략 (2026-07-30 수정)

**설계 결함 발견·수정**: 최초 부트스트랩은 발굴 결과를 구독자 내림차순으로 정렬해 상위 N개를
채택했다. 그 결과 시드 75개 중 구독자 10만 이하가 8개뿐이었고, `RISING_SUBSCRIBER_MAX=100,000`
기준의 "신규 뜨는 유튜버" 보드가 사실상 빈다. **추적 풀이 곧 발굴 한계**라는 점을 놓친 오류.

수정한 세 가지:

| 축 | 내용 |
|----|------|
| **선정** | 구독자 구간별 층화 추출 — micro(<1만) 4 / small(<10만) 5 / mid(<100만) 4 / large(≥100만) 2. **10만 이하 60% 확보**. 구간 부족 시 작은 구간 우선으로 보충 |
| **질의** | `discovery_queries`(head, 채널검색) + `discovery_queries_niche`(롱테일, 인기영상검색) 두 계열로 분리 — 둘 다 `config/categories.yaml` 소관 |
| **경로** | `type=channel`(권위도 편향) 외에 **`type=video, order=viewCount, publishedAfter=최근 30일` → 그 채널** 추가. "권위 있는 채널"이 아니라 "최근 성과를 낸 채널"을 찾는 경로 |

실측 결과(2026-07-30): 후보 135~231개/카테고리 → 채택 15개, 10만 이하 60%, 쿼터 3,521u.

**한국어 필터 (2026-07-30 추가)**: `relevanceLanguage=ko` 는 힌트일 뿐이어서 영어권 채널이 유입된다.
`looks_korean()` = 국가코드 KR **또는** 채널명/소개에 한글 (OR 조건 — 국가코드 비공개가 흔하고
`UNDERkg` 처럼 영문명 한국 채널이 있어 어느 한쪽만으로는 오판한다). `--allow-foreign` 로 해제 가능.

실측 편차가 컸다: **aicoding 은 후보 196개 중 73개가 비한국어**(freeCodeCamp 1,180만, CBC News 471만
등)로, 필터 없이는 카테고리가 성립하지 않았다. 반면 나머지 5개 카테고리는 사실상 ShortCircuit 1건뿐 —
AI·코딩만 영어권 비중이 압도적이라는 도메인 특성이다. 따라서 기존 5개 카테고리는 재발굴하지 않았다.

### 분류기 점수의 함정 (2026-07-30 실측)

점수를 `히트 수 × 가중치`로 두면 **키워드를 많이 가진 카테고리가 구조적으로 이긴다**.
food 키워드를 48개로 늘린 직후 캠핑 채널(조조캠핑)·육아 브이로그(트위티)·여행 채널(푸른아오)이
전부 food 로 넘어갔다 — 캠핑/육아 영상 제목에 음식 이야기가 여러 번 나오기 때문이다.
→ `MAX_COUNTED_HITS = 3` 상한으로 "얼마나 많이 언급했나"가 아니라 "어느 주제가 걸렸나"로 경쟁시킨다.

키워드는 **채널이 실제로 쓰는 말**로 채워야 한다. 등산 채널은 '등산'이라 쓰지 않고
'지리산 칠선계곡·100대명산 완등·백운대 최단코스'라고 쓴다. 그래서 주요 명산 이름 19개를 열거했다
(한국 서비스이므로 유한하다). 영어 제목 채널(MIZI)을 위해 workout·stretching 등 영어 용어도 넣는다.

### 시드 보충 (refill)

`jobs/refill_seeds.py` — 검증 탈락분을 교체한다. bootstrap 과 달리 **RSS 검증을 통과한 채널만
채택**하므로 뽑고 버리는 낭비가 없고, **결손이 채워지면 즉시 검색을 멈춘다**.
실측: food 는 2회 검색(200u)으로 5개를 채웠고, fitness 는 2회(200u)로 4개를 채웠다.
카테고리당 최대 700u 대비 크게 절약된다.

⚠️ **쿼터 원장은 프로세스마다 0에서 시작한다** — 같은 날 여러 번 실행하면 일 상한을 넘길 수 있다.
누적 추적은 P4 의 `ytr_quota_usage` 적재가 들어와야 가능하며, 그때까지는 `--budget-units` 로
실행분을 직접 제한한다.

**남은 노이즈(P3에서 교정)**: 인기영상 경로는 조회수 상위를 뽑기 때문에 **대형 예능·뉴스 채널이
아무 질의에나 걸린다** — travel 에 ILLIT·뜬뜬, vlog 에 KNN NEWS, fitness 에 한국관광공사TV,
food 에 다람냥(슬라임). 전부 한국 채널이지만 **카테고리가 틀렸다**(언어 문제와 별개).
반대로 micro/small 구간은 롱테일 질의와 잘 맞아 정확도가 높다.
→ 대응: ① 분류기가 영상 제목·태그로 재배정 ② 대형 구간 `is_seed` 신뢰도 하향.

### 접속 방식 (실측 기록, 2026-07-30)

| 용도 | 경로 | 비고 |
|------|------|------|
| 런타임 (수집기·웹) | **PostgREST HTTPS** | 공용 CA로 검증 성공. 네이티브 드라이버 불필요 |
| DDL/마이그레이션 | pg8000 → `aws-1-ap-northeast-2.pooler.supabase.com:6543` | ⚠️ `aws-0`이 아니라 **`aws-1`** |
| 마이그레이션 TLS | Supabase 자체 CA(`Supabase Intermediate 2021 CA`) | 공용 스토어에 없음 → 대시보드에서 CA 내려받아 `--ca` 사용 권장. 현재는 `--insecure`로 적용함 |

## 4. Phase 구성

| Phase | 범위 | 완료 기준 |
|-------|------|-----------|
| **P0. 스캐폴딩** | 저장소 구조, `.venv`, `.env.example`, Supabase 프로젝트+스키마, categories.yaml/seeds.yaml 골격 | 스키마 마이그레이션 적용, 로컬에서 DB 연결 스모크 통과 |
| **P1. Core 수집기** | yt_client(harness/live), rss_watcher, 스냅샷 저장, purge | 전 테스트 GREEN (harness만, live 0회) |
| **P2. 지수 엔진** | trend_engine — 정규화 velocity, 4종 랭킹(trending/rising × video/channel), fixture 시계열 검증 | 산식 단위 테스트 + 랭킹 통합 테스트 GREEN |
| **P3. 분류·발굴** | classifier(키워드 규칙), discover(search 예산제), 시드 부트스트랩 스크립트 | 분류 정확도 스팟체크(수동 30건), 예산 가드 테스트 GREEN |
| **P4. 파이프라인 통합** | jobs 3종 + GitHub Actions cron(하루 3회), 쿼터 사용량 로깅, 실패 알림 | Actions에서 3일 연속 무인 성공 |
| **P5. 웹 프론트** | **DESIGN.md 먼저 작성**(dataviz 스킬 + validate_palette.js) → 홈 4보드, 채널 상세(성장 그래프), 라이트/다크 | DESIGN.md 검증 기록 완료, 로컬 빌드+접근성 체크리스트 통과 |
| **P6. 콜드스타트·배포** | 2주 데이터 축적(P4 완료 시점부터 병행), **보안 검토 게이트**, Vercel 배포, 개인정보처리방침·브랜딩 표기 | 보안 검토 통과 보고 + 배포 후 스모크 |

- P5는 P4의 Actions 가동(콜드스타트 축적)과 **병렬 진행** — 2주 대기가 크리티컬 패스가 되지 않게.
- 각 Phase는 TDD: 테스트 먼저 → 구현 → 리팩터. Phase 완료 시 TASK.md에 일시 기록.
- **Phase 완료마다 `tools/gen_progress.py` 실행 → 진행 대시보드 아티팩트 갱신·게시** (워크스페이스 CLAUDE.md SDD 규칙 4). 대시보드는 `dataviz` 검증 기본 팔레트 사용 — 서비스 UI가 아니므로 `docs/DESIGN.md` 범위 밖.

## 4a. 수집 실측 (2026-08-03 1회차)

| 항목 | 실측 |
|------|------|
| 채널 | 90 (channels.list 2회 = **2u**) |
| 새 영상 감지 | RSS 90요청 = **0u** |
| 영상 | 479 (videos.list 10회 = **10u**) |
| **1회 합계** | **12u** — 하루 3회 = 36u / 일 상한 9,500u |

즉 수집은 일 예산의 **0.4%** 만 쓴다. 남는 예산은 전부 발굴(search.list 100u/회) 몫이다.
설계 전제였던 "RSS 로 감지 + 배치로 통계"가 실측으로 확인됐다.

**추적 창 14일**: 지수는 영상 나이 7일 / 속도 구간 48h 를 쓰므로 여유를 두되 보관정책(30일) 안이다.
매 회차 **기존 추적 영상을 다시 찍는다** — 스냅샷 2개 이상이어야 속도가 나오므로,
새 영상만 찍으면 모든 영상이 영원히 스냅샷 1개로 남는다.

### 실게시에서만 드러난 것 (2026-08-03)

| 발견 | 내용 |
|------|------|
| **RPC 400 — `DELETE requires a WHERE clause`** | Supabase 는 WHERE 없는 DELETE/UPDATE 를 차단한다. `001_init.sql` 의 `delete from ytr_trend_scores;` 가 걸렸다. **함수 본문 안이라 배포·문법 검사로는 안 잡히고 첫 실게시에서야 드러났다** → `003_fix_publish_rpc.sql` 에서 `where true` 로 의도 명시 |
| **채널 보드가 0행** | 버그가 아니다. 채널 `view_count`/`subscriber_count` 는 3분 간격으로는 움직이지 않고, **구독자 수는 유튜브가 반올림해서 준다**(16,800,000 처럼). 8시간 간격 cron 에서는 채워진다. 다만 대형 채널의 구독자 증감은 반올림 단위(10만) 이하로는 관측 불가 — rising 채널이 10만 이하 대상이라 실사용에는 문제없다 |

이 두 가지가 "로컬 GREEN 이 배포 조건의 일부일 뿐"이라는 규칙의 실증 사례다.

## 4b. 유지보수 파이프라인 (FR-9, 2026-07-30 확정)

**정기 실행 (P-D5)**: 수집 cron 하루 3회 직후 같은 워크플로에서 이어 실행한다 —
수집이 끝난 상태를 곧바로 검증·집계해야 상황판이 실제를 반영한다.

```
collect (수집)  →  compute (지수)  →  purge (30일)  →  verify_seeds (RSS, 쿼터 0)
                                                        → gen_admin / gen_seeds_review (리포트)
```

리포트 생성물(`docs/*.html`)은 Actions 산출물로 커밋하거나 아티팩트로 게시한다.
**검증 실패는 워크플로를 실패시키지 않는다** — 시드 품질 문제는 수집 중단 사유가 아니고,
상황판의 경고로 드러나야 할 성질의 정보다.

**수동 절차 (카테고리 추가)**: 런북 6단계 — 콘솔 페이지가 실행 명령을 그대로 제공한다.
핵심 주의사항 2가지를 페이지에 명시했다:
- 시드 발굴은 **반드시 `--only`** — 전체 재발굴은 카테고리당 700u 를 다시 태운다
- **검증 탈락은 삭제 대상이 아니라 검토 대상** — 실측상 탈락 7건 중 3건이 키워드 부족이었다

**자동 점검 임계값** (`tools/gen_admin.py` 상단 상수, 근거는 §6 리스크 표):

| 항목 | 임계값 | 근거 |
|------|--------|------|
| 검증 기록 노후 | 7일 | 채널이 주제를 바꾸는 주기 |
| 카테고리 통과율 하한 | 60% | 그 이하면 키워드 또는 시드 구성 문제 |
| 무수집 경고 | 12시간 | §6 "Actions cron 지연" 대응 기준과 동일 |
| 쿼터 경고 | 일 상한의 80% | 추가 발굴 여부 판단선 |

## 5. 마일스톤

| 마일스톤 | 내용 |
|----------|------|
| M1 | P0~P2 — 로컬 harness GREEN (외부 호출 0) |
| M2 | P3~P4 — Actions cron 가동, 콜드스타트 시작 |
| M3 | P5 — UI 완성 (로컬), DESIGN 검증 기록 완료 |
| M4 | P6 — 2주 데이터 + 보안 검토 통과 → 공개 배포 |

## 6. 리스크와 대응

| 리스크 | 대응 |
|--------|------|
| RSS 피드가 채널당 최신 15개만 제공 | **실측 확인(2026-07-30): 정확히 15개.** 하루 3회 폴링이면 충분 (일 15개 초과 업로드 채널은 드묾); 놓친 영상은 discover가 보완 |
| **RSS 루트 `yt:channelId` 의 `UC` 접두어 누락** | 실측 확인 — 루트는 `DqOf2y4k-…`, entry 레벨은 `UCDqOf2y4k-…`. 루트 값을 믿으면 외래키가 어긋난다. `_resolve_channel_id()` 가 entry → 링크 → 접두어 복원 순으로 처리하고 회귀 테스트로 고정 |
| Shorts/롱폼 혼재로 랭킹 왜곡 | Shorts 는 조회수 규모가 달라 같은 보드에서 겨루면 롱폼이 밀린다. 현재 `is_short = 길이 ≤ 180초` 휴리스틱(API 가 종횡비를 주지 않음). **보드 분리 여부는 P2 결정 사항** |
| GitHub Actions cron 지연/미실행 (무료 티어 특성) | 지수 계산이 스냅샷 간격에 무관하도록 Δt 실측 기반 산식; 12시간 무수집 시 알림 |
| 쿼터 소진 | jobs/collect가 예산 카운터 유지, 소진 시 수집만 중단 (서빙 무영향) |
| 분류 오탐 (키워드 규칙 한계) | 채널 단위 수동 오버라이드 컬럼; 정확도 미달 시 LLM 분류 Phase 추가 (SPEC 개정) |
| **Supabase 500MB 초과 (실질 리스크 ↑)** | 무료 티어를 **다른 앱들과 공유**한다 (기존 67 테이블, 일부 수천~8천 행). 추적 5천 채널·2만 영상 × 하루 3회 × 30일이면 스냅샷만 200만 행대 → 용량 초과 가능. **대응: 고해상도 스냅샷은 7일만 보존, 8~30일 구간은 일 1회로 다운샘플링**(P2에서 구현). 사용량 모니터링 필수 |
| **공유 프로젝트 사고 위험** | 다른 앱과 같은 DB — 접두어 없는 DDL 이 남의 테이블을 건드릴 수 있다. `ytr_` 접두어 강제 테스트 + 마이그레이션은 `IF NOT EXISTS`/`OR REPLACE` 만 사용, `drop table` 금지 |
| YouTube ToS 30일 규정 | purge 잡을 P1부터 구현·테스트 (배포 직전 아님) |

## 7. 결정 기록 (확정, 2026-07-30)

| # | 항목 | 결정 |
|---|------|------|
| P-D1 | 수집 주기 | ✅ 하루 3회 — 00/08/16 KST (= UTC 15/23/07, cron `0 15,23,7 * * *`) |
| P-D2 | 웹→DB 접근 방식 | ✅ Supabase anon key + RLS read-only. 읽기 전용이므로 서버 프록시 불필요. **service key는 수집기(Actions Secrets)에만** |
| P-D3 | 콜드스타트 중 P5 병렬 진행 | ✅ 병렬 — fixture 데이터로 UI 개발 |
| P-D4 | 운영 콘솔 성격 | ✅ **상황판 + 러너블(읽기 전용)** — 버튼 실행은 인증·감사로그가 필요하므로 별도 Phase 로 미룸 |
| P-D5 | 유지보수 작업 실행 방식 | ✅ **수집 cron 에 이어붙임** (하루 3회). 검증 실패가 워크플로를 실패시키지 않는다 |
