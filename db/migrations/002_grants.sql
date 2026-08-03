-- 002_grants.sql — 권한 최소화 (defense in depth)
--
-- 배경: Supabase 는 public 스키마의 테이블에 anon/authenticated 역할에게 기본 권한을 부여한다.
--       RLS 만으로도 데이터는 막히지만(정책 없음 = 0행), 테이블 존재 자체는 API 로 드러난다.
--       쓰기 역시 RLS 로 막히지만, 권한 계층에서 한 번 더 막는 편이 안전하다.
--
-- 원칙:
--   - 웹(anon)에는 조회 대상 테이블의 SELECT 만 남긴다.
--   - 운영 테이블(ytr_quota_usage)은 anon 접근을 완전히 회수한다.
--   - 쓰기는 service_role 만 (Supabase 기본으로 RLS 우회 + 권한 보유).

-- 1) 웹이 읽는 테이블: SELECT 만 남기고 쓰기 권한 회수
do $$
declare t text;
begin
  foreach t in array array[
    'ytr_categories','ytr_regions','ytr_channels','ytr_channel_snapshots',
    'ytr_videos','ytr_video_snapshots','ytr_trend_scores'
  ]
  loop
    execute format('revoke insert, update, delete, truncate, references, trigger on %I from anon, authenticated', t);
    execute format('grant select on %I to anon, authenticated', t);
  end loop;
end $$;

-- 2) 운영 테이블: anon/authenticated 접근 전면 회수 (수집기 전용)
revoke all on ytr_quota_usage from anon, authenticated;

-- 3) RPC: 랭킹 발행은 수집기만 호출 가능해야 한다
revoke all on function ytr_publish_trend_scores(jsonb) from anon, authenticated;
revoke execute on function ytr_publish_trend_scores(jsonb) from public;
grant execute on function ytr_publish_trend_scores(jsonb) to service_role;
