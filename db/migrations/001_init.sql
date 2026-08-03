-- yt-trend-radar — 초기 스키마 (PLAN §3)
-- 적용: python tools/apply_migrations.py  (또는 Supabase SQL Editor 에 붙여넣기)
--
-- ⚠️ 이 Supabase 프로젝트는 다른 앱들과 공유된다 (public 스키마에 67개 테이블 기존 존재).
--    따라서 이 프로젝트의 모든 객체는 `ytr_` 접두어를 쓴다. 접두어 없는 이름은 절대 쓰지 않는다.
--
-- 보관 정책: YouTube API ToS 상 수집 데이터는 30일 내 갱신 또는 삭제 (SPEC NFR-1).
--            jobs/purge.py 가 RETENTION_DAYS 기준으로 삭제한다.
-- 권한 정책: anon(웹)은 SELECT 전용. 쓰기는 service_role(수집기)만. (PLAN P-D2)

-- =============================================================
-- 1. ytr_categories / ytr_regions — config/categories.yaml 동기화 사본
-- =============================================================
create table if not exists ytr_categories (
  id            text primary key,               -- 'food', 'travel', ...
  name          text not null,                  -- '음식'
  weight        real not null default 1.0,
  sort_order    int  not null default 0,
  updated_at    timestamptz not null default now()
);

create table if not exists ytr_regions (
  id            text primary key,               -- 'domestic' | 'overseas'
  name          text not null                   -- '국내' | '해외'
);

-- =============================================================
-- 2. ytr_channels — 추적 대상 채널
-- =============================================================
create table if not exists ytr_channels (
  id                 text primary key,          -- 'UCxxxx...' (YouTube channel id)
  title              text not null,
  handle             text,
  thumbnail_url      text,
  country            text,                      -- API country 필드 ('KR' 등)
  uploads_playlist   text,
  subscriber_count   bigint,                    -- 최신 스냅샷 값 (조회 편의용 캐시)
  video_count        bigint,
  view_count         bigint,
  category_id        text references ytr_categories(id) on delete set null,
  region             text references ytr_regions(id) on delete set null,
  category_override  text references ytr_categories(id) on delete set null,  -- 수동 교정 우선
  region_override    text references ytr_regions(id) on delete set null,
  is_seed            boolean not null default false,
  discovered_at      timestamptz not null default now(),
  last_seen_at       timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists ytr_channels_category_idx  on ytr_channels (category_id, region);
create index if not exists ytr_channels_last_seen_idx on ytr_channels (last_seen_at desc);

-- =============================================================
-- 3. ytr_channel_snapshots — 구독자/조회수 시계열 (30일 롤링)
-- =============================================================
create table if not exists ytr_channel_snapshots (
  channel_id        text not null references ytr_channels(id) on delete cascade,
  ts                timestamptz not null,
  subscriber_count  bigint,
  view_count        bigint,
  video_count       bigint,
  primary key (channel_id, ts)
);

create index if not exists ytr_channel_snapshots_ts_idx on ytr_channel_snapshots (ts);

-- =============================================================
-- 4. ytr_videos — 영상 메타 (30일 롤링, published_at 기준)
-- =============================================================
create table if not exists ytr_videos (
  id                text primary key,           -- YouTube video id
  channel_id        text not null references ytr_channels(id) on delete cascade,
  title             text not null,
  thumbnail_url     text,
  published_at      timestamptz not null,
  duration_seconds  int,
  is_short          boolean not null default false,
  category_id       text references ytr_categories(id) on delete set null,
  region            text references ytr_regions(id) on delete set null,
  view_count        bigint,                     -- 최신 스냅샷 값 (캐시)
  like_count        bigint,
  first_seen_at     timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists ytr_videos_channel_idx   on ytr_videos (channel_id);
create index if not exists ytr_videos_published_idx on ytr_videos (published_at desc);
create index if not exists ytr_videos_category_idx  on ytr_videos (category_id, region, published_at desc);

-- =============================================================
-- 5. ytr_video_snapshots — 조회수 시계열 (30일 롤링)
-- =============================================================
create table if not exists ytr_video_snapshots (
  video_id      text not null references ytr_videos(id) on delete cascade,
  ts            timestamptz not null,
  view_count    bigint,
  like_count    bigint,
  comment_count bigint,
  primary key (video_id, ts)
);

create index if not exists ytr_video_snapshots_ts_idx on ytr_video_snapshots (ts);

-- =============================================================
-- 6. ytr_trend_scores — 산출된 랭킹 (웹이 읽는 유일한 랭킹 소스)
--    조인 없이 카드를 그릴 수 있도록 표시 필드를 비정규화해 담는다.
--    compute 주기마다 ytr_publish_trend_scores() 로 원자적 교체 → 항상 최신(ToS 안전).
-- =============================================================
create table if not exists ytr_trend_scores (
  id            bigserial primary key,
  scope         text not null check (scope in ('video', 'channel')),
  kind          text not null check (kind  in ('trending', 'rising')),
  category_id   text not null,
  region        text,                            -- null = region 무관(전체)
  rank          int  not null,
  score         double precision not null,
  target_id     text not null,                   -- video id 또는 channel id

  -- 표시용 비정규화 필드
  title            text,
  channel_id       text,
  channel_title    text,
  thumbnail_url    text,
  published_at     timestamptz,
  view_count       bigint,
  subscriber_count bigint,
  delta_views      bigint,                       -- 산출 구간 조회수 증가량
  window_hours     real,                         -- 산출 구간 길이 (Δt 실측)

  computed_at   timestamptz not null default now()
);

create unique index if not exists ytr_trend_scores_board_rank_idx
  on ytr_trend_scores (scope, kind, category_id, coalesce(region, '*'), rank);
create index if not exists ytr_trend_scores_board_idx
  on ytr_trend_scores (scope, kind, category_id, region, rank);

-- =============================================================
-- 7. ytr_quota_usage — 일별 API 쿼터 사용량 (안전장치, SPEC NFR-4)
-- =============================================================
create table if not exists ytr_quota_usage (
  day          date not null,
  endpoint     text not null,                    -- 'videos.list' | 'channels.list' | 'search.list'
  calls        int  not null default 0,
  units        int  not null default 0,
  primary key (day, endpoint)
);

-- =============================================================
-- 8. ytr_publish_trend_scores — 보드 원자적 교체 RPC
-- =============================================================
create or replace function ytr_publish_trend_scores(rows jsonb)
returns int
language plpgsql
security invoker
as $$
declare
  inserted int;
begin
  delete from ytr_trend_scores;

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

-- =============================================================
-- 9. RLS — anon(웹)은 읽기만. service_role 은 RLS 우회(Supabase 기본).
-- =============================================================
alter table ytr_categories        enable row level security;
alter table ytr_regions           enable row level security;
alter table ytr_channels          enable row level security;
alter table ytr_channel_snapshots enable row level security;
alter table ytr_videos            enable row level security;
alter table ytr_video_snapshots   enable row level security;
alter table ytr_trend_scores      enable row level security;
alter table ytr_quota_usage       enable row level security;

do $$
declare t text;
begin
  -- 웹이 읽어야 하는 테이블: 랭킹 보드 + 채널 상세(성장 그래프)
  foreach t in array array[
    'ytr_categories','ytr_regions','ytr_channels','ytr_channel_snapshots',
    'ytr_videos','ytr_video_snapshots','ytr_trend_scores'
  ]
  loop
    execute format('drop policy if exists %I on %I', t || '_anon_read', t);
    execute format(
      'create policy %I on %I for select to anon, authenticated using (true)',
      t || '_anon_read', t
    );
  end loop;
end $$;

-- ytr_quota_usage 는 운영 데이터 — 웹에 노출하지 않는다 (정책 없음 = anon 접근 불가).
