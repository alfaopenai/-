# GG Reader Backend

This backend is a passive screen reader for the poker UI. It does not click or control GG Club.

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\activate
pip install -r backend\requirements.txt
```

Install Tesseract OCR for Windows and verify:

```powershell
tesseract --version
```

If Tesseract is installed in a custom path, set:

```powershell
$env:TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## Run

Terminal 1:

```powershell
npm run start:backend
```

Terminal 2:

```powershell
npm run start:web
```

Or run both:

```powershell
npm run dev
```

## Mock UI Check

Open:

```text
http://127.0.0.1:7000/?ggMock=1
```

Click `קרא שולחן GG`. This uses `mock/gg_snapshot_example.json`.

## Live Screen Check

The recommended live path is browser capture:

1. Open `http://127.0.0.1:7000/`.
2. Click `קרא שולחן GG`.
3. In the browser sharing dialog, choose the `NLH` / `PLO` GG table window. If you choose the full screen, keep the GG window visible.

The browser sends cropped frames to:

```text
POST http://127.0.0.1:8787/api/gg-reader/parse-frame
```

The frontend samples at 3 FPS. Hidden opponent cards are displayed as `X` and are not inserted into the deck.

Every accepted snapshot is stored in SQLite:

```text
backend/data/gg_history.sqlite
GET http://127.0.0.1:8787/api/gg-reader/hands
GET http://127.0.0.1:8787/api/gg-reader/history
```

Native backend capture is still available with:

```text
http://127.0.0.1:7000/?ggNative=1
```

Native capture must run in the same Windows session where GG Club is visible. If GG Club is open on your local computer but this backend runs inside RDP/VPS, the backend cannot see the local screen.

List monitors:

```text
GET http://127.0.0.1:8787/api/gg-reader/monitors
```

List detected GG windows:

```text
GET http://127.0.0.1:8787/api/gg-reader/windows
```

Select a monitor from the UI dropdown or use:

```text
http://127.0.0.1:7000/?ggMonitor=1
```

Capture a debug frame:

```text
GET http://127.0.0.1:8787/api/gg-reader/debug/frame?source=auto
GET http://127.0.0.1:8787/api/gg-reader/debug/frame?source=window
GET http://127.0.0.1:8787/api/gg-reader/debug/frame?source=monitor
GET http://127.0.0.1:8787/api/gg-reader/debug/frame-info
```

The frame is saved to:

```text
backend/data/debug_last_frame.png
```

## Current Limitations

- Browser capture is the default live mode because Windows may block direct capture of game windows.
- Auto native mode still prefers the visible ClubGG table window (`NLH` / `PLO`) through Windows Graphics Capture, then falls back to monitor capture.
- The live reader is tuned for 3 FPS; OCR runs from cache/background work so card/seat updates do not wait on Tesseract every frame.
- Board-card recognition is implemented for large GG card faces.
- OCR for names and stacks is still imperfect and depends on Tesseract being installed.
- Calibration profiles are placeholders until verified against real GG screenshots.
- Hidden cards can be represented as `X`.
- A weak/unparsed frame must not clear the table; the frontend preserves the last valid snapshot.
