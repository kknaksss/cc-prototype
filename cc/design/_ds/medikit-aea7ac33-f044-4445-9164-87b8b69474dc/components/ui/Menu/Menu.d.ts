import * as React from 'react';

/**
 * Menu — from @medisolve-ai/medikit@1.4.0 (./src/ui/menu/menu.stories.tsx).
 */
export interface MenuProps {
  /** 메뉴 설정 배열 */
  menus: MenuConfig[];
  /** 현재 경로 (pathname) — 활성 메뉴 판별용 */
  currentPath: string;
  /** 로고 영역 (펼침 상태에서만 표시) */
  logo?: React.ReactNode;
  /** 링크 컴포넌트 (react-router Link 등) — 미지정 시 `<a>` 사용 */
  linkAs?: "symbol" | "object" | "map" | "filter" | "a" | "button" | "div" | "form" | "h2" | "h3" | "img" | "input" | "label" | "li" | "nav" | "ol" | (string & {}) /* +164 more */;
  /** 메뉴 클릭 핸들러 (SPA 라우팅 연결용) */
  onMenuClick?: (href: string, e: React.MouseEvent) => void;
  /** 열림 상태 변경 핸들러 */
  onOpenChange?: (open: boolean) => void;
  style?: React$1.CSSProperties;
  className?: string;
  id?: string;
  children?: React.ReactNode;
}

export declare const Menu: React.ComponentType<MenuProps>;
