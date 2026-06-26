"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [raterId, setRaterId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rater_id: raterId, password }),
      });
      if (res.ok) {
        router.push("/profile");
      } else {
        const data = await res.json();
        setError(data.error || "登录失败");
      }
    } catch {
      setError("网络错误");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="text-center mb-10">
          <div className="sr-seal mx-auto mb-5">
            墨
          </div>
          <h1 className="text-5xl sr-serif tracking-tight">SumiRate</h1>
          <p className="sr-label mt-3">
            传统视觉风格评分系统
          </p>
        </div>

        <div className="sr-panel-white p-8 shadow-[0_24px_80px_rgba(0,0,0,0.04)]">
          <h2 className="text-2xl sr-serif mb-6 pb-4 border-b border-[#c4c7c7]/30">
            进入工作室
          </h2>

          <form onSubmit={handleSubmit} className="space-y-6">
            {error && (
              <p className="text-sm text-[#93000a] bg-[#ffdad6] p-3">{error}</p>
            )}

            <div>
              <label className="sr-label block mb-2">
                评审者编号
              </label>
              <input
                className="sr-input"
                placeholder="请输入审查者编号"
                value={raterId}
                onChange={(e) => setRaterId(e.target.value)}
                required
              />
            </div>

            <div>
              <label className="sr-label block mb-2">
                通行令牌
              </label>
              <input
                className="sr-input"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="sr-button w-full"
            >
              {loading ? "认证中..." : "进入工作室"}
            </button>
          </form>
        </div>
      </div>
    </main>
  );
}
