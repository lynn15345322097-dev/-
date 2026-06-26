import { NextRequest, NextResponse } from "next/server";
import {
  createSessionCookieValue,
  SESSION_COOKIE,
  SESSION_MAX_AGE,
  verifyLogin,
} from "@/lib/auth";

export async function POST(request: NextRequest) {
  const { rater_id, password } = await request.json();

  if (!rater_id || !password) {
    return NextResponse.json({ error: "编号和密码不能为空" }, { status: 400 });
  }

  const ok = await verifyLogin(rater_id, password);
  if (!ok) {
    return NextResponse.json({ error: "编号或密码错误" }, { status: 401 });
  }

  const response = NextResponse.json({ success: true });
  response.cookies.set(SESSION_COOKIE, createSessionCookieValue(rater_id), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
  response.cookies.set("rater_id", "", { httpOnly: true, path: "/", maxAge: 0 });
  return response;
}
