import * as React from 'react';

/**
 * Button — from @medisolve-ai/medikit@1.4.0 (./src/ui/button/button.stories.tsx).
 * @replaces button
 */
export interface ButtonProps {
  isLoading?: boolean;
  variant?: "text" | "icon" | "solid" | "filled" | "outlined" | "fillOutlined";
  color?: "blue" | "red" | "yellow" | "black" | "gray";
  size?: "s" | "md" | "sm" | "xl" | "l" | "m" | "ss" | "lg";
  shape?: "circle" | "default" | "round";
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  style?: React$1.CSSProperties;
  className?: string;
  id?: string;
  children?: React.ReactNode;
  asChild?: boolean;
}

export declare const Button: React.ComponentType<ButtonProps>;
