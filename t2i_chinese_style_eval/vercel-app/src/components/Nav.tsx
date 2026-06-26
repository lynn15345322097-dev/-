"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

export default function Nav({
  raterId,
  isAdmin,
}: {
  raterId: string;
  isAdmin: boolean;
}) {
  const pathname = usePathname();
  const router = useRouter();

  const active = "text-black border-b-2 border-black pb-1";
  const inactive = "text-[#5e5e5e] hover:text-black transition-colors";

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    router.push("/login");
  }

  return (
    <header className="sticky top-0 bg-[#fafaf5]/95 backdrop-blur border-b border-[#c4c7c7]/30 z-50">
      <div className="sr-container flex justify-between items-center py-3 md:py-4">
        <div className="flex items-center gap-4 md:gap-10 min-w-0">
          <h1 className="text-2xl md:text-4xl sr-serif tracking-tight shrink-0">
            SumiRate
          </h1>
          <nav className="flex gap-4 md:gap-8 text-sm md:text-base overflow-x-auto">
            <Link
              href="/profile"
              className={pathname === "/profile" ? active : inactive}
            >
              主页
            </Link>
            <Link
              href="/rate"
              className={pathname === "/rate" ? active : inactive}
            >
              评分
            </Link>
            {isAdmin && (
              <Link
                href="/admin"
                className={pathname === "/admin" ? active : inactive}
              >
                管理
              </Link>
            )}
          </nav>
        </div>
        <button
          onClick={logout}
          aria-label={`退出 ${raterId}`}
          className="sr-label whitespace-nowrap hover:text-black transition-colors"
        >
          退出
        </button>
      </div>
    </header>
  );
}
