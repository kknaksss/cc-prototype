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
};

export default config;
