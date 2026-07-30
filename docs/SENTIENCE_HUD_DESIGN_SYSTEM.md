# Sentience HUD Design System — CycleKernel Ghost Sync v3.1

> Design-system specification for the Cognitive Sync overlay.
> This document is the interim design system while the Figma connector remains auth-gated.
> Once a real fileKey + node-id is supplied and Figma auth is restored, this content will be synchronized into the Figma file.

## 1. Purpose

The Sentience HUD is the visual manifestation of the CognitiveBridge.
It shows the operator *why* the LLM is currently in a particular cognitive state by mapping live LoopMem metrics into Evo-Psych traits and system-prompt overrides.

## 2. Color Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `#0a0e17` | Page background |
| `--panel` | `#111827` | Card / panel surface |
| `--border` | `#1f2937` | Borders, dividers |
| `--text` | `#e5e7eb` | Primary text |
| `--muted` | `#9ca3af` | Secondary / labels |
| `--accent` | `#22d3ee` | Brand / live indicator |
| `--divergent` | `#a78bfa` | High Entropy mood |
| `--convergent` | `#34d399` | High Coupling mood |
| `--survival` | `#f87171` | Low Core mood |
| `--neutral` | `#60a5fa` | Baseline / balanced |

## 3. Typography

- Font stack: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`
- Mood display: 1.75rem / 600
- Section labels: 0.7rem uppercase, letter-spacing 0.1em
- Metric values: 1.25rem
- Body / explanation: 0.9rem

## 4. Components

### 4.1 Mood Indicator
- Large colored text reflecting current cognitive state
- Classes: `.mood.divergent` | `.mood.convergent` | `.mood.survival` | `.mood.neutral` | `.mood.balanced-tension`

### 4.2 Metric Cards
Three equal cards showing:
- Entropy (L5)
- Coupling (L2)
- Core

### 4.3 Trait Chips
Pill-shaped chips listing active Evo-Psych traits:
- Creative/Divergent
- Analytical/Convergent
- Survival/Conservation
- High-Confidence / Exploratory-Uncertainty
- Neutral-Baseline

### 4.4 System Prompt Override Box
Left-border accent panel that displays the exact override text the Chat Interface should inject.

### 4.5 Integration Endpoint Card
Dashed border panel documenting:
```
GET /v1/current_mood
```

## 5. Cognitive Mapping Rules (Source of Truth)

| Condition | Trait | Mood | Explanation |
|-----------|-------|------|-------------|
| L5 (entropy) > 0.8 | Creative/Divergent | divergent | Current State: High Entropy - Expect Divergent Answers |
| L2 (coupling) > 0.05 | Analytical/Convergent | convergent / balanced-tension | Current State: High Coupling - Expect Analytical Precision |
| Core < 0.1 | Survival/Conservation | survival | Current State: Low Core - Survival/Conservation Protocols Active |
| U2 > 0.7 | High-Confidence | — | Increase assertive tone |
| U2 < 0.2 | Exploratory-Uncertainty | — | Surface uncertainty explicitly |
| none of the above | Neutral-Baseline | neutral | LoopMem within nominal bounds |

## 6. Live Surfaces

- **Production HUD**: https://ghost-sync-hud-v31.vercel.app
- **Alias**: https://ghost-sync-hud-v31-ghost-shell.vercel.app
- **Bridge code**: `src/bridge/` on this repository (v3.1-ghost-sync)

## 7. Next Step (Figma)

When the Figma connector is re-authenticated and a design URL or raw `fileKey` + `node-id` is supplied, the `cyclekernel-deploy` skill will:

1. Parse the coordinates
2. Call `figma___get_design_context`
3. Optionally capture the live HUD into the Figma file
4. Sync the tokens and components defined above into the design system

Until then, this markdown file is the canonical design-system reference.
