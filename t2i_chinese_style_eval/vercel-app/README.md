# SumiRate Vercel App

This is the Vercel/Next.js version of the SumiRate subjective evaluation site.

## Responsibilities

- Next.js renders the login, reviewer profile, rating, and admin pages.
- Supabase stores reviewers, rating items, image metadata, feedback, and ratings.
- Supabase Storage serves blind evaluation images.
- The browser should only see blind labels and rating UI data, not raw model identities.

## Local Development

```bash
npm install
npm run dev -- --hostname 127.0.0.1 --port 3064
```

Open `http://127.0.0.1:3064`.

## Required Environment Variables

Use `env.example` as the template. Do not commit real secrets.

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_STORAGE_BUCKET`
- `EVALUATION_SET_ID`
- `ADMIN_IDS`
- `SESSION_SECRET`

## Checks Before Deploy

```bash
npm run lint
npm run build
```

The service role key must stay server-side only. Never expose it as a `NEXT_PUBLIC_*` variable.
