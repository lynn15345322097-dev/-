"use client";

import Nav from "@/components/Nav";

export default function AdminClient({
  raterId,
  total,
  done,
  activeRaters,
  reviewerStats,
  recent,
  feedback,
}: {
  raterId: string;
  total: number;
  done: number;
  activeRaters: number;
  reviewerStats: Record<string, number>;
  recent: { reviewer_id: string; image_id: string; created_at: string }[];
  feedback: { rater_id: string; content: string; created_at: string }[];
}) {
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);
  const remaining = total - done;

  return (
    <div className="min-h-screen">
      <Nav raterId={raterId} isAdmin={true} />
      <main className="sr-container py-8 md:py-12 space-y-10 md:space-y-12">
        <div>
          <p className="sr-label mb-3">Admin Archive / 管理后台</p>
          <h2 className="text-3xl md:text-5xl sr-serif">评分管理概览</h2>
          <p className="text-[#5e5e5e] text-sm mt-3">
            共 {total} 张评测图片，{activeRaters} 位评审者参与
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 md:gap-8">
          <div className="md:col-span-2 p-6 md:p-8 sr-panel-white">
            <div className="flex justify-between mb-8">
              <div>
                <h3 className="sr-serif text-2xl">完成进度</h3>
                <p className="text-xs text-[#5e5e5e] mt-2">
                  共 {total} 张评测图片，{activeRaters} 位评审者参与
                </p>
              </div>
              <span className="text-4xl sr-serif">{pct}%</span>
            </div>
            <div className="h-32 flex items-end gap-3">
              {Object.entries(reviewerStats).map(([id, n], i) => {
                const h = Math.max(5, Math.round((n / total) * 100));
                return (
                  <div
                    key={id}
                    className="flex-1 bg-black hover:opacity-80 transition-all"
                    style={{
                      height: `${h}%`,
                      opacity: 0.3 + (i % 7) * 0.1,
                    }}
                    title={`${id}: ${n}`}
                  />
                );
              })}
            </div>
            <div className="flex justify-between mt-3 text-xs text-[#858383]">
              {Object.keys(reviewerStats)
                .slice(0, 7)
                .map((id) => (
                  <span key={id}>{id.slice(0, 3)}</span>
                ))}
            </div>
          </div>

          <div className="p-6 md:p-8 sr-ink-card flex flex-col justify-between">
            <div>
              <p className="sr-label relative z-10">
                活跃评审者
              </p>
              <h4 className="text-5xl sr-serif mt-4 relative z-10">{activeRaters}</h4>
            </div>
            <div className="space-y-3 mt-6 relative z-10">
              <div className="flex justify-between text-sm border-b border-[#c4c7c7]/35 pb-2">
                <span className="text-[#5e5e5e]">已评图片</span>
                <span>{done}</span>
              </div>
              <div className="flex justify-between text-sm border-b border-[#c4c7c7]/35 pb-2">
                <span className="text-[#5e5e5e]">剩余待评</span>
                <span>{remaining}</span>
              </div>
            </div>
          </div>
        </div>

        <section>
          <h3 className="sr-serif text-2xl mb-4">评审者</h3>
          <div className="overflow-x-auto sr-panel-white">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-[#c4c7c7]/30">
                  <th className="py-3 px-4 sr-label">
                    评审员
                  </th>
                  <th className="py-3 px-4 sr-label text-center">
                    样本总数
                  </th>
                  <th className="py-3 px-4 sr-label text-right">
                    完成进度
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#c4c7c7]/20">
                {Object.entries(reviewerStats).map(([id, n]) => (
                  <tr key={id} className="hover:bg-[#f4f4ef]">
                    <td className="py-4 px-4 flex items-center gap-3">
                      <div className="w-8 h-8 border border-[#c4c7c7]/50 bg-[#f4f4ef] flex items-center justify-center text-sm sr-serif">
                        {id[0].toUpperCase()}
                      </div>
                      <span>{id}</span>
                    </td>
                    <td className="py-4 px-4 text-center text-sm">{n}</td>
                    <td className="py-4 px-4 text-right">
                      <span className="px-2 py-0.5 bg-[#f4f4ef] text-xs">
                        {Math.round((n / total) * 100)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 pt-8 border-t border-[#c4c7c7]/35">
          <section>
            <h3 className="sr-serif text-2xl mb-4">最近动态</h3>
            <div className="space-y-4">
              {recent.length > 0 ? (
                recent.map((r, i) => (
                  <div key={i} className="flex gap-3">
                    <div className="w-0.5 bg-[#c4c7c7]" />
                    <div>
                      <p className="text-sm">
                        {r.reviewer_id} 评了 {r.image_id}
                      </p>
                      <p className="text-xs text-[#858383]">
                        {new Date(r.created_at).toLocaleString()}
                      </p>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-sm text-[#858383]">暂无评分记录</p>
              )}
            </div>
          </section>

          {feedback.length > 0 && (
            <section>
              <h3 className="sr-serif text-2xl mb-4">评审者反馈</h3>
              <div className="space-y-4">
                {feedback.map((fb, i) => (
                  <div
                    key={i}
                    className="p-4 bg-white border border-[#c4c7c7]/30"
                  >
                    <p className="text-xs text-[#858383] mb-2">
                      {fb.rater_id} ·{" "}
                      {new Date(fb.created_at).toLocaleString()}
                    </p>
                    <p className="text-sm">{fb.content}</p>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
