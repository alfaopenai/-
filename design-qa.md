# Design QA — Alpha Poker premium table

## Verdict

final result: passed

No actionable P0, P1, or P2 issue remains in the verified desktop experience. Two non-blocking P3 improvements are recorded below.

## Visual sources and verified state

- Source visual truth: `C:\Users\Administrator\AppData\Local\Temp\codex-clipboard-e73a260d-a393-4175-9898-bfc109422a28.png`
- Final implementation screenshot: `C:\Users\Administrator\Desktop\POKER\output\design-qa\premium-gg-mock-qa-passed-1280x720.png`
- Hosted-runtime screenshot: `C:\Users\Administrator\Desktop\POKER\output\design-qa\premium-hosted-final-1280x720.png`
- Verified viewport: 1280 × 720 CSS pixels
- Verified route/state: `http://127.0.0.1:7000/?ggMock=1`, six occupied seats, three empty seats, flop dealt, hero hand visible, pot and equity overlays populated.
- The source and implementation depict different live hands, so visual fidelity was judged on composition, hierarchy, proportions, styling, affordances, and information density rather than identical card/player content.

## Full and focused comparison

The source and final implementation were inspected side by side at original resolution in one comparison pass. The full-frame images also served as the focused comparison because the table, board, seat pods, stack values, action/equity badges, and empty-seat controls are all legible without cropping.

### Fidelity surfaces

- Typography: clear Hebrew hierarchy with Segoe UI/Arial fallbacks; compact numeric emphasis mirrors the reference's table HUD while remaining readable. The exact GG typeface was not copied.
- Spacing and layout: the wide table is the dominant visual surface, seats follow the rail, the board remains the central focal point, and all content fits the verified viewport with `scrollWidth === innerWidth` and `scrollHeight === innerHeight`.
- Color and contrast: graphite chrome, green felt, cyan stack values, gold pot/action accents, white cards, and muted secondary labels closely match the reference's semantic palette.
- Image assets: generated raster leather/background, card-back, and chip assets render at appropriate crop and quality. Empty seats use the real Alpha Poker mark. No CSS-drawn icons or fake avatar imagery were introduced.
- Copy: Hebrew controls, player metadata, pot, equity, and desktop-only GG-reader messaging are coherent and concise.
- Intentional deviations: the existing calculator toolbar was retained as a compact product control surface; player avatars from the GG client were not fabricated and are represented by premium stat pods instead.

## Iteration history

### Iteration 1 — P1 layout and cascade defects

- Findings: legacy generic button styling made table controls/card slots appear white; narrow breakpoints clipped the table; history and diagnostics drawers could overlap; forced directionality harmed mixed Hebrew/player-name content.
- Fixes: introduced component-specific selectors, bounded responsive geometry, mutually exclusive drawers with synchronized ARIA state, and automatic text direction for names.
- Evidence: final 1280 × 720 screenshot; measured document size is exactly 1280 × 720 with no horizontal or vertical overflow.

### Iteration 2 — P2 visual scale mismatch

- Finding: the first premium pass left the table too small and narrow compared with the GG reference.
- Fix: expanded the stage to the available viewport, increased the table to the dominant width, and rebalanced seat/card positioning around the rail.
- Evidence: `premium-gg-mock-final-wide-v2-1280x720.png`, followed by the final QA capture.

### Iteration 3 — P2 keyboard dialog behavior

- Finding: the card picker did not fully restore hidden/ARIA state or focus when closed with Escape.
- Fix: Escape now closes the picker, restores `aria-hidden="true"`, and returns focus to the originating card slot.
- Evidence: card picker opened with 52 choices and focus on a card; Escape closed it and returned focus to `flop1`.

### Iteration 4 — P2 hosted-runtime control leakage

- Finding: a legacy display rule could override the `hidden` attribute on local-only reader/debug controls in the hosted build.
- Fix: hosted capability policy now guards every local endpoint/WebSocket/display-capture path, and hidden local controls have an explicit high-specificity rule.
- Evidence: hosted screenshot and runtime inspection show `data-runtime="hosted"`; reader, history, monitor, and diagnostics controls are hidden; the browser console is clean.

### Final comparison

- P0: none
- P1: none
- P2: none
- P3: optimize the three generated PNG assets (about 7.1 MB combined) for faster cold loads.
- P3: add arrow-key roving focus inside menu-style history/diagnostics lists if those lists become primary navigation.

## Interaction and accessibility checks

- GG mock read populated six players, the board, hero cards, pot, capture confidence, and equity overlays.
- Random deal populated all 23 card slots without errors; clear reset all dealt cards without errors while preserving the initialized blind pot as intended.
- History and diagnostics drawers open independently, update `aria-expanded`, close one another, close with Escape, and restore focus.
- Card picker exposes 52 card choices, maintains dialog ARIA state, closes with Escape, and restores focus.
- Seat/card controls have accessible labels; mixed-direction player names use automatic directionality.
- Reduced-motion rules are present for users who request less animation.

## Browser-rendered evidence

- Final local URL: `http://127.0.0.1:7000/?ggMock=1`
- Browser console: `[]`
- Final viewport metrics: `innerWidth=1280`, `innerHeight=720`, `scrollWidth=1280`, `scrollHeight=720`.
- Table-stage metrics: wrapper `(x=12, y=146, w=1256, h=554)`; table `(x=188.56, y=202.78, w=902.88, h=440.42)`.
- All seat bounds remain inside the stage: `minX=205.5`, `minY=173.1`, `maxX=1086.6`, `maxY=668.95`.
- Hosted build was separately served through a non-loopback hostname and verified at 1280 × 720 with no overflow and no console errors.

## Automated QA

- JavaScript syntax checks: 30/30 passed.
- Node smoke suites: 8/8 passed.
- Python unit suite: 81 collected; 78 passed, 3 skipped because optional source fixtures are absent, 0 failed, 0 errors.
- Curated web build: 17/17 expected files, 17/17 SHA-256 matches, 0 symlinks, 0 private paths, and 8,027,962 output bytes.
- Package/dependency resolution, curated web build, Render Blueprint JSON-schema validation, and whitespace checks passed.
