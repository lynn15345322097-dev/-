---
name: Shanshui Minimalist
colors:
  surface: '#fafaf5'
  surface-dim: '#dadad5'
  surface-bright: '#fafaf5'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f4f4ef'
  surface-container: '#eeeee9'
  surface-container-high: '#e8e8e3'
  surface-container-highest: '#e3e3de'
  on-surface: '#1a1c19'
  on-surface-variant: '#444748'
  inverse-surface: '#2f312e'
  inverse-on-surface: '#f1f1ec'
  outline: '#747878'
  outline-variant: '#c4c7c7'
  surface-tint: '#5f5e5e'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#1c1b1b'
  on-primary-container: '#858383'
  inverse-primary: '#c8c6c5'
  secondary: '#5e5e5e'
  on-secondary: '#ffffff'
  secondary-container: '#e3e2e2'
  on-secondary-container: '#646464'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#1a1c1c'
  on-tertiary-container: '#838484'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e5e2e1'
  primary-fixed-dim: '#c8c6c5'
  on-primary-fixed: '#1c1b1b'
  on-primary-fixed-variant: '#474746'
  secondary-fixed: '#e3e2e2'
  secondary-fixed-dim: '#c7c6c6'
  on-secondary-fixed: '#1b1c1c'
  on-secondary-fixed-variant: '#464747'
  tertiary-fixed: '#e3e2e2'
  tertiary-fixed-dim: '#c7c6c6'
  on-tertiary-fixed: '#1a1c1c'
  on-tertiary-fixed-variant: '#464747'
  background: '#fafaf5'
  on-background: '#1a1c19'
  surface-variant: '#e3e3de'
typography:
  display-lg:
    fontFamily: EB Garamond
    fontSize: 48px
    fontWeight: '500'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: EB Garamond
    fontSize: 32px
    fontWeight: '500'
    lineHeight: '1.2'
  headline-md:
    fontFamily: EB Garamond
    fontSize: 24px
    fontWeight: '500'
    lineHeight: '1.3'
  body-lg:
    fontFamily: Work Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.6'
  body-md:
    fontFamily: Work Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.5'
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1.0'
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 8px
  container-max: 1140px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 64px
---

## Brand & Style
This design system fuses the ancient art of *Shuimo* (ink wash) with contemporary minimalist UI principles. It targets a sophisticated audience seeking focus and tranquility, particularly in creative, literary, or high-end lifestyle contexts.

The design movement is **Minimalist-Calligraphic**. It leverages the concept of "white space" (*liubai*) not just as a lack of content, but as a structural element that allows the UI to breathe. The aesthetic relies on the contrast between precision (grid-based layout) and organic expression (ink bleeds and brush-stroke accents). The emotional response should be one of deep focus, serenity, and timeless quality.

## Colors
The palette is strictly monochromatic, inspired by the varied tones of ink on rice paper.

- **Paper White (#F5F5F0):** The base surface, a warm cream that prevents eye strain and evokes traditional xuan paper.
- **Ink Black (#1A1A1A):** Used for primary text and high-impact structural elements. It is never pure black, retaining a soft, charcoal-like depth.
- **Charcoal Grey (#757575):** For secondary information and borders.
- **Light Wash Greys:** Used for backgrounds and subtle textures, mimicking diluted ink.

Avoid gradients unless they simulate a natural ink bleed. Accent colors are forbidden; hierarchy is established purely through value and weight.

## Typography
Typography reflects the tension between the brush and the press.

- **Headlines:** Use **EB Garamond**. Its calligraphic roots and elegant serifs mimic the variable pressure of a brush stroke. Use generous leading and optical kerning.
- **Body:** Use **Work Sans**. It provides a grounded, neutral contrast to the expressive headlines, ensuring long-form legibility.
- **Data & Labels:** Use **JetBrains Mono**. This monospaced choice introduces a "seal-carving" or "technical" precision to the UI, making it feel modern and professional.

Vertical text orientation is encouraged for short decorative headings or sidebar labels to reinforce the traditional aesthetic.

## Layout & Spacing
The layout follows a **Fixed Grid** philosophy with asymmetrical balancing. 

- **The Void:** Use exaggerated margins (64px+) on desktop to create a sense of vastness. Content should be centered or offset to one side to mimic a landscape scroll.
- **Rhythm:** Spacing follows an 8px base unit. However, component spacing should be "loose" rather than "tight" to maintain the *liubai* effect.
- **Responsive:** On mobile, margins collapse to 16px, and vertical stacks are used. For tablets, maintain large top and bottom safe areas to frame the content like a piece of art.

## Elevation & Depth
In this design system, depth is conveyed through **Tonal Layers** and opacity rather than shadows.

- **Stacking:** Surface levels are distinguished by subtle shifts from Paper White (#F5F5F0) to light wash greys. 
- **Ink Bleed:** Instead of drop shadows, use soft, asymmetric blurs (10-20% opacity) that look like ink soaking into paper.
- **Translucency:** Use backdrop filters with 90% opacity on floating panels to create a "layered paper" effect. 
- **Outlines:** Use thin (0.5px - 1px) borders that appear hand-drawn or slightly irregular in opacity to define sections without adding "weight."

## Shapes
The shape language is primarily **Soft** and organic. 

While the grid is rigid, individual components should feel slightly softened. Avoid perfect circles for anything other than icons; instead, use slightly squircle-like shapes.
- Use `rounded-lg` (0.5rem) for cards and containers.
- Use `rounded-xl` (0.75rem) for buttons to give them a "stone" or "pebble" feel.
- Decorative elements may feature "torn paper" edges or "ink splash" masks.

## Components
- **Buttons:** Primary buttons are solid Ink Black with Paper White text. Secondary buttons use a "brush stroke" border (1px solid with variable opacity). There is no hover "glow"; instead, the background shifts slightly to a darker wash grey.
- **Cards:** Cards have no shadows. They are defined by a 1px wash-grey border or a subtle background color shift. 
- **Inputs:** Simple bottom-border only, mimicking a line on a notebook. The focus state is a subtle "ink bleed" expansion of the border weight.
- **Chips:** Rounded-xl shapes with a light grey background, resembling small river stones.
- **Lists:** Separated by thin, horizontal strokes that don't reach the edge of the container, suggesting a manuscript layout.
- **Specialty Component - The Seal:** A small, square red-tinted (the only exception to the palette) or black-on-white monogram used as a "verified" badge or a signature at the end of articles.