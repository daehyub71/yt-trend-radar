-- =============================================================
-- 004 — 보드에 format(롱폼/Shorts) 축 추가
--
-- 근거(2026-08-03 실측): 추적 영상 486개 중 306개(63%)가 Shorts 이고,
-- 산출된 보드의 **67%가 Shorts** 였다. Shorts 는 조회수 획득 속도가 롱폼과 근본적으로
-- 달라, 같은 보드에서 겨루면 롱폼이 거의 노출되지 않는다.
-- → 영상 보드를 format 별로 분리해 각자 공정하게 경쟁시킨다.
--
-- format 은 채널 보드에서는 null 이다 (채널에 롱폼/Shorts 구분이 없다).
-- =============================================================

alter table ytr_trend_scores
  add column if not exists format text
  check (format is null or format in ('long', 'short'));

comment on column ytr_trend_scores.format is
  '영상 보드의 형식 축: long | short. 채널 보드는 null.';

-- 유니크 인덱스에 format 을 포함해야 롱폼/Shorts 가 같은 rank 를 가질 수 있다
drop index if exists ytr_trend_scores_board_rank_idx;
create unique index ytr_trend_scores_board_rank_idx
  on ytr_trend_scores (
    scope, kind, category_id,
    coalesce(region, '*'), coalesce(format, '*'), rank
  );

drop index if exists ytr_trend_scores_board_idx;
create index ytr_trend_scores_board_idx
  on ytr_trend_scores (scope, kind, category_id, region, format, rank);

-- 게시 RPC 도 format 을 함께 적재하도록 갱신
create or replace function ytr_publish_trend_scores(rows jsonb)
returns int
language plpgsql
security invoker
as $$
declare
  inserted int;
begin
  delete from ytr_trend_scores where true;   -- Supabase 안전장치: WHERE 필수

  insert into ytr_trend_scores (
    scope, kind, category_id, region, format, rank, score, target_id,
    title, channel_id, channel_title, thumbnail_url, published_at,
    view_count, subscriber_count, delta_views, window_hours
  )
  select
    r->>'scope',
    r->>'kind',
    r->>'category_id',
    nullif(r->>'region', ''),
    nullif(r->>'format', ''),
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
