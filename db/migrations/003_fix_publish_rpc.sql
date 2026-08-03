-- =============================================================
-- 003 — ytr_publish_trend_scores 의 무조건 DELETE 수정
--
-- 문제(2026-08-03 실측): 첫 실게시에서 HTTP 400
--   {"code":"21000","message":"DELETE requires a WHERE clause"}
--
-- Supabase 는 실수로 테이블을 비우는 것을 막기 위해 WHERE 없는 DELETE/UPDATE 를 차단한다.
-- 001_init.sql 의 `delete from ytr_trend_scores;` 가 여기에 걸렸다.
-- 보드는 매 주기 전량 교체가 정상 동작이므로, 의도를 명시한 WHERE 를 붙인다.
--
-- 함수 본문 안의 DELETE 라 로컬 psql 에서는 통과했고 **실 게시 시점에야 드러났다** —
-- 그래서 P4 에서 실제 게시를 한 번 돌려보는 것이 필요했다.
-- =============================================================

create or replace function ytr_publish_trend_scores(rows jsonb)
returns int
language plpgsql
security invoker
as $$
declare
  inserted int;
begin
  -- `where true` — 전량 삭제가 의도임을 명시한다 (Supabase 안전장치 통과)
  delete from ytr_trend_scores where true;

  insert into ytr_trend_scores (
    scope, kind, category_id, region, rank, score, target_id,
    title, channel_id, channel_title, thumbnail_url, published_at,
    view_count, subscriber_count, delta_views, window_hours
  )
  select
    r->>'scope',
    r->>'kind',
    r->>'category_id',
    nullif(r->>'region', ''),
    (r->>'rank')::int,
    (r->>'score')::double precision,
    r->>'target_id',
    r->>'title',
    r->>'channel_id',
    r->>'channel_title',
    r->>'thumbnail_url',
    nullif(r->>'published_at', '')::timestamptz,
    nullif(r->>'view_count', '')::bigint,
    nullif(r->>'subscriber_count', '')::bigint,
    nullif(r->>'delta_views', '')::bigint,
    nullif(r->>'window_hours', '')::real
  from jsonb_array_elements(rows) as r;

  get diagnostics inserted = row_count;
  return inserted;
end;
$$;
