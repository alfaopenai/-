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

The backend must run in the same Windows session where GG Club is visible.
If GG Club is open on your local computer but this backend runs inside RDP/VPS, the backend cannot see the local screen.

List monitors:

```text
GET http://127.0.0.1:8787/api/gg-reader/monitors
```

Select a monitor from the UI dropdown or use:

```text
http://127.0.0.1:7000/?ggMonitor=1
```

Capture a debug frame:

```text
GET http://127.0.0.1:8787/api/gg-reader/debug/frame
GET http://127.0.0.1:8787/api/gg-reader/debug/frame-info
```

The frame is saved to:

```text
backend/data/debug_last_frame.png
```

## Current Limitations

- OCR and template matching are scaffolded, not complete.
- Calibration profiles are placeholders until verified against real GG screenshots.
- Hidden cards can be represented as `X`.
- Visible-card recognition requires templates in `backend/gg_reader/templates/`.
- A weak/unparsed frame must not clear the table; the frontend preserves the last valid snapshot.
