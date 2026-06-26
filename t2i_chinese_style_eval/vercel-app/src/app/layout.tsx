import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SumiRate | 墨评",
  description: "中国传统视觉风格 T2I 图像生成评价系统",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Work+Sans:wght@300;400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen bg-[#fafaf5] text-[#1a1c19] font-sans">
        {children}
      </body>
    </html>
  );
}
