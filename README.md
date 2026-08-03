# yt-trend-radar

카테고리별 유튜브 트렌드 발견 서비스 — **지금 뜨는 / 신규 뜨는** 영상·유튜버를 찾습니다.

[English](README.en.md)

---

## 왜 만드는가

유튜브는 **2025년 7월에 Trending 페이지를 폐지**했습니다. Data API v3 의
`videos.list(chart=mostPopular)` 도 이제 Music / Movies / Gaming 차트만 반환합니다.

실제로 확인한 응답 (한국, 2026-07-30):

```
[10] Shut The Door                        — Music
[1]  어벤져스: 둠스데이 코믹콘 예고편 유출   — Film
[20] '펜타킬의 기억' 대회 승률 100% 아지르  — Gaming
```

즉 **"음식"·"여행" 같은 카테고리의 트렌드는 API 로 얻을 수 없습니다.**
직접 계산해야 하고, 그것이 이 프로젝트의 전제이자 차별점입니다.

## 어떻게 계산하는가

스냅샷 시계열에서 **정규화 velocity** 를 구합니다.

```
score = Δ값 / (Δ시간h × max(구독자, floor) ** α)
```

α 하나로 성격이 다른 두 보드를 만듭니다.

| 보드 | α | 의미 |
|------|---|------|
| **지금 뜨는** | 0.25 | 절대 증가량 위주. 대형 채널에 완만한 핸디캡만 준다 |
| **신규 뜨는** | **1.00** | 구독자 1명당 증가량 = 규모 중립. 구독자 대비 성과가 좋은 소형 채널이 위로 |

> **α ≥ 1.0 은 규약입니다.** Δ가 구독자에 비례할 때 `score ∝ 구독자^(1-α)` 이므로,
> α<1 이면 "신규 뜨는" 보드도 결국 구독자 순이 됩니다. α=0.7 로 시연했을 때 실제로 그랬습니다.
> α=1.0 에서만 "구독자 대비 성과"라는 정의가 성립합니다.
> 코드는 α<1 인 rising 설정을 **생성 시점에 예외로 막습니다** — 조용히 열화되면 아무도 눈치채지 못하기 때문입니다.

**Δ시간은 실측합니다.** GitHub Actions cron 은 밀리므로, 8시간 간격을 가정하면 지연된 주기에서
속도가 부풀거나 꺼집니다.

## 쿼터 전략

YouTube Data API 는 하루 10,000 units 이고 추가 구매가 불가능합니다.
`search.list` 가 100 units 로 압도적으로 비싸기 때문에, 수집 경로를 이렇게 나눴습니다.

| 용도 | 방법 | 비용 | 실측 (채널 90개) |
|------|------|------|------------------|
| 새 영상 감지 | **채널 RSS 피드** | **0 u** | 90 요청 |
| 영상 통계 | `videos.list` 50개 배치 | 1 u / 50개 | 영상 479개 → 10 u |
| 채널 통계 | `channels.list` 50개 배치 | 1 u / 50개 | 2 u |
| 채널 발굴 | `search.list` (예산제) | 100 u / 회 | 수집 경로에서 제외 |

**수집 1회 = 12 units.** 하루 3회 = 36 u — 일 예산의 0.4% 입니다.
사용자 트래픽은 쿼터와 무관합니다. 웹은 자체 DB 만 읽습니다.

```
[크론 수집기] --일 36u--> YouTube API
      ↓ 스냅샷 적재
[Supabase] --지수 산출--> 랭킹 테이블
      ↓ 조회 (읽기 전용)
[웹]  ← 방문자가 몇 명이든 쿼터 소모 0
```

## 구조

```
collector/            수집·산출 (Python, 외부 의존성 최소)
  core/               models · config · db · quota
  sources/            yt_client · rss_watcher   (모두 harness/live 두 구현)
  engine/             classifier · trend_engine
  jobs/               collect · compute · purge · bootstrap_seeds · refill_seeds
  tests/              243개, 외부 호출 없이 실행
config/               categories.yaml (분류 규칙·발굴 질의) · seeds.yaml (추적 채널)
db/migrations/        스키마 · 권한(RLS) · 게시 RPC
tools/                리포트 생성기 · 검증 스크립트
docs/                 SPEC · PLAN · DESIGN · TASK  ← 진실의 원천
```

## 개발 방식

- **SDD** — `docs/` 의 SPEC → PLAN → DESIGN → TASK 를 코드와 같은 turn 에 갱신합니다.
  코드와 문서가 어긋나면 **문서가 진실**입니다.
- **TDD** — 모듈 구현 전에 테스트를 씁니다. 기본 게이트는 **외부 호출 0** 으로 돌아갑니다
  (`YT_MODE=harness`). 실 API 를 쓰는 테스트는 `@pytest.mark.live` 로 격리합니다.
- **Harness 우선** — 모든 외부 의존성(API·DB)은 harness 구현을 함께 갖습니다.

```bash
cd collector
python -m pytest            # 243 passed — 외부 호출 없음
python -m pytest -m live    # 실제 YouTube API / RSS (쿼터 소량 소모)
```

## 실행

```bash
cp .env.example .env        # 키 채우기
cd collector && pip install -r requirements.txt

python -m jobs.sync_config          # 카테고리 → DB
python -m jobs.collect              # 수집 (12u)
python -m jobs.compute              # 지수 산출 → 랭킹 게시
python -m jobs.purge                # 30일 보관 정책 집행

python ../tools/verify_seeds.py     # 시드 품질 RSS 검증 (쿼터 0)
python ../tools/gen_admin.py        # 운영 콘솔 생성
```

카테고리를 추가하려면 `config/categories.yaml` 에 항목을 넣고 —
**코드 수정은 필요 없습니다** — 아래를 실행합니다.

```bash
python -m jobs.refill_seeds --only <category_id>   # 새 카테고리만 발굴 (700u)
```

`--only` 없이 돌리면 전체 카테고리를 다시 발굴해 쿼터를 크게 낭비합니다.

## 데이터 취급 (YouTube API ToS)

- **30일 보관 정책**: 수집 데이터는 30일 내 갱신되거나 삭제됩니다 (`jobs/purge`, 수집 때마다 실행).
- **영상 제목이 담긴 산출물은 커밋하지 않습니다.** git 이력은 지워도 남기 때문입니다.
  검토용 리포트는 Actions 아티팩트로 올라가고 자동 만료됩니다.
- 영상 재생은 **유튜브로 연결**합니다. 임베드·재호스팅하지 않습니다.
- 랭킹 점수는 **자체 산출 지표**이며 유튜브 공식 지표가 아닙니다. UI 에 그 사실을 표기합니다.
- 개인정보를 수집하지 않습니다 — 공개 채널 메타와 공개 영상 통계만 다룹니다.

## 보안

- 시크릿은 `.env`(로컬) / GitHub Secrets(CI) 에만 둡니다. 저장소에는 들어가지 않습니다.
- 웹은 **읽기 전용 키 + RLS** 로만 DB 에 접근합니다. 쓰기 권한 키는 서버에만 존재합니다.
- 배포·push 전 보안 검토가 필수 게이트입니다 (시크릿·의존성 취약점·RLS·API 예의).
  최근 검토 기록은 `docs/TASK.md` 의 「보안 검토 기록」 절에 있습니다.

## 현재 상태

콜드스타트 수집 중입니다. 속도 계산에는 스냅샷이 2개 이상 필요하므로,
수집 시작 직후 며칠은 보드가 얇습니다 — 정상이며 운영 콘솔이 그 사실을 보여줍니다.

진행 상황은 `docs/TASK.md` 와 `docs/progress.html` 에서 볼 수 있습니다.
