# Task 16 UI audit and review record

## Initial classification

| Area | Initial classification | Primary finding | Implemented status |
|---|---|---|---|
| Splash | spacing/typography polish | remote font and decorative gradient dependency | System font, calm ivory/sea-green layout |
| Login/registration | accessibility/responsive | unconstrained desktop width and inconsistent form behavior | Constrained, keyboard-aware form with autofill/actions and language control |
| OTP | accessibility/responsive | dense input/feedback and unconstrained width | Six-digit presentation, live feedback/progress semantics, constrained form |
| Caregiver dashboard | responsive/navigation error | fixed grid aspect ratio, inert bottom navigation, raw load exception, developer-facing ML summary in primary actions | Adaptive 2/3-column grid, working care destinations, safe error message; ML audit summary removed from the caregiver workflow |
| Patient management | responsive/accessibility | fixed side-by-side form fields and list-tile checkbox dependence | Adaptive fields, accessible checkbox control, constrained form |
| Assessment | framework/layout error | six symptom tiles plus measurement confirmation tiles used problematic ListTile/card composition; BMI/dropdowns overflowed with scaling | No ListTile composition; responsive sections; feet/inches entry converts to centimetres before BMI, API, and persistence; caregiver-facing general glucose accepts decimal mmol/L and converts only at the compatibility boundary for the existing integer mg/dL record/heuristic contract; narrow and 180% text-scale revalidation required after the input update |
| Risk result | visual/responsive | gradient and wide unconstrained content | Solid formal status panel and bounded content |
| Prescription/OCR | responsive polish | long form stretched on web | Bounded, keyboard-dismissable review flow; existing explicit confirmation retained |
| History | error/responsive | raw exception and gradient summary | Safe retry error, semantic loading, constrained full-height tabs, solid summary, and a rolling seven-day view of saved Heart v2 scores with an explicit non-heart-attack disclaimer |
| ML summary | terminology/visual | dense wide presentation and gradient | Bounded reading width, accurate model/fallback wording, solid header |
| Loading/error/empty | consistency | several raw or unlabeled states | Semantic progress on critical screens and safe dashboard/history/medicine errors; existing next-action empty states retained |

## Design/accessibility decisions

- Shared sea-green, ivory, white, light-yellow, border, and accessible status colors.
- Platform/system typography with a global `Noto Sans Bengali` fallback to render Bangla glyphs consistently without a remote font dependency.
- Theme-level 48–56 logical-pixel controls plus padded checkboxes and icon buttons.
- Shared spacing/radius, cards, primary buttons, section headers, responsive content, adaptive form rows, and checkbox tiles.
- Gradients and `withOpacity` deprecated calls removed from application UI.
- Key English/Bangla labels centralized with a persisted runtime language selection.
- Android keyboard mode remains `adjustResize`; long forms dismiss keyboard on drag.

## Automated viewport evidence

- Assessment at 320 × 780: no framework/layout exception.
- Assessment at 390 × 844 with 1.8 text scale: no overflow/framework exception.
- Role selection at 320 x 780: no overflow/framework exception.
- Caregiver registration and OTP at 390 x 844 with 1.8 text scale: no overflow/framework exception.
- Flutter Web at 900 x 700 and 1440 x 1000: static screenshots reviewed for hierarchy, spacing, and bounded content.
- Physical narrow/standard/landscape validation remains mandatory before completion.
