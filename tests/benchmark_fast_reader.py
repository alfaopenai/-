from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2

from backend.gg_reader.fast_reader import FastGgReader


def main() -> int:
    fixture = ROOT / "tests" / "fixtures" / "gg_table_preflop.png"
    frame = cv2.imread(str(fixture), cv2.IMREAD_UNCHANGED)
    if frame is None:
        raise SystemExit(f"Could not load fixture: {fixture}")

    reader = FastGgReader()
    for _index in range(30):
        reader.parse(frame)

    times_ms: list[float] = []
    snapshot = None
    for _index in range(300):
        started_at = time.perf_counter()
        snapshot = reader.parse(frame)
        times_ms.append((time.perf_counter() - started_at) * 1000)

    ordered = sorted(times_ms)
    p95 = ordered[int(0.95 * (len(ordered) - 1))]
    avg = statistics.mean(times_ms)
    metrics = reader.get_metrics()
    print(
        "frames=300 "
        "warmup=30 "
        f"avgParseMs={avg:.2f} "
        f"p95ParseMs={p95:.2f} "
        f"maxParseMs={max(times_ms):.2f} "
        f"actualReaderFps={metrics.get('actualReaderFps', 0)} "
        f"fieldsUpdated={metrics.get('fieldsUpdated', 0)} "
        f"fieldsReused={metrics.get('fieldsReused', 0)} "
        f"changedRois={metrics.get('changedRois', 0)} "
        f"ocrPending={metrics.get('ocrPending', 0)}"
    )
    if avg >= 100 or p95 >= 180 or max(times_ms) >= 333:
        raise SystemExit(
            f"Benchmark failed: avg={avg:.2f}ms p95={p95:.2f}ms max={max(times_ms):.2f}ms"
        )
    if snapshot is not None:
        print(
            f"snapshot active={snapshot.activePlayerCount} "
            f"street={snapshot.street} pot={snapshot.pot} "
            f"dealer={snapshot.dealerSeatIndex} confidence={snapshot.confidence:.3f}"
        )
    print(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
