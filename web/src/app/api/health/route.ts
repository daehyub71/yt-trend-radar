import { NextResponse } from 'next/server';
import { DbUnavailableError, configStatus, fetchCategories } from '@/lib/db';

export const dynamic = 'force-dynamic';

/**
 * 배포 진단용. **키 값을 절대 반환하지 않는다** — 설정 존재 여부(boolean)와
 * DB 응답 상태만 노출한다.
 *
 * 왜 필요한가: 첫 Vercel 배포에서 홈이 "데이터를 불러올 수 없습니다"만 띄웠는데,
 * 그 화면만으로는 환경변수 미설정인지 키가 틀린 건지 DB 장애인지 구분할 수 없었다.
 * 원인을 못 좁히는 오류 화면은 없느니만 못하다.
 */
export async function GET() {
  const cfg = configStatus();
  const body: Record<string, unknown> = {
    ok: false,
    config: cfg,
    checkedAt: new Date().toISOString(),
  };

  if (!cfg.hasUrl || !cfg.hasAnonKey) {
    body.reason = 'missing-config';
    body.hint =
      'Vercel → Settings → Environment Variables 에 SUPABASE_URL, SUPABASE_ANON_KEY 를 ' +
      'Production 환경으로 추가한 뒤 **재배포**해야 반영됩니다.';
    return NextResponse.json(body, { status: 503 });
  }

  try {
    const categories = await fetchCategories();
    body.ok = true;
    body.categories = categories.length;
    return NextResponse.json(body);
  } catch (e) {
    if (e instanceof DbUnavailableError) {
      body.reason = e.reason;
      body.status = e.status;
      body.hint =
        e.status === 401
          ? 'anon 키가 올바르지 않거나 RLS 정책이 SELECT 를 막고 있습니다.'
          : 'DB 응답이 정상이 아닙니다. Supabase 프로젝트 상태를 확인하세요.';
    } else {
      body.reason = 'unknown';
    }
    return NextResponse.json(body, { status: 503 });
  }
}
