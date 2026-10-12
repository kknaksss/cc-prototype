Badge from @medisolve-ai/medikit. Use via `window.MedisolveAiMedikit.Badge` (bundle loaded from the root `_ds_bundle.js`). Components expect the context this repo's `.storybook/preview` decorators provide (theme/i18n) — see README.md.

Variants (see `Badge.html`): Playground, 색상 변형, 결제 상태 예시, 커스텀 색상 오버라이드, 사이즈.

## Props

```ts
interface BadgeProps {
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
```

## Examples

```jsx
// Playground
export const Playground: Story = {};

// 색상 변형
export const Variants: Story = {
  name: "색상 변형",
  render: () => (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Badge variant="neutral">해지예약</Badge>
        <Badge variant="primary">구독중</Badge>
        <Badge variant="warning">체험 D-3</Badge>
        <Badge variant="danger">결제필요</Badge>
        <Badge variant="purple">체험</Badge>
      </div>
      <p className="text-typo-caption-md-400 text-ms-gray-600">
        warning(앰버)은 red보다 완만한 경고 — 무료체험 임박·저잔액 등
      </p>
    </div>
  ),
};

// 결제 상태 예시
export const BillingStatuses: Story = {
  name: "결제 상태 예시",
  render: () => (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="primary" dot>
        구독중
      </Badge>
      <Badge variant="purple">무료체험 D-7</Badge>
      <Badge variant="neutral">해지예약</Badge>
      <Badge variant="danger" dot>
        결제필요
      </Badge>
      <Badge variant="danger">이용종료</Badge>
      <Badge variant="primary">결제완료</Badge>
    </div>
  ),
};
```

### Playground

```jsx
/* Playground */ compose(S, "Playground")
```

### Variants

```jsx
/* 색상 변형 */ compose(S, "Variants")
```

### BillingStatuses

```jsx
/* 결제 상태 예시 */ compose(S, "BillingStatuses")
```

### CustomColor

```jsx
/* 커스텀 색상 오버라이드 */ compose(S, "CustomColor")
```

### Sizes

```jsx
/* 사이즈 */ compose(S, "Sizes")
```
