"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Nav from "@/components/Nav";

const DIMENSIONS = [
  {
    name: "style_consistency_score",
    label: "形式风格一致性",
    desc: "图像整体是否符合目标传统视觉风格。请重点判断风格特征，不要只根据图像精致度、清晰度或个人审美喜好评分。",
  },
  {
    name: "element_accuracy_score",
    label: "对象元素准确性",
    desc: '图像是否准确呈现提示词要求的主要对象和关键元素。请重点判断"该有的东西是否出现、是否清楚、是否符合要求"。',
  },
  {
    name: "error_control_score",
    label: "干扰元素规避程度",
    desc: (
      <>
        图像是否避免了与任务不匹配、喧宾夺主或造成风格偏移的元素。
        <span className="text-red-600">
          分数越高，表示越好地规避了这类干扰元素。
        </span>
        此类元素包括现代建筑、赛博光效、写实摄影、西方骑士、超级英雄、随机彩色面具等明显
        <span className="text-red-600">不当元素</span>
        ，也包括不服务于当前任务、并导致图像偏离目标风格的
        <span className="text-red-600">泛中国元素</span>
        ，如花鸟装饰、宫廷人物、仙侠元素等。
      </>
    ),
  },
  {
    name: "overall_score",
    label: "整体评分",
    desc: "综合前三项判断本次生成任务的完成度。请同时考虑风格是否一致、对象是否准确、是否存在干扰元素，而不是只按图像好看程度或个人偏好评分。",
  },
];

export default function RateClient({
  raterId,
  isAdmin,
  done,
  item,
  imageUrl,
  total,
  ratedCount,
  allItems,
  ratedIds,
}: {
  raterId: string;
  isAdmin: boolean;
  done?: boolean;
  item?: {
    image_id: string;
    target_style: string;
    prompt_level: string;
    prompt_text: string;
    expected_elements?: string | null;
    forbidden_elements?: string | null;
  };
  imageUrl?: string;
  total: number;
  ratedCount: number;
  allItems: string[];
  ratedIds: Set<string>;
}) {
  const router = useRouter();
  const [scores, setScores] = useState<Record<string, number>>({});
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");

  const pct = total === 0 ? 0 : Math.round((ratedCount / total) * 100);

  if (done) {
    return (
      <div className="min-h-screen">
        <Nav raterId={raterId} isAdmin={isAdmin} />
        <main className="sr-container py-16 text-center">
          <div className="sr-seal mx-auto mb-6">完</div>
          <h2 className="text-3xl md:text-5xl sr-serif mb-4">
            您已完成全部图像评分。
          </h2>
          <p className="text-lg mb-2">感谢您的参与和支持。</p>
          <p className="text-[#5e5e5e] mb-12 leading-relaxed">
            本次评分结果将用于中国传统视觉风格 T2I 图像生成评价研究。
            <br />
            数据将匿名处理，仅用于研究分析。
          </p>
          <FeedbackForm />
        </main>
      </div>
    );
  }

  if (!item) return null;

  const promptText = (item.prompt_text || "")
    .replace(/^生成(一幅|一张|一副|一个)?/, "")
    .trim();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (Object.keys(scores).length < 4) {
      setMessage("每个维度都需选择 1-5 分");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/ratings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_id: item!.image_id,
          ...scores,
          comment,
        }),
      });
      if (res.ok) {
        router.refresh();
      } else {
        const data = await res.json();
        setMessage(data.error || "提交失败");
      }
    } catch {
      setMessage("网络错误");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Nav raterId={raterId} isAdmin={isAdmin} />
      <div className="flex flex-1 flex-col lg:flex-row">
        {/* Thumbnail sidebar */}
        <aside className="hidden lg:flex w-64 shrink-0 flex-col border-r border-[#c4c7c7]/25 bg-[#f4f4ef] overflow-y-auto max-h-[calc(100vh-73px)] sticky top-[73px]">
          <div className="p-4 border-b border-[#c4c7c7]/30">
            <h3 className="sr-label text-black">评测图片</h3>
            <p className="sr-label !text-[10px] !tracking-normal mt-2">
              {ratedCount}/{total} 已评
            </p>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {allItems.map((iid) => {
              const isRated = ratedIds.has(iid);
              const isCurrent = iid === item.image_id;
              return (
                <a
                  key={iid}
                  href={`/rate?image_id=${iid}`}
                  className={`flex items-center gap-2 px-3 py-2 text-xs border transition-colors ${
                    isCurrent
                      ? "border-black bg-[#e3e2e2]"
                      : isRated
                      ? "border-[#747878]/35 bg-white/40"
                      : "border-[#c4c7c7]/30 hover:bg-[#e8e8e3]"
                  }`}
                >
                  <span className="truncate flex-1">{iid}</span>
                  <span
                    className={`sr-label !text-[10px] !tracking-normal ${isRated ? "!text-[#1a1c19]" : "!text-[#858383]"}`}
                  >
                    {isRated ? "已评" : "未评"}
                  </span>
                </a>
              );
            })}
          </div>
        </aside>

        {/* Main */}
        <div className="flex-1 px-4 md:px-8 lg:px-12 py-5 md:py-8 min-w-0">
          <div className="max-w-4xl mx-auto mb-4 border-b border-[#c4c7c7]/30 pb-3">
            <span className="sr-label block mb-2">
              Target Style / 目标风格
            </span>
            <h2 className="text-2xl md:text-3xl sr-serif">
              {item.target_style} · {item.prompt_level} · {item.image_id}
            </h2>
          </div>

          {imageUrl && (
            <section className="max-w-4xl mx-auto mb-5">
              <div className="relative aspect-square md:aspect-[4/3] bg-[#eeeee9] flex items-center justify-center p-2 overflow-hidden">
              <img
                src={imageUrl}
                alt={item.image_id}
                  className="w-full h-full object-contain bg-white transition-transform duration-700 hover:scale-[1.01]"
              />
              </div>
            </section>
          )}

          <div className="max-w-4xl mx-auto flex flex-wrap justify-between items-center gap-4">
            <button
              className="text-[#5e5e5e] hover:text-black transition-colors text-sm"
              type="button"
              onClick={() => router.push("/profile")}
            >
              返回工作室
            </button>
            <div className="sr-label">
              已评 {ratedCount}/{total} ({pct}%)
            </div>
          </div>
        </div>

        {/* Rating sidebar */}
        <aside className="w-full lg:w-[420px] bg-[#f4f4ef]/70 border-t lg:border-t-0 lg:border-l border-[#c4c7c7]/25 p-4 md:p-8 lg:max-h-[calc(100vh-73px)] lg:sticky lg:top-[73px] overflow-y-auto">
          {/* Prompt box */}
          <div className="mb-6 p-4 bg-white border border-[#c4c7c7]/35">
            <p className="sr-label mb-2">目标风格</p>
            <p className="font-semibold mb-4">
              {item.target_style} · {item.prompt_level}
            </p>
            <p className="sr-label mb-2">提示词</p>
            <p className="text-sm italic text-[#5e5e5e] leading-relaxed">{promptText}</p>
          </div>

          <h3 className="text-2xl sr-serif mb-6 pb-4 border-b border-black/10">
            Rating Form / 评审表
          </h3>

          <form onSubmit={handleSubmit} className="space-y-8">
            {DIMENSIONS.map((dim) => (
              <div key={dim.name}>
                <label className="block mb-3">
                  <span className="font-semibold text-sm">{dim.label}</span>
                  <span className="block text-xs text-[#5e5e5e] mt-2 font-normal leading-relaxed">
                    {dim.desc}
                  </span>
                </label>
                <div className="flex gap-2">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <label
                      key={n}
                      className={`flex-1 h-10 border flex items-center justify-center cursor-pointer text-xs transition-colors ${
                        scores[dim.name] === n
                          ? "bg-black text-white border-black"
                          : "border-[#c4c7c7] hover:bg-[#e8e8e3]"
                      }`}
                    >
                      <input
                        type="radio"
                        name={dim.name}
                        value={n}
                        className="hidden"
                        checked={scores[dim.name] === n}
                        onChange={() =>
                          setScores({ ...scores, [dim.name]: n })
                        }
                        required
                      />
                      {n}
                    </label>
                  ))}
                </div>
              </div>
            ))}

            <div className="pt-6 border-t border-[#c4c7c7]/40">
              <h4 className="sr-label mb-3">
                备注 / 问题说明
              </h4>
              <textarea
                className="sr-textarea text-sm"
                placeholder="请在此输入对图片中存在问题的具体说明..."
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            </div>

            {message && (
              <p className="text-sm text-[#93000a] bg-[#ffdad6] p-3">
                {message}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="sr-button w-full"
            >
              {submitting ? "提交中..." : "提交评定"}
            </button>
          </form>
        </aside>
      </div>
    </div>
  );
}

function FeedbackForm() {
  const [fb, setFb] = useState("");
  const [sent, setSent] = useState(false);

  async function submitFb() {
    if (!fb.trim()) return;
    await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: fb }),
    });
    setSent(true);
  }

  return (
    <div className="max-w-md mx-auto text-left">
      <p className="sr-label mb-2">可选反馈</p>
      {sent ? (
        <p className="text-black">感谢您的反馈。</p>
      ) : (
        <>
          <textarea
            className="sr-textarea min-h-32 text-sm mb-4"
            placeholder="如有任何建议或想法，请在此留言..."
            value={fb}
            onChange={(e) => setFb(e.target.value)}
          />
          <button
            onClick={submitFb}
            className="sr-button w-full"
          >
            提交反馈并结束
          </button>
        </>
      )}
    </div>
  );
}
