import { createClient } from "@supabase/supabase-js";

type Table<Row, Insert = Partial<Row>, Update = Partial<Row>> = {
  Row: Row;
  Insert: Insert;
  Update: Update;
  Relationships: [];
};

type Database = {
  public: {
    Tables: {
      reviewers: Table<{
        reviewer_id: string;
        password_hash: string | null;
      }>;
      rating_items: Table<{
        image_id: string;
        target_style: string;
        prompt_level: string;
        prompt_text: string;
        expected_elements: string | null;
        forbidden_elements: string | null;
        storage_path: string | null;
      }>;
      metadata: Table<{
        image_id: string;
        job_id: string;
        model_id: string;
      }>;
      generation_jobs: Table<{
        job_id: string;
        prompt_id: string;
      }>;
      ratings: Table<{
        rating_id: string;
        evaluation_set_id: string;
        image_id: string;
        job_id: string;
        prompt_id: string;
        reviewer_id: string;
        blind_model_label: string;
        style_consistency_score: number | null;
        element_accuracy_score: number | null;
        error_control_score: number | null;
        overall_score: number | null;
        comment: string | null;
        error_tags: string[] | null;
        created_at: string;
        updated_at: string;
      }>;
      feedback: Table<{
        rater_id: string;
        content: string;
        created_at: string;
      }>;
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
};

let adminClient: ReturnType<typeof createClient<Database>> | null = null;

export function getSupabaseAdmin() {
  if (!adminClient) {
    const url = process.env.SUPABASE_URL;
    const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!url || !serviceRoleKey) {
      throw new Error("Missing Supabase server environment variables");
    }
    adminClient = createClient<Database>(url, serviceRoleKey, {
      auth: { persistSession: false },
    });
  }
  return adminClient;
}

export const EVALUATION_SET_ID = process.env.EVALUATION_SET_ID || "mvp_2026_06";
export const STORAGE_BUCKET = process.env.SUPABASE_STORAGE_BUCKET || "rating-images";
export const ADMIN_IDS = new Set(
  (process.env.ADMIN_IDS || "LYNN").split(",").filter(Boolean)
);

export const BLIND_MODEL_LABELS: Record<string, string> = {
  M01: "Model_A",
  M02: "Model_B",
  M03: "Model_C",
};

export function getPreviewImageUrl(publicUrl: string): string {
  if (!publicUrl) return "";
  const renderUrl = publicUrl.replace(
    "/storage/v1/object/public/",
    "/storage/v1/render/image/public/"
  );
  const separator = renderUrl.includes("?") ? "&" : "?";
  return `${renderUrl}${separator}width=960&quality=75`;
}
