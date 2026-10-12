import * as React from 'react';

/**
 * Header — from @medisolve-ai/medikit@1.4.0 (./src/ui/header/header.stories.tsx).
 */
export interface HeaderProps {
  /** 좌측 로고 (ReactNode) */
  logo?: React.ReactNode;
  /** 로고 클릭 핸들러 */
  onLogoClick?: () => void;
  /** 상단 네비게이션 메뉴 설정 */
  menus?: MenuConfig[];
  /** 현재 경로 (pathname) — 활성 메뉴 판별용 */
  currentPath?: string;
  /** 링크 컴포넌트 (react-router Link 등) — 미지정 시 `<a>` 사용 */
  linkAs?: "symbol" | "object" | "map" | "filter" | "a" | "button" | "div" | "form" | "h2" | "h3" | "img" | "input" | "label" | "li" | "nav" | "ol" | (string & {}) /* +164 more */;
  /** 메뉴 클릭 핸들러 */
  onMenuClick?: (href: string, e: React.MouseEvent) => void;
  /** 병원(지점) 이름 */
  branchName?: string;
  /** 사용자 이름 */
  userName?: string;
  /** 로그아웃 핸들러 */
  onLogout?: () => void;
  style?: React$1.CSSProperties;
  className?: string;
  id?: string;
  children?: React.ReactNode;
}

export declare const Header: React.ComponentType<HeaderProps>;
