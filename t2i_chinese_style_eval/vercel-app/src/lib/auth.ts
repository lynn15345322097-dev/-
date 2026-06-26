import { cookies } from "next/headers";
import { ADMIN_IDS, getSupabaseAdmin } from "./supabase";
import { createHash, createHmac, timingSafeEqual } from "crypto";

export const SESSION_COOKIE = "sr_session";
export const SESSION_MAX_AGE = 60 * 60 * 24;

type SessionPayload = {
  raterId: string;
  exp: number;
};

export function hashPassword(password: string): string {
  return createHash("sha256").update(password).digest("hex");
}

function sessionSecret(): string {
  const secret = process.env.SESSION_SECRET;
  if (!secret && process.env.NODE_ENV === "production") {
    throw new Error("SESSION_SECRET is required in production");
  }
  return secret || "dev-only-sumirate-session-secret";
}

function encode(value: string): string {
  return Buffer.from(value, "utf8").toString("base64url");
}

function decode(value: string): string {
  return Buffer.from(value, "base64url").toString("utf8");
}

function sign(payload: string): string {
  return createHmac("sha256", sessionSecret()).update(payload).digest("base64url");
}

function verifySignature(payload: string, signature: string): boolean {
  const expected = Buffer.from(sign(payload));
  const actual = Buffer.from(signature);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

export function createSessionCookieValue(raterId: string): string {
  const payload = encode(
    JSON.stringify({
      raterId,
      exp: Math.floor(Date.now() / 1000) + SESSION_MAX_AGE,
    } satisfies SessionPayload)
  );
  return `${payload}.${sign(payload)}`;
}

function parseSessionCookie(value: string | undefined): SessionPayload | null {
  if (!value) return null;
  const [payload, signature] = value.split(".");
  if (!payload || !signature || !verifySignature(payload, signature)) return null;
  try {
    const parsed = JSON.parse(decode(payload)) as SessionPayload;
    if (!parsed.raterId || !parsed.exp) return null;
    if (parsed.exp < Math.floor(Date.now() / 1000)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export async function getSession(): Promise<{
  raterId: string;
  isAdmin: boolean;
} | null> {
  const jar = await cookies();
  const session = parseSessionCookie(jar.get(SESSION_COOKIE)?.value);
  if (!session) return null;
  return { raterId: session.raterId, isAdmin: ADMIN_IDS.has(session.raterId) };
}

export async function requireLogin(): Promise<{
  raterId: string;
  isAdmin: boolean;
}> {
  const session = await getSession();
  if (!session) throw new Error("UNAUTHORIZED");
  return session;
}

export async function requireAdmin(): Promise<string> {
  const session = await requireLogin();
  if (!session.isAdmin) throw new Error("FORBIDDEN");
  return session.raterId;
}

export async function verifyLogin(
  raterId: string,
  password: string
): Promise<boolean> {
  const supabaseAdmin = getSupabaseAdmin();
  const { data } = await supabaseAdmin
    .from("reviewers")
    .select("password_hash")
    .eq("reviewer_id", raterId)
    .single();

  if (!data || !data.password_hash) return false;
  return hashPassword(password) === data.password_hash;
}
