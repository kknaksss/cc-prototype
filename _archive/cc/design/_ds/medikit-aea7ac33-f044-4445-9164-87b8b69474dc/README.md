# Building with medikit (@medisolve-ai/medikit)

medikit is a **Tailwind-preset design system** for MediSolve products (Say / Bay / Admin). Components are real compiled React parts on `window.MedisolveAiMedikit.*`; you style your own layout glue with medikit's Tailwind token classes. Every color/spacing/typography value below is a real class in the shipped stylesheet — use these names, do not invent hex values or ad-hoc scales.

## Setup — no provider, but pick a brand

There is **no theme provider or context wrapper**. Components render standalone — import and use directly. The design tokens live as CSS variables (`--ms-*`) on `:root`, and the Tailwind classes below resolve to them.

**Brand color via `data-product`.** The default `primary` is MediSolve blue (`#476cff`). To brand a screen for a specific product, set `data-product` on the root element — it re-points `primary` (and its shades) to that product's color. Every component and `text-primary`/`bg-primary` class follows automatically:

```jsx
// Charty screens → deep violet (#6f21ff). Wrap the root once:
<div data-product="charty">
  {/* everything here renders in Charty brand color */}
  <Button variant="solid" color="blue">저장</Button>
</div>
```

Supported: `data-product="charty"` (violet `#6f21ff`), `"say"` (`#5442ff`), `"bay"` (`#23a0ff`), `"watch"` (cyan `#00ace2`), `"selly"` (magenta `#a300b8`), `"linky"` (teal `#20c8d6`), `"studio"` (purple `#5000af`). Omit it for default blue. **When designing for Charty, always wrap the root in `data-product="charty"`.**

## The styling idiom — medikit's Tailwind vocabulary

Style your layout with these **real** classes (utility system, not props):

**Colors** (as `text-*` / `bg-* / border-*`):
- Brand primary: `primary` (+ `primary-100`, `primary-300`, `primary-500`) — e.g. `text-primary`, `bg-primary`, `bg-primary-100`
- Alert/danger: `red` (+ `red-100/300/500`) · Success: `success` · Accent: `purple` (+ `purple-100/500`)
- Neutrals: `ms-gray-100` … `ms-gray-800` (e.g. `text-ms-gray-600` for secondary text, `bg-ms-gray-100` for subtle fills), plus `ms-black`, `ms-white`

**Typography** — `text-typo-<category>-<size>-<weight>`:
- Categories: `headline-lg`, `headline-md`, `title-lg`, `title-md`, `title-sm`, `heading-md`, `heading-sm`, `body`, `caption-md`, `meta-sm`
- Weights: `-600` (bold), `-500` (medium), `-400` (regular)
- Examples: `text-typo-title-md-600`, `text-typo-body-400`, `text-typo-caption-md-500`. The `body` category omits size (`text-typo-body-600/500/400`).

**Radius**: standard Tailwind `rounded-*`, `rounded-full` (pills/circles are common). **Shadows**: `shadow-pop-over`, `shadow-pop-over-more`, `shadow-accordion`. **Motion**: `animate-spin-once`, `animate-accordion-down/up`.

**Font**: Pretendard ships with the system — all text renders in it automatically; do not set a font-family.

## Where the truth lives

- Read `_ds_bundle.css` for the exact token → class definitions before styling.
- Each component has a `<Name>.prompt.md` (usage + variants) and `<Name>.d.ts` (the exact prop API) under `components/`. Read these before composing a component — props carry the design language (e.g. Button's `variant`/`color`/`size`, Input's `error`/size props).

## One idiomatic example

```jsx
const { Button, Input, Label } = window.MedisolveAiMedikit;
<div className="flex flex-col gap-4 p-6 bg-ms-white rounded-lg shadow-pop-over">
  <h2 className="text-typo-title-md-600 text-ms-gray-800">환자 등록</h2>
  <div className="flex flex-col gap-1.5">
    <Label required>이름</Label>
    <Input placeholder="이름을 입력하세요" />
  </div>
  <div className="flex justify-end gap-2">
    <Button variant="outlined" color="gray">취소</Button>
    <Button variant="solid" color="blue">저장</Button>
  </div>
</div>
```

Component controls come from medikit; layout, spacing, and text styling come from the classes above. That keeps every screen on-brand and 1:1 with shippable code.

# MedisolveAiMedikit (@medisolve-ai/medikit@1.4.0)

This design system is the published @medisolve-ai/medikit React library, bundled as a single
browser global. All 42 components are the real upstream code.

## Where things are

- `_ds_bundle.js` — the whole-DS bundle at the project root; loads every component to `window.MedisolveAiMedikit`. First line is a `/* @ds-bundle: … */` metadata header.
- `styles.css` — the single stylesheet entry: it `@import`s the tokens, fonts, and component styles (`_ds_bundle.css`). Link this one file.
- `components/<group>/<Name>/<Name>.prompt.md` (example JSX + variants), `<Name>.d.ts` (types), `<Name>.html` (variant grid).
- `tokens/*.css` — CSS custom properties, names verbatim from upstream.
- `fonts/` — `@font-face` files + `fonts.css` (when the package ships fonts).

For a specific component, `read_file("components/<group>/<Name>/<Name>.prompt.md")`.

## Loading

Add these two lines to your page once (React must be on the page first):

```html
<link rel="stylesheet" href="styles.css">
<script src="_ds_bundle.js"></script>
```

Components are then available at `window.MedisolveAiMedikit.*`. Mount into a dedicated child node (e.g. `<div id="ds-root">`), not the host page's own React root, so the two trees don't collide:

```jsx
const { Accordion } = window.MedisolveAiMedikit;
ReactDOM.createRoot(document.getElementById('ds-root')).render(<Accordion />);
```

This DS's storybook wraps every story in decorators from `.storybook/preview`
(bundled for the preview cards as `_vendor/preview-decorators.js`). Components
likely need equivalent context — theme/i18n providers — in your tree too. The
exact chain hasn't been distilled into config, so check the DS's documented
provider setup before composing.

## Tokens

103 CSS custom properties from @medisolve-ai/medikit. Names are
preserved verbatim from upstream. They are declared inside `_ds_bundle.css` (this DS ships one compiled stylesheet rather than separate token files).

- **color** (18): `--tw-border-spacing-x`, `--tw-border-spacing-y`, `--tw-ring-offset-color`, …
- **spacing** (3): `--tw-ring-inset`, `--tw-space-y-reverse`, `--tw-space-x-reverse`
- **shadow** (7): `--tw-ring-offset-shadow`, `--tw-ring-shadow`, `--tw-shadow`, …
- **other** (75): `--tw-translate-x`, `--tw-translate-y`, `--tw-rotate`, …

## Components

### ui
- `Accordion`
- `ActionButton`
- `AppTabs`
- `AsyncBoundary`
- `Badge`
- `Banner`
- `Button`
- `Calendar`
- `Card`
- `Checkbox`
- `Chip`
- `ComboBox`
- `Command`
- `DatePicker`
- `DeferredComponent`
- `Dialog`
- `Divider`
- `Footer` —  .
- `Header`
- `HoverCard` — HoverCard 
- `Input`
- `Label`
- `Loading`
- `Logo`
- `Menu`
- `Modal`
- `Notify`
- `Pagination`
- `Popover` — Popover 
- `Progress`
- `RadioGroup`
- `ResetButton`
- `Spacing`
- `Table`
- `Tabs`
- `Textarea`
- `Toggle`
- `Tooltip`

### billing
- `AmountStepper`
- `BillingBanner` —          B-0/B-1 SoT.
- `CheckoutModal`
- `PlanCard` —    A-3    C-2   .
