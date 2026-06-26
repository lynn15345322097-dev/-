import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth";
import {
  EVALUATION_SET_ID,
  STORAGE_BUCKET,
  getPreviewImageUrl,
  getSupabaseAdmin,
} from "@/lib/supabase";
import RateClient from "./RateClient";

const ITEM_SELECT =
  "image_id,target_style,prompt_level,prompt_text,expected_elements,forbidden_elements,storage_path";

type RatingItemRow = {
  image_id: string;
  target_style: string;
  prompt_level: string;
  prompt_text: string;
  expected_elements?: string | null;
  forbidden_elements?: string | null;
  storage_path?: string | null;
};

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

export default async function RatePage() {
  const session = await getSession();
  if (!session) redirect("/login");
  const supabaseAdmin = getSupabaseAdmin();

  // Get all items for sidebar
  const { data: allItems } = await supabaseAdmin
    .from("rating_items")
    .select("image_id")
    .order("image_id");

  // Get rated items
  const { data: rated } = await supabaseAdmin
    .from("ratings")
    .select("image_id")
    .eq("evaluation_set_id", EVALUATION_SET_ID)
    .eq("reviewer_id", session.raterId);

  const ratedIds = new Set((rated || []).map((r) => r.image_id));

  // Get first unrated
  const nextUnrated = (allItems || []).find(
    (item) => !ratedIds.has(item.image_id)
  );

  // Get counts
  const { count: total } = await supabaseAdmin
    .from("rating_items")
    .select("*", { count: "exact", head: true });

  const { count: done } = await supabaseAdmin
    .from("ratings")
    .select("*", { count: "exact", head: true })
    .eq("evaluation_set_id", EVALUATION_SET_ID)
    .eq("reviewer_id", session.raterId);

  // If no unrated, show done
  if (!nextUnrated) {
    return (
      <RateClient
        raterId={session.raterId}
        isAdmin={session.isAdmin}
        done={true}
        total={total || 0}
        ratedCount={done || 0}
      />
    );
  }

  // Fetch the next item with full details
  const { data: item } = await supabaseAdmin
    .from("rating_items")
    .select(ITEM_SELECT)
    .eq("image_id", nextUnrated.image_id)
    .single<RatingItemRow>();

  if (!item) {
    return (
      <RateClient
        raterId={session.raterId}
        isAdmin={session.isAdmin}
        done={true}
        total={total || 0}
        ratedCount={done || 0}
      />
    );
  }

  const imageUrl = item.storage_path
    ? supabaseAdmin.storage
        .from(STORAGE_BUCKET)
        .getPublicUrl(item.storage_path).data.publicUrl
    : "";
  const previewImageUrl = getPreviewImageUrl(imageUrl);

  return (
      <RateClient
        raterId={session.raterId}
        isAdmin={session.isAdmin}
        item={clientItem(item)}
        imageUrl={previewImageUrl}
      total={total || 0}
      ratedCount={done || 0}
    />
  );
}
