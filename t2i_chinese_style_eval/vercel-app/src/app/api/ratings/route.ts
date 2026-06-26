import { NextRequest, NextResponse } from "next/server";
import { requireLogin } from "@/lib/auth";
import {
  EVALUATION_SET_ID,
  BLIND_MODEL_LABELS,
  getSupabaseAdmin,
} from "@/lib/supabase";

export async function POST(request: NextRequest) {
  const session = await requireLogin().catch(() => null);
  if (!session)
    return NextResponse.json({ error: "请先登录" }, { status: 401 });
  const supabaseAdmin = getSupabaseAdmin();

  const body = await request.json();
  const {
    image_id,
    style_consistency_score,
    element_accuracy_score,
    error_control_score,
    overall_score,
    comment,
  } = body;

  if (
    !image_id ||
    ![1, 2, 3, 4, 5].includes(style_consistency_score) ||
    ![1, 2, 3, 4, 5].includes(element_accuracy_score) ||
    ![1, 2, 3, 4, 5].includes(error_control_score) ||
    ![1, 2, 3, 4, 5].includes(overall_score)
  ) {
    return NextResponse.json({ error: "每个维度都需选择 1-5 分" }, { status: 400 });
  }

  // Look up metadata for job_id, prompt_id, model_id
  const { data: meta } = await supabaseAdmin
    .from("metadata")
    .select("job_id, model_id")
    .eq("image_id", image_id)
    .single();

  if (!meta?.job_id || !meta?.model_id) {
    return NextResponse.json({ error: "图片元数据缺失" }, { status: 500 });
  }

  const { data: job } = await supabaseAdmin
    .from("generation_jobs")
    .select("prompt_id")
    .eq("job_id", meta.job_id)
    .single();

  if (!job?.prompt_id) {
    return NextResponse.json({ error: "提示词元数据缺失" }, { status: 500 });
  }

  const blindModelLabel = BLIND_MODEL_LABELS[meta.model_id];
  if (!blindModelLabel) {
    return NextResponse.json({ error: "盲评模型标签配置缺失" }, { status: 500 });
  }

  const now = new Date().toISOString();
  const ratingId = `R${now.replace(/[-:T.Z]/g, "").slice(0, 14)}_${Math.random()
    .toString(36)
    .slice(2, 8)}`;

  const { error } = await supabaseAdmin.from("ratings").upsert(
    {
      rating_id: ratingId,
      evaluation_set_id: EVALUATION_SET_ID,
      image_id,
      job_id: meta.job_id,
      prompt_id: job.prompt_id,
      reviewer_id: session.raterId,
      blind_model_label: blindModelLabel,
      style_consistency_score,
      element_accuracy_score,
      error_control_score,
      overall_score,
      comment: comment || null,
      created_at: now,
      updated_at: now,
    },
    { onConflict: "evaluation_set_id,image_id,reviewer_id" }
  );

  if (error) {
    return NextResponse.json({ error: `保存失败: ${error.message}` }, { status: 500 });
  }

  return NextResponse.json({ success: true, rating_id: ratingId });
}
