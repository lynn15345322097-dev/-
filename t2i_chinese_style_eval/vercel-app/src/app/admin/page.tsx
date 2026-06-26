import { requireAdmin } from "@/lib/auth";
import { EVALUATION_SET_ID, getSupabaseAdmin } from "@/lib/supabase";
import AdminClient from "./AdminClient";

type ReviewerRow = { reviewer_id: string };
type RecentRow = { reviewer_id: string; image_id: string; created_at: string };
type FeedbackRow = { rater_id: string; content: string; created_at: string };

export default async function AdminPage() {
  const raterId = await requireAdmin().catch(() => null);
  if (!raterId) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-serif mb-2">403</h1>
          <p className="text-gray-500">Admin only</p>
        </div>
      </div>
    );
  }
  const supabaseAdmin = getSupabaseAdmin();

  const { count: total } = await supabaseAdmin
    .from("rating_items")
    .select("*", { count: "exact", head: true });

  const { count: done } = await supabaseAdmin
    .from("ratings")
    .select("*", { count: "exact", head: true })
    .eq("evaluation_set_id", EVALUATION_SET_ID);

  const { data: reviewersRaw } = await supabaseAdmin
    .from("ratings")
    .select("reviewer_id")
    .eq("evaluation_set_id", EVALUATION_SET_ID);

  const reviewers = (reviewersRaw || []) as ReviewerRow[];
  const activeRaterIds = [...new Set((reviewers || []).map((r) => r.reviewer_id))];

  const { data: reviewerStatsRaw } = await supabaseAdmin
    .from("ratings")
    .select("reviewer_id")
    .eq("evaluation_set_id", EVALUATION_SET_ID);

  const stats: Record<string, number> = {};
  const reviewerStats = (reviewerStatsRaw || []) as ReviewerRow[];
  (reviewerStats || []).forEach((r) => {
    stats[r.reviewer_id] = (stats[r.reviewer_id] || 0) + 1;
  });

  const { data: recentRaw } = await supabaseAdmin
    .from("ratings")
    .select("reviewer_id, image_id, created_at")
    .eq("evaluation_set_id", EVALUATION_SET_ID)
    .order("created_at", { ascending: false })
    .limit(5);
  const recent = (recentRaw || []) as RecentRow[];

  const { data: feedbackRaw } = await supabaseAdmin
    .from("feedback")
    .select("rater_id, content, created_at")
    .order("created_at", { ascending: false });
  const feedback = (feedbackRaw || []) as FeedbackRow[];

  return (
    <AdminClient
      raterId={raterId}
      total={total || 0}
      done={done || 0}
      activeRaters={activeRaterIds.length}
      reviewerStats={stats}
      recent={recent.map((r) => ({
        reviewer_id: r.reviewer_id,
        image_id: r.image_id,
        created_at: r.created_at,
      }))}
      feedback={feedback}
    />
  );
}
