import * as React from 'react';

/**
 * Tabs — from @medisolve-ai/medikit@1.4.0 (./src/ui/tab/tab.stories.tsx).
 */
export interface TabsProps {
  tabs: Tab[];
  selectedTab: string;
  onSelectTab: (tab: string) => void;
  disabled?: boolean;
  style?: React$1.CSSProperties;
  className?: string;
  id?: string;
  children?: React.ReactNode;
}

export declare const Tabs: React.ComponentType<TabsProps>;
