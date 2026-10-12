Menu from @medisolve-ai/medikit. Use via `window.MedisolveAiMedikit.Menu` (bundle loaded from the root `_ds_bundle.js`). Components expect the context this repo's `.storybook/preview` decorators provide (theme/i18n) — see README.md.

Variants (see `Menu.html`): Default, Collapsed, With Storage Key, Controlled.

## Props

```ts
interface MenuProps {
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
```

## Examples

```jsx
// Default
export const Default: Story = {
  render: () => (
    <div className="flex h-[600px] border border-ms-gray-300 rounded-[8px] overflow-hidden">
      <Menu
        menus={menuConfig}
        currentPath="/ai/guide-dashboard"
        logo={
          <span className="text-typo-title-md-500 text-primary">centurion say</span>
        }
        onMenuClick={(href, e) => {
          e.preventDefault();
          alert(`navigate → ${href}`);
        }}
      />
      <div className="flex-1 bg-ms-gray-100 p-[42px]">
        <p className="text-typo-heading-md-500 text-ms-gray-700">메인 콘텐츠 영역</p>
        <p className="text-typo-body-400 text-ms-gray-600 mt-2">
          currentPath: /ai/guide-dashboard
        </p>
      </div>
    </div>
  ),
};

// Collapsed
export const Collapsed: Story = {
  render: () => (
    <div className="flex h-[600px] border border-ms-gray-300 rounded-[8px] overflow-hidden">
      <Menu
        menus={menuConfig}
        currentPath="/ai/guide-management"
        defaultOpen={false}
        onMenuClick={(_href, e) => {
          e.preventDefault();
        }}
      />
      <div className="flex-1 bg-ms-gray-100 p-[42px]">
        <p className="text-typo-heading-md-500 text-ms-gray-700">
          접힌 상태 — 아이콘 호버 시 툴팁 표시
        </p>
      </div>
    </div>
  ),
};

// With Storage Key
export const WithStorageKey: Story = {
  render: () => {
    const [path, setPath] = useState('/monitoring/dashboard');

    return (
      <div className="flex h-[600px] border border-ms-gray-300 rounded-[8px] overflow-hidden">
        <Menu
          menus={menuConfig}
          currentPath={path}
          storageKey="menu-state"
          logo={
            <span className="text-typo-title-md-500 text-primary">centurion say</span>
          }
          onMenuClick={(href, e) => {
            e.preventDefault();
            setPath(href);
          }}
        />
        <div className="flex-1 bg-ms-gray-100 p-[42px]">
          <p className="text-typo-heading-md-500 text-ms-gray-700">
            storageKey 모드 — 새로고침해도 열림/닫힘 상태 유지
          </p>
          <p className="text-typo-body-400 text-ms-gray-600 mt-2">
            currentPath: {path}
          </p>
        </div>
      </div>
    );
  },
};
```

### Default

```jsx
/* Default */ compose(S, "Default")
```

### Collapsed

```jsx
/* Collapsed */ compose(S, "Collapsed")
```

### WithStorageKey

```jsx
/* With Storage Key */ compose(S, "WithStorageKey")
```

### Controlled

```jsx
/* Controlled */ compose(S, "Controlled")
```
