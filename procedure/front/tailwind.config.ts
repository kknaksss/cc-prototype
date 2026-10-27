import type { Config } from 'tailwindcss';
import { medikitPreset } from '@medisolve-ai/medikit/tailwind';

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
    './node_modules/@medisolve-ai/medikit/dist/**/*.js',
  ],
  presets: [medikitPreset as Partial<Config>],
  theme: {
    extend: {
      // 시안이 쓰는 「heading-sm-600」(14px · 600) — medikit 1.4.0 FONT_SIZE 에 없어 상속 크기로 그려졌다(E2E #11). 같은 꼴로 채운다
      fontSize: { 'typo-heading-sm-600': ['14px', { fontWeight: '600', lineHeight: '1.5', letterSpacing: '0' }] },
    },
  },
};

export default config;
