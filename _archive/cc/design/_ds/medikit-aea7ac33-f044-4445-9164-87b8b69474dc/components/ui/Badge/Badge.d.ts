import * as React from 'react';

/**
 * Badge — from @medisolve-ai/medikit@1.4.0 (./src/ui/badge/badge.stories.tsx).
 */
export interface BadgeProps {
  /** 색상 변형 — medikit 기본 토큰에 매핑 (success=primary, warning=danger로 흡수). 팔레트 밖 커스텀 색이 필요하면 className으로 오버라이드 (예: className="bg-[ */
  variant?: "neutral" | "primary" | "warning" | "danger" | "purple";
  size?: "md" | "sm";
  /** 좌측 상태 점(dot) 표시 — 헤더 상태칩 형태. 색은 텍스트색을 따름 */
  dot?: boolean;
  style?: React$1.CSSProperties;
  className?: string;
  id?: string;
  children?: React.ReactNode;
}

export declare const Badge: React.ComponentType<BadgeProps>;
