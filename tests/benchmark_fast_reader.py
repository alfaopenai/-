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
    fixture = ROOT / "backend" / "data" / "debug_last_frame.png"
    frame = cv2.imread(str(fixture), cv2.IMREAD_UNCHANGED)
    if frame is None:
        raise SystemExit(f"Could not load fixture: {fixture}")

    reader = FastGgReader()
    times_ms: list[float] = []
    snapshot = None
    for _index in range(300):
        started_at = time.perf_counter()
        snapshot = reader.parse(frame)
        times_ms.append((time.perf_counter() - started_at) * 1000)

    ordered = sorted(times_ms)
    p95 = ordered[int(0.95 * (len(ordered) - 1))]
    print(
        "frames=300 "
        f"first={times_ms[0]:.2f}ms "
        f"avg={statistics.mean(times_ms):.2f}ms "
        f"p95={p95:.2f}ms "
        f"max={max(times_ms):.2f}ms"
    )
    if snapshot is not None:
        print(
            f"snapshot active={snapshot.activePlayerCount} "
            f"street={snapshot.street} pot={snapshot.pot} "
            f"dealer={snapshot.dealerSeatIndex} confidence={snapshot.confidence:.3f}"
        )
    print(reader.get_metrics())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
