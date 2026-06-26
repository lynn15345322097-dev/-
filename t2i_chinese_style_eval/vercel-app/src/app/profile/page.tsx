import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth";
import { EVALUATION_SET_ID, getSupabaseAdmin } from "@/lib/supabase";
import ProfileClient from "./ProfileClient";

export default async function ProfilePage() {
  const session = await getSession();
  if (!session) redirect("/login");
  const supabaseAdmin = getSupabaseAdmin();

  const { count: total } = await supabaseAdmin
    .from("rating_items")
    .select("*", { count: "exact", head: true });

  const { count: done } = await supabaseAdmin
    .from("ratings")
    .select("*", { count: "exact", head: true })
    .eq("evaluation_set_id", EVALUATION_SET_ID)
    .eq("reviewer_id", session.raterId);

  return (
    <ProfileClient
      raterId={session.raterId}
      isAdmin={session.isAdmin}
      total={total || 0}
      done={done || 0}
    />
  );
}
