import type { Metadata } from 'next';
import 'pretendard/dist/web/variable/pretendardvariable.css';
import '@medisolve-ai/medikit/styles';
import './styles/ceramique-theme.css';
import './styles/medikit-patches.css';
import './globals.css';

export const metadata: Metadata = {
  title: 'Céramique 명동점',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" data-product="ceramique">
      <body>{children}</body>
    </html>
  );
}
