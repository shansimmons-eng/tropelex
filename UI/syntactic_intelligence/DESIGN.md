---
name: Syntactic Intelligence
colors:
  surface: '#0c1324'
  surface-dim: '#0c1324'
  surface-bright: '#32394c'
  surface-container-lowest: '#070e1f'
  surface-container-low: '#141b2d'
  surface-container: '#181f31'
  surface-container-high: '#232a3c'
  surface-container-highest: '#2e3447'
  on-surface: '#dce2fa'
  on-surface-variant: '#cbc3d5'
  inverse-surface: '#dce2fa'
  inverse-on-surface: '#293042'
  outline: '#958e9e'
  outline-variant: '#494452'
  surface-tint: '#d1bcff'
  primary: '#d1bcff'
  on-primary: '#3c058d'
  primary-container: '#a580fa'
  on-primary-container: '#3a008b'
  inverse-primary: '#6c46bd'
  secondary: '#7cd1f6'
  on-secondary: '#003546'
  secondary-container: '#007697'
  on-secondary-container: '#def3ff'
  tertiary: '#7cdc67'
  on-tertiary: '#023a00'
  tertiary-container: '#4ca93a'
  on-tertiary-container: '#023700'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#eaddff'
  primary-fixed-dim: '#d1bcff'
  on-primary-fixed: '#24005b'
  on-primary-fixed-variant: '#532ba4'
  secondary-fixed: '#bde9ff'
  secondary-fixed-dim: '#7cd1f6'
  on-secondary-fixed: '#001f2a'
  on-secondary-fixed-variant: '#004d64'
  tertiary-fixed: '#98fa80'
  tertiary-fixed-dim: '#7cdc67'
  on-tertiary-fixed: '#012200'
  on-tertiary-fixed-variant: '#045300'
  background: '#0c1324'
  on-background: '#dce2fa'
  surface-variant: '#2e3447'
  accent-lavender: '#a580fa'
  accent-periwinkle: '#8098fa'
  accent-sky: '#80d5fa'
  accent-lime: '#98fa80'
  terminal-bg: '#010515'
  glass-border: rgba(165, 128, 250, 0.2)
  status-success: '#98fa80'
  status-info: '#80d5fa'
  status-warning: '#a580fa'
typography:
  headline-xl:
    fontFamily: Hanken Grotesk
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Hanken Grotesk
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Hanken Grotesk
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Hanken Grotesk
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.1em
spacing:
  unit: 4px
  gutter: 16px
  margin-desktop: 32px
  margin-mobile: 16px
  container-max: 1440px
---

## Brand & Style

The design system is engineered for high-performance AI memory management, bridging the gap between raw data structures and professional human-computer interaction. It prioritizes information density and technical clarity, evoking the precision of a high-end IDE mixed with the sophisticated aesthetics of modern aerospace instrumentation.

The visual direction follows a **Modern-Terminal** approach:
- **Atmosphere:** Dark, immersive, and analytical.
- **Visual Language:** High-contrast surfaces, razor-sharp geometry, and functional glassmorphism. 
- **Depth:** Surfaces use backdrop blurs and subtle glows rather than traditional shadows to simulate a futuristic HUD (Heads-Up Display).
- **Density:** Tight spacing and compact typography to support complex knowledge graphs and deep technical logs.

## Colors

The palette is anchored in a near-black navy (`#010515`) to provide maximum contrast for its neon-adjacent accents. 

- **Primary & Secondary:** Lavender and Sky are used for primary actions, active states, and focus indicators.
- **Data Accents:** Lime-green is reserved for "learning" events, successful completions, and positive pattern matching. Periwinkle is used for secondary data attributes and metadata.
- **Glass Effects:** Overlays and modals utilize semi-transparent versions of the background with thin, 1px borders using `glass-border` to maintain structural definition without heavy solid fills.
- **High-Contrast Logic:** All text must meet a minimum 7:1 contrast ratio against the deep navy background to ensure legibility in high-density data views.

## Typography

This design system employs a dual-font strategy to balance human readability with machine-centric data display.

- **UI Controls & Prose:** `Hanken Grotesk` provides a sharp, contemporary sans-serif feel that remains legible even at smaller scales used in high-density sidebars.
- **Data & Code:** `JetBrains Mono` is used for all JSON outputs, memory addresses, timestamps, and terminal logs.
- **Scaling:** On mobile devices, `headline-xl` should scale down to 32px. Use `label-caps` for all secondary metadata, categories, and system tags to create a clear visual distinction from interactive body text.

## Layout & Spacing

The layout is built on a **4px base grid** to allow for the precision required in technical interfaces.

- **Grid Model:** A 12-column fluid grid for desktop, transitioning to a 4-column grid for mobile.
- **Density:** We favor a "Compact" density model. Content areas should use 16px (4 units) of internal padding to maximize the amount of visible data on-screen.
- **Structure:** Use horizontal dividers and subtle vertical lines (1px) to separate memory modules rather than wide whitespace. This mimics a multi-pane IDE layout.
- **Breakpoints:**
  - Mobile: < 600px
  - Tablet: 600px - 1024px
  - Desktop: > 1024px

## Elevation & Depth

Standard shadows are replaced by **Tonal Layering** and **Glows**:

- **Layer 0 (Background):** Base navy `#010515`.
- **Layer 1 (Surface):** Slightly lighter navy (2% lighter) with a 1px border.
- **Layer 2 (Overlays):** 70% opacity background with a 20px backdrop-filter blur.
- **Active States:** Instead of elevation height, active elements use a subtle outer glow (box-shadow) using the primary lavender or sky colors with a 4px-8px blur radius. This creates a "powered-on" terminal effect.
- **Depth Hierarchy:** Use `z-index` to stack glass panels. Higher-level panels should have a slightly more opaque border to distinguish themselves from the background layers.

## Shapes

The shape language is strictly **Sharp (0px)**. 

- **Hard Edges:** All buttons, input fields, cards, and modal windows must use 90-degree corners. This reinforces the technical, systematic nature of the product.
- **Separators:** Use 1px solid lines for all divisions. Avoid rounded containers or "pill" buttons unless they represent status indicators (chips), and even then, consider using square tags for consistency.

## Components

- **Buttons:** Sharp corners, 1px border. Default state is a ghost-style (transparent background with accent border). Hover state triggers a solid fill of the accent color with black text.
- **Input Fields:** Bottom-border only or 1px full border. Focus state should trigger a subtle glow in the secondary Sky color. Use Monospaced font for all text input.
- **Chips/Tags:** Square edges. Use `label-caps` typography. Backgrounds should be low-opacity (15%) versions of the accent colors.
- **Cards:** No shadows. Use 1px borders (`glass-border`). Titles should be in `headline-md` or `label-caps` depending on content type.
- **Memory Lists:** High-density rows with alternating subtle background tints. Use icons for "SourceType" (e.g., a small terminal icon for CLI, a globe for WebScraper).
- **Glow Indicators:** Use small (8px) square "LED" indicators to show system status (e.g., Pulsing Lime for "Active Learning").
- **Scrollbars:** Custom-styled to be ultra-thin (4px), using the periwinkle accent for the thumb and the base navy for the track.