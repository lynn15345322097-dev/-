"use client";

import { useRouter } from "next/navigation";
import Nav from "@/components/Nav";

export default function ProfileClient({
  raterId,
  isAdmin,
  total,
  done,
}: {
  raterId: string;
  isAdmin: boolean;
  total: number;
  done: number;
}) {
  const router = useRouter();
  const remaining = total - done;
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);

  return (
    <div className="min-h-screen">
      <Nav raterId={raterId} isAdmin={isAdmin} />
      <main className="sr-container py-10 md:py-14">
        <section className="mb-12 md:mb-16">
          <p className="sr-label mb-3">Reviewer Studio / 评审工作台</p>
          <h1 className="text-4xl md:text-6xl sr-serif mb-3">欢迎回来</h1>
          <p className="text-[#5e5e5e] text-base md:text-lg max-w-2xl leading-relaxed">
            已完成 {done} / {total} 项评分（{pct}%），剩余 {remaining} 项待评。
          </p>
        </section>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 md:gap-8 mb-12 md:mb-16">
          <div className="sr-ink-card p-8">
            <span className="sr-label relative z-10">
              总任务数
            </span>
            <div className="text-5xl sr-serif mt-4 relative z-10">{total}</div>
          </div>
          <div className="sr-ink-card p-8">
            <span className="sr-label relative z-10">
              已完成
            </span>
            <div className="text-5xl sr-serif mt-4 relative z-10">{done}</div>
          </div>
          <div className="sr-ink-card p-8">
            <span className="sr-label relative z-10">
              待处理
            </span>
            <div className="text-5xl sr-serif mt-4 text-[#ba1a1a] relative z-10">
              {remaining}
            </div>
          </div>
        </div>

        <div className="flex gap-4">
          <button
            onClick={() => router.push("/rate")}
            className="sr-button px-10"
          >
            {done > 0 ? "继续评分" : "开始评分"}
          </button>
        </div>
      </main>
    </div>
  );
}
