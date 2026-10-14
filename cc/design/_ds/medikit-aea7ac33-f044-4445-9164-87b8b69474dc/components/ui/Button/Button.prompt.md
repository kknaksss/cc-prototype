Button from @medisolve-ai/medikit. Use via `window.MedisolveAiMedikit.Button` (bundle loaded from the root `_ds_bundle.js`). Components expect the context this repo's `.storybook/preview` decorators provide (theme/i18n) — see README.md.

Variants (see `Button.html`): Default, All Variants, Shapes, All Sizes, Variants Colors, States, Icons.

## Props

```ts
interface ButtonProps {
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
```

## Examples

```jsx
// Default
export const Default: Story = {
  args: { children: "버튼" },
};

type Variant =
  | "solid"
  | "filled"
  | "outlined"
  | "text"
  | "icon"
  | "fillOutlined";
type Color = "blue" | "red" | "black" | "gray";

// All Variants
export const AllVariants: Story = {
  render: () => {
    const lgCombos: { variant: Variant; color: Color; label: string }[] = [
      { variant: "solid", color: "blue", label: "Solid / Blue" },
      { variant: "filled", color: "blue", label: "Filled / Blue" },
      { variant: "outlined", color: "black", label: "Outlined / Black" },
      { variant: "outlined", color: "blue", label: "Outlined / Blue" },
      { variant: "filled", color: "red", label: "Filled / Red" },
    ];

    const smCombos: { variant: Variant; color: Color; label: string }[] = [
      { variant: "outlined", color: "black", label: "Outlined / Black" },
      { variant: "outlined", color: "blue", label: "Outlined / Sub-Blue" },
      { variant: "outlined", color: "red", label: "Outlined / Red" },
    ];

    return (
      <div className="flex flex-col gap-[48px]">
        {/* LG */}
        <div>
          <h2 className="text-typo-title-md-500 text-ms-black mb-[16px]">
            Button_L
          </h2>
          <table className="border-collapse">
            <thead>
              <tr>
                <th className="text-left p-[8px] text-typo-body-500 text-ms-gray-700 w-[140px]" />
                <th className="text-center p-[8px] text-typo-body-500 text-ms-gray-700 w-[160px]">
                  Default
                </th>
                <th className="text-center p-[8px] text-typo-body-500 text-ms-gray-700 w-[160px]">
                  Disabled
                </th>
                <th className="text-center p-[8px] text-typo-body-500 text-ms-gray-700 w-[160px]">
                  Progress
                </th>
              </tr>
            </thead>
            <tbody>
              {lgCombos.map(({ variant, color, label }) => (
// …

// Shapes
export const Shapes: Story = {
  render: () => (
    <div className="flex flex-col gap-[24px]">
      {(["default", "round", "circle"] as const).map((shape) => (
        <div key={shape} className="flex items-center gap-[12px]">
          <span className="w-[80px] text-typo-body-400 text-ms-gray-600">
            {shape}
          </span>
          <Button shape={shape} size="lg">
            {shape === "circle" ? "O" : "텍스트"}
          </Button>
          <Button shape={shape} size="md">
            {shape === "circle" ? "O" : "텍스트"}
          </Button>
          <Button shape={shape} size="sm">
            {shape === "circle" ? "O" : "텍스트"}
          </Button>
        </div>
      ))}
    </div>
  ),
};

/** 신규 canonical(xl/l/m/s/ss) + 레거시 alias(lg/md/sm, @deprecated) 높이 비교 */
```

### Default

```jsx
/* Default */ compose(S, "Default")
```

### AllVariants

```jsx
/* All Variants */ compose(S, "AllVariants")
```

### Shapes

```jsx
/* Shapes */ compose(S, "Shapes")
```

### AllSizes

```jsx
/* All Sizes */ compose(S, "AllSizes")
```

### VariantsColors

```jsx
/* Variants Colors */ compose(S, "VariantsColors")
```

### States

```jsx
/* States */ compose(S, "States")
```

### Icons

```jsx
/* Icons */ compose(S, "Icons")
```
