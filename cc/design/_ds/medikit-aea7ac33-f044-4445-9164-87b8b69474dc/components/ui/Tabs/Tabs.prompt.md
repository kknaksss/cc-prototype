Tabs from @medisolve-ai/medikit. Use via `window.MedisolveAiMedikit.Tabs` (bundle loaded from the root `_ds_bundle.js`). Components expect the context this repo's `.storybook/preview` decorators provide (theme/i18n) — see README.md.

Variants (see `Tabs.html`): Default, Disabled.

## Props

```ts
interface TabsProps {
  tabs: Tab[];
  selectedTab: string;
  onSelectTab: (tab: string) => void;
  disabled?: boolean;
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
    const [selected, setSelected] = useState('monitoring');
    return (
      <Tabs tabs={sampleTabs} selectedTab={selected} onSelectTab={setSelected} />
    );
  },
};

// Disabled
export const Disabled: Story = {
  render: () => {
    const [selected, setSelected] = useState('monitoring');
    return (
      <Tabs tabs={sampleTabs} selectedTab={selected} onSelectTab={setSelected} disabled />
    );
  },
};
```

### Default

```jsx
/* Default */ compose(S, "Default")
```

### Disabled

```jsx
/* Disabled */ compose(S, "Disabled")
```
