Header from @medisolve-ai/medikit. Use via `window.MedisolveAiMedikit.Header` (bundle loaded from the root `_ds_bundle.js`). Components expect the context this repo's `.storybook/preview` decorators provide (theme/i18n) — see README.md.

Variants (see `Header.html`): Default, With Logo, With Menu.

## Props

```ts
interface HeaderProps {
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
```

## Examples

```jsx
// Default
export const Default: Story = {
  render: () => {
    const [currentPath, setCurrentPath] = useState('/ai/guide-dashboard');

    return (
      <Header
        menus={menus}
        currentPath={currentPath}
        onMenuClick={(href, e) => {
          e.preventDefault();
          setCurrentPath(href);
        }}
        branchName="서울본사 메디솔브점"
        userName="홍길동"
        onLogout={() => alert('로그아웃')}
      />
    );
  },
};

// With Logo
export const WithLogo: Story = {
  render: () => (
    <Header
      logo={<span className="text-typo-title-md-500 text-primary">centurion say</span>}
      onLogoClick={() => alert('로고 클릭')}
      branchName="서울본사 메디솔브점"
      userName="홍길동"
      onLogout={() => alert('로그아웃')}
    />
  ),
};

// With Menu
export const WithMenu: Story = {
  render: () => {
    const [currentPath, setCurrentPath] = useState('/ai/guide-dashboard');

    const handleNavigate = (href: string, e: React.MouseEvent) => {
      e.preventDefault();
      setCurrentPath(href);
    };

    return (
      <div className="flex flex-col h-[600px] border border-ms-gray-300 rounded-[8px] overflow-hidden">
        <Header
          menus={menus}
          currentPath={currentPath}
          onMenuClick={handleNavigate}
          branchName="서울본사"
          userName="관리자"
          onLogout={() => alert('로그아웃')}
        />
        <div className="flex flex-1 overflow-hidden">
          <Menu
            menus={menus}
            currentPath={currentPath}
            logo={
              <span className="text-typo-title-md-500 text-primary">centurion say</span>
            }
            onMenuClick={handleNavigate}
          />
          <div className="flex-1 bg-ms-gray-100 p-[42px]">
            <p className="text-typo-heading-md-500 text-ms-gray-700">메인 콘텐츠 영역</p>
            <p className="text-typo-body-400 text-ms-gray-600 mt-2">
              currentPath: {currentPath}
            </p>
          </div>
        </div>
      </div>
    );
  },
};
// …
```

### Default

```jsx
/* Default */ compose(S, "Default")
```

### WithLogo

```jsx
/* With Logo */ compose(S, "WithLogo")
```

### WithMenu

```jsx
/* With Menu */ compose(S, "WithMenu")
```
