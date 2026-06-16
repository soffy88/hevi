import './globals.css';
import type { Metadata } from 'next';
import { AuthProvider } from '@/components/AuthProvider';

export const metadata: Metadata = {
  title: 'hevi — AI 视频创作工作台',
  description: '无限画布 · AI 视频生成',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh" data-theme="professional">
      <body><AuthProvider>{children}</AuthProvider></body>
    </html>
  );
}
