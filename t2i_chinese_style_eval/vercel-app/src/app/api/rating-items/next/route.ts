import { NextRequest, NextResponse } from "next/server";
import { requireLogin } from "@/lib/auth";
import {
  EVALUATION_SET_ID,
  STORAGE_BUCKET,
  getPreviewImageUrl,
  getSupabaseAdmin,
} from "@/lib/supabase";

type RatingItemRow = {
  image_id: string;
  target_style: string;
  prompt_level: string;
  prompt_text: string;
  expected_elements?: string | null;
  forbidden_elements?: string | null;
  storage_path?: string | null;
};

type RatingRow = {
  style_consistency_score: number | null;
  element_accuracy_score: number | null;
  error_control_score: number | null;
  overall_score: number | null;
  comment: string | null;
  error_tags?: string[] | null;
};

const ITEM_SELECT =
  "image_id,target_style,prompt_level,prompt_text,expected_elements,forbidden_elements,storage_path";

function clientItem(item: RatingItemRow) {
  return {
    image_id: item.image_id,
    target_style: item.target_style,
    prompt_level: item.prompt_level,
    prompt_text: item.prompt_text,
    expected_elements: item.expected_elements ?? null,
    forbidden_elements: item.forbidden_elements ?? null,
  };
}

export async function GET(request: NextRequest) {
  const session = await requireLogin().catch(() => null);
  if (!session)
    return NextResponse.json({ error: "请先登录" }, { status: 401 });
  const supabaseAdmin = getSupabaseAdmin();

  const imageId = request.nextUrl.searchParams.get("image_id") || undefined;

  if (imageId) {
    const { data: item } = await supabaseAdmin
      .from("rating_items")
      .select(ITEM_SELECT)
      .eq("image_id", imageId)
      .single<RatingItemRow>();

    if (!item)
      return NextResponse.json({ error: "图片不存在" }, { status: 404 });

    const { data: prev } = await supabaseAdmin
      .from("ratings")
      .select(
        "style_consistency_score,element_accuracy_score,error_control_score,overall_score,comment,error_tags"
      )
      .eq("evaluation_set_id", EVALUATION_SET_ID)
      .eq("image_id", imageId)
      .eq("reviewer_id", session.raterId)
      .maybeSingle<RatingRow>();

    const url = item.storage_path
      ? supabaseAdmin.storage.from(STORAGE_BUCKET).getPublicUrl(item.storage_path)
          .data.publicUrl
      : "";

    return NextResponse.json({
      item: clientItem(item),
      url: getPreviewImageUrl(url),
      prevRating: prev || null,
    });
  }

  // Get next unrated image
  const { data: rated } = await supabaseAdmin
    .from("ratings")
    .select("image_id")
    .eq("evaluation_set_id", EVALUATION_SET_ID)
    .eq("reviewer_id", session.raterId);

  const ratedIds = new Set((rated || []).map((r) => r.image_id));

  const { data: all } = await supabaseAdmin
    .from("rating_items")
    .select(ITEM_SELECT)
    .order("image_id");

  const next = ((all || []) as RatingItemRow[]).find(
    (item) => !ratedIds.has(item.image_id)
  );

  if (!next) {
    return NextResponse.json({ done: true });
  }

  const url = next.storage_path
    ? supabaseAdmin.storage.from(STORAGE_BUCKET).getPublicUrl(next.storage_path)
        .data.publicUrl
    : "";

  return NextResponse.json({
    item: clientItem(next),
    url: getPreviewImageUrl(url),
    prevRating: null,
  });
}
