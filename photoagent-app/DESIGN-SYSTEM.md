# PhotoAgent Desktop App -- Design System & UI Specification

**Version:** 1.0
**Date:** April 14, 2026

---

## Color System

### Background Layers
| Token | Hex | Tailwind | Usage |
|---|---|---|---|
| `bg-base` | `#09090B` | `zinc-950` | Window background, deepest layer |
| `bg-surface` | `#18181B` | `zinc-900` | Sidebar, cards, panels |
| `bg-elevated` | `#27272A` | `zinc-800` | Hover states, dropdowns, modals |
| `bg-overlay` | `#3F3F46` | `zinc-700` | Tooltip backgrounds, active selections |

### Text Hierarchy
| Token | Hex | Tailwind | Usage |
|---|---|---|---|
| `text-primary` | `#FAFAFA` | `zinc-50` | Headings, important labels |
| `text-secondary` | `#A1A1AA` | `zinc-400` | Body text, descriptions |
| `text-muted` | `#71717A` | `zinc-500` | Placeholders, timestamps |

### Accent Colors
| Token | Hex | Tailwind | Usage |
|---|---|---|---|
| `accent-primary` | `#6366F1` | `indigo-500` | Primary buttons, active nav |
| `accent-primary-hover` | `#818CF8` | `indigo-400` | Hover state |
| `accent-primary-muted` | `#312E81` | `indigo-900` | Selected row bg, badge bg |
| `accent-success` | `#22C55E` | `green-500` | Success states |
| `accent-warning` | `#F59E0B` | `amber-500` | Warnings |
| `accent-danger` | `#EF4444` | `red-500` | Destructive actions |

### Borders
| Token | Hex | Tailwind |
|---|---|---|
| `border-subtle` | `#27272A` | `zinc-800` |
| `border-default` | `#3F3F46` | `zinc-700` |
| `border-focus` | `#6366F1` | `indigo-500` |

### Privacy
| Token | Hex | Usage |
|---|---|---|
| `privacy-badge-bg` | `#064E3B` | emerald-900 |
| `privacy-badge-text` | `#34D399` | emerald-400 |

---

## Typography

Font: `-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`

| Token | Size | Weight | Tailwind |
|---|---|---|---|
| `display` | 28px | 700 | `text-[28px] font-bold` |
| `h1` | 22px | 600 | `text-[22px] font-semibold` |
| `h2` | 17px | 600 | `text-[17px] font-semibold` |
| `body` | 14px | 400 | `text-sm` |
| `caption` | 12px | 400 | `text-xs` |
| `label` | 11px | 500 | `text-[11px] font-medium` |

---

## Layout

- Window: 1280x800 default, 960x600 min
- Sidebar: 240px (expanded), 64px (collapsed), bg-surface
- Detail panel: 320px, slides from right
- Photo grid: CSS Grid auto-fill, 200px thumbnails, 4px gap

---

## Tailwind Custom Config

```
colors:
  pa-base: '#09090B'
  pa-surface: '#18181B'
  pa-elevated: '#27272A'
  pa-overlay: '#3F3F46'
  pa-accent: '#6366F1'
  pa-accent-hover: '#818CF8'
  pa-accent-muted: '#312E81'
  pa-success: '#22C55E'
  pa-warning: '#F59E0B'
  pa-danger: '#EF4444'
  pa-privacy-bg: '#064E3B'
  pa-privacy: '#34D399'
```
