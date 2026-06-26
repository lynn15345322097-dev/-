-- SumiRate long-term evaluation database schema for Supabase/Postgres.
-- Apply this in Supabase SQL editor or via the Supabase migration tool.

create table if not exists prompts (
    prompt_id text primary key,
    target_style text not null,
    prompt_level text not null,
    prompt_text text not null,
    expected_elements text,
    forbidden_elements text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists models (
    model_id text primary key,
    model_name text,
    provider text,
    notes text,
    created_at timestamptz not null default now()
);

create table if not exists evaluation_sets (
    evaluation_set_id text primary key,
    name text not null,
    description text,
    status text not null default 'active' check (status in ('draft', 'active', 'closed', 'archived')),
    created_at timestamptz not null default now()
);

create table if not exists model_blind_labels (
    evaluation_set_id text not null references evaluation_sets(evaluation_set_id) on delete cascade,
    model_id text not null references models(model_id) on delete cascade,
    blind_model_label text not null,
    created_at timestamptz not null default now(),
    primary key (evaluation_set_id, model_id),
    unique (evaluation_set_id, blind_model_label)
);

create table if not exists generation_jobs (
    job_id text primary key,
    prompt_id text not null references prompts(prompt_id) on delete restrict,
    model_id text not null references models(model_id) on delete restrict,
    replicate_idx integer,
    seed bigint,
    status text not null,
    attempts integer,
    original_prompt text not null,
    revised_prompt text,
    revision_reason text,
    raw_image_path text,
    error_code text,
    error_message text,
    timeout_sec integer,
    safety_blocked boolean,
    created_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz
);

create table if not exists rating_items (
    image_id text primary key,
    evaluation_set_id text not null references evaluation_sets(evaluation_set_id) on delete restrict,
    job_id text not null references generation_jobs(job_id) on delete restrict,
    blind_filename text not null,
    blind_image_path text not null,
    target_style text not null,
    prompt_level text not null,
    prompt_text text not null,
    expected_elements text,
    forbidden_elements text,
    image_width integer,
    image_height integer,
    generated_at timestamptz,
    created_at timestamptz not null default now(),
    unique (evaluation_set_id, job_id)
);

create table if not exists reviewers (
    reviewer_id text primary key,
    display_name text not null,
    password_hash text,
    role text not null default 'reviewer' check (role in ('reviewer', 'admin')),
    active boolean not null default true,
    created_at timestamptz not null default now()
);

create table if not exists ratings (
    rating_id text primary key,
    evaluation_set_id text not null references evaluation_sets(evaluation_set_id) on delete restrict,
    image_id text not null references rating_items(image_id) on delete restrict,
    job_id text not null references generation_jobs(job_id) on delete restrict,
    prompt_id text not null references prompts(prompt_id) on delete restrict,
    reviewer_id text not null references reviewers(reviewer_id) on delete restrict,
    blind_model_label text not null,
    style_consistency_score integer not null check (style_consistency_score between 1 and 5),
    element_accuracy_score integer not null check (element_accuracy_score between 1 and 5),
    error_control_score integer not null check (error_control_score between 1 and 5),
    overall_score integer not null check (overall_score between 1 and 5),
    error_tags text,
    comment text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (evaluation_set_id, image_id, reviewer_id)
);

create table if not exists feedback (
    feedback_id bigserial primary key,
    reviewer_id text references reviewers(reviewer_id) on delete set null,
    content text not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_generation_jobs_prompt_id on generation_jobs(prompt_id);
create index if not exists idx_generation_jobs_model_id on generation_jobs(model_id);
create index if not exists idx_rating_items_set_id on rating_items(evaluation_set_id);
create index if not exists idx_rating_items_job_id on rating_items(job_id);
create index if not exists idx_ratings_reviewer_id on ratings(reviewer_id);
create index if not exists idx_ratings_image_id on ratings(image_id);
create index if not exists idx_ratings_set_reviewer on ratings(evaluation_set_id, reviewer_id);

create or replace view rating_export as
select
    r.reviewer_id,
    r.job_id,
    r.prompt_id,
    r.blind_model_label,
    r.style_consistency_score,
    r.element_accuracy_score,
    r.error_control_score,
    r.overall_score,
    r.error_tags,
    r.comment,
    r.created_at
from ratings r
order by r.created_at, r.reviewer_id, r.image_id;
