import { NextRequest, NextResponse } from "next/server";
import { requireAdmin, requireLogin } from "@/lib/auth";
import { getSupabaseAdmin } from "@/lib/supabase";

export async function POST(request: NextRequest) {
  const session = await requireLogin().catch(() => null);
  if (!session)
    return NextResponse.json({ error: "请先登录" }, { status: 401 });
  const supabaseAdmin = getSupabaseAdmin();

  const { content } = await request.json();
  if (!content?.trim()) {
    return NextResponse.json({ error: "内容不能为空" }, { status: 400 });
  }

  const { error } = await supabaseAdmin.from("feedback").insert({
    rater_id: session.raterId,
    content: content.trim(),
    created_at: new Date().toISOString(),
  });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ success: true });
}

export async function GET() {
  const admin = await requireAdmin().catch(() => null);
  if (!admin) return NextResponse.json([], { status: 403 });
  const supabaseAdmin = getSupabaseAdmin();

  const { data } = await supabaseAdmin
    .from("feedback")
    .select("rater_id, content, created_at")
    .order("created_at", { ascending: false });

  return NextResponse.json(data || []);
}
