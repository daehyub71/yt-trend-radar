# 배포 절차 (P6)

> 배포는 **보안 검토 통과가 전제**다 (워크스페이스 CLAUDE.md §Security Review).
> 최근 검토 기록: `docs/TASK.md` 「보안 검토 기록」 2차(2026-08-03) — 미해결 위험 없음.

## 0. 공개 시점 — 지금이 아니다

속도 지수는 **같은 대상의 스냅샷 2개 이상**이 있어야 계산된다. 의미 있는 순위가 나오려면
2주 정도 축적이 필요하다.

| 항목 | 상태 |
|------|------|
| 수집 시작 | **2026-08-03** |
| 공개 목표 | **2026-08-17** |
| 현재 축적 | 3회차 (약 3시간분) |

그래서 배포는 **두 단계로 나눈다.**

1. **지금**: 색인 차단 상태로 배포해 **파이프라인을 실제 환경에서 검증**한다.
   URL 은 살아 있지만 검색에는 잡히지 않는다.
2. **8/17 이후**: 보드가 찼는지 확인하고 `SITE_PUBLIC=true` 로 공개 전환한다.

얇은 보드가 먼저 색인되면 **그것이 검색 결과의 첫인상으로 굳는다.** 이후 내용이 좋아져도
평가가 따라오지 않기 때문에, 색인 차단을 기본값으로 뒀다.

## 1. Vercel 프로젝트 연결

1. [vercel.com/new](https://vercel.com/new) → GitHub 저장소 `daehyub71/yt-trend-radar` 가져오기
2. **Root Directory** 를 반드시 **`web`** 으로 지정한다 (모노레포 구조)
3. Framework Preset: Next.js (자동 인식)
4. Node.js Version: **22.x**

## 2. 환경변수 (Vercel → Settings → Environment Variables)

| 이름 | 값 | 비고 |
|------|-----|------|
| `SUPABASE_URL` | 프로젝트 URL | |
| `SUPABASE_ANON_KEY` | **anon 키** | ⚠️ service 키를 넣지 말 것 |
| `SITE_URL` | 배포 도메인 | 예: `https://yt-trend-radar.vercel.app` |
| `SITE_PUBLIC` | *(설정하지 않음)* | 공개 전환 시에만 `true` |

**`SUPABASE_SERVICE_KEY` 는 웹에 넣지 않는다.** 웹은 읽기만 하며, 쓰기 권한 키는
수집기(GitHub Actions)에만 존재한다. 웹 코드는 그 이름을 참조하지도 않는다.

`NEXT_PUBLIC_` 접두어를 쓰지 않는 것도 의도된 설계다 — 접두어를 붙이면 값이
브라우저 번들에 인라인된다. 현재 빌드 산출물(`.next/static`)에 키가 **0건**임을 검증했다.

## 3. 배포 후 스모크 점검

```bash
BASE=https://<배포도메인>

curl -s "$BASE/robots.txt"                    # Disallow: / 여야 정상 (공개 전)
curl -s "$BASE/" -o /dev/null -w "%{http_code}\n"
curl -s "$BASE/?category=food&format=long" | grep -c 'class="card"'
curl -s "$BASE/privacy" -o /dev/null -w "%{http_code}\n"
```

- 홈이 200 이고 카드가 렌더되면 DB 연결·RLS·ISR 이 모두 정상이다.
- 카드가 0개면 환경변수를 먼저 의심한다 (특히 anon 키).

## 4. 공개 전환 (2026-08-17 이후)

1. 운영 콘솔(`docs/admin.html`)에서 확인:
   - 수집 정상 (마지막 수집 12시간 이내)
   - 랭킹 행 수가 충분한가
   - 카테고리별 보드가 비어 있지 않은가
2. Vercel 환경변수에 **`SITE_PUBLIC=true`** 추가 → 재배포
3. 확인:
   ```bash
   curl -s "$BASE/robots.txt"      # Allow: / 로 바뀐다
   curl -s "$BASE/sitemap.xml" | grep -c '<url>'   # 13개
   ```
4. Google Search Console 에 사이트맵 제출

## 5. 되돌리기

문제가 생기면 `SITE_PUBLIC` 을 지우고 재배포하면 즉시 색인 차단으로 돌아간다.
Vercel 의 이전 배포로 롤백해도 된다 — **수집 파이프라인은 웹과 독립**이라
웹을 롤백해도 데이터는 계속 쌓인다.
