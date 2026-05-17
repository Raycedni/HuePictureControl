"""WLED activation latency benchmark.

Reproduces the per-frame event-loop slice the StreamingCoordinator runs,
comparing the CURRENT shared-gradient design (`region_gradients` with
``n=N`` then ``asyncio.gather(hue.render, wled.render)``) against the
SPLIT design (cheap ``hue_gradients`` n=1 on the event loop +
``wled_gradients`` n=N inside ``asyncio.to_thread``, gathered).

The goal is to confirm that Hue's per-frame event-loop time stays at the
no-WLED baseline (~0.15 ms) regardless of WLED LED count when the split
is applied.

Run:
    source /tmp/hpc-venv/Scripts/activate
    cd Backend
    python -m spike.wled_latency_bench

Note on fidelity: this benchmark does NOT load DTLS / UDP sockets. It
reproduces ONLY the SYNCHRONOUS per-frame compute that runs on the
event loop -- which is the dimension affected by the split fix. The real
HueStreamer and WledStreamer both await an ``asyncio.to_thread`` for
their actual IO so their IO costs are off-loop in both designs.
"""
from __future__ import annotations

import asyncio
import statistics
import time

import numpy as np

from services.color_math import (
    RegionMask,
    build_polygon_mask,
    sub_sample_gradient,
)


# ----- Fake sinks that reproduce the SYNC portion of each real render -----

class FakeHue:
    """Reproduces HueStreamer.render's synchronous body cost.

    Per services/streaming_service.py:183-292, the sync body:
      1. For each channel: gradient.mean(axis=0) -> rgb_to_xy -> struct.pack
      2. Concatenates a bytearray of channel records
      3. _build_dtls_message(records) -> header pack + checksum
      4. await asyncio.to_thread(sock.send, message)   <-- off-loop

    We model 1-3 with real numpy + bytearray work so the sync slice is
    realistic. We skip 4 (the send is off-loop in both designs).
    """

    def __init__(self, n_channels: int) -> None:
        self._n_channels = n_channels
        # Each channel maps to one of the regions (round-robin).
        # In the real code _channel_to_region is loaded from DB during start.
        self._channel_to_region: dict[int, str] = {}

    def bind(self, region_ids: list[str]) -> None:
        if not region_ids:
            self._channel_to_region = {}
            return
        for i in range(self._n_channels):
            self._channel_to_region[i] = region_ids[i % len(region_ids)]

    async def render(self, region_gradients: dict[str, np.ndarray]) -> None:
        records = bytearray()
        for channel_id, region_id in self._channel_to_region.items():
            gradient = region_gradients.get(region_id)
            if gradient is None or len(gradient) == 0:
                continue
            mean_rgb = gradient.mean(axis=0)
            r = int(mean_rgb[0]); g = int(mean_rgb[1]); b = int(mean_rgb[2])
            # rgb_to_xy stand-in: cheap math (matches the real per-channel cost
            # at small N -- pure floats, no numpy allocation).
            x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / max(r + g + b, 1)
            y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / max(r + g + b, 1)
            bri = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255.0
            x_u16 = int(max(0.0, min(1.0, x)) * 65535)
            y_u16 = int(max(0.0, min(1.0, y)) * 65535)
            b_u16 = int(max(0.0, min(1.0, bri)) * 65535)
            records += int(channel_id).to_bytes(1, "big") + \
                       x_u16.to_bytes(2, "big") + \
                       y_u16.to_bytes(2, "big") + \
                       b_u16.to_bytes(2, "big")
        # Header pack (~16 bytes) mirrors _build_dtls_message.
        message = b"HueStream" + b"\x02\x00\x00\x00\x00\x00\x00" + bytes(records)
        # Real code does: await asyncio.to_thread(sock.send, message).
        # We model the await as a single event-loop yield -- the send work
        # is off-loop in both designs.
        await asyncio.sleep(0)
        # Touch message so it isn't optimised away.
        _ = len(message)


class FakeWled:
    """Reproduces WledStreamer.render's per-device synchronous body cost.

    Per services/wled_streamer.py:295-441, per device the sync body:
      1. Build colors = np.zeros((led_count, 3), dtype=np.uint8)
      2. For each channel: lookup gradient, sub-sample (np.linspace + index)
         OR slice, plus the brightness-cutoff path (mean+luma calc)
      3. build_packets_for_device(colors).tobytes() into UDP frames
      4. await asyncio.to_thread(_send_all)   <-- off-loop

    We model 1-3; step 4 is off-loop in both designs.
    """

    def __init__(self, n_devices: int, led_count: int, n_channels_per_dev: int = 1) -> None:
        self._n_devices = n_devices
        self._led_count = led_count
        self._n_channels_per_dev = n_channels_per_dev
        self._region_ids_per_dev: list[list[str]] = []

    def bind(self, region_ids: list[str]) -> None:
        # Round-robin region assignment across devices/channels.
        if not region_ids:
            self._region_ids_per_dev = [[] for _ in range(self._n_devices)]
            return
        self._region_ids_per_dev = []
        idx = 0
        for _ in range(self._n_devices):
            dev_regions = []
            for _ in range(self._n_channels_per_dev):
                dev_regions.append(region_ids[idx % len(region_ids)])
                idx += 1
            self._region_ids_per_dev.append(dev_regions)

    async def render(self, region_gradients: dict[str, np.ndarray]) -> None:
        async def _one_device(dev_regions: list[str]) -> None:
            colors = np.zeros((self._led_count, 3), dtype=np.uint8)
            for region_id in dev_regions:
                gradient = region_gradients.get(region_id)
                if gradient is None or len(gradient) == 0:
                    continue
                src_n = len(gradient)
                if src_n == self._led_count:
                    slice_arr = gradient
                elif src_n == 1:
                    slice_arr = np.broadcast_to(
                        gradient[0].astype(np.uint8), (self._led_count, 3)
                    )
                else:
                    idx = np.linspace(
                        0, src_n - 1, self._led_count
                    ).astype(np.int32)
                    slice_arr = gradient[idx]
                colors[: self._led_count] = slice_arr
            # Mimic build_packets_for_device tobytes pack (one packet body).
            _packet = colors.tobytes()
            # The real to_thread send is off-loop -- model as a yield.
            await asyncio.sleep(0)
            _ = len(_packet)

        if self._n_devices == 0:
            return
        await asyncio.gather(*(
            _one_device(self._region_ids_per_dev[i])
            for i in range(self._n_devices)
        ))


# ----- Helpers -----

def _make_region_mask() -> RegionMask:
    poly = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    return build_polygon_mask(poly)


def _make_frame() -> np.ndarray:
    rng = np.random.default_rng(seed=42)
    return rng.integers(0, 256, size=(480, 640, 3), dtype=np.uint8)


# ----- Pipeline variants -----

async def current_frame(
    frame: np.ndarray,
    region_plan: dict,
    hue: FakeHue,
    wled: FakeWled,
    n_region: int,
) -> tuple[float, float]:
    """CURRENT (pre-fix) path: shared region_gradients dict with n=n_region."""
    t_frame = time.perf_counter()
    region_gradients = {
        rid: sub_sample_gradient(frame, mask, n_region, orientation="auto")
        for rid, (mask, _, _) in region_plan.items()
    }
    hue_dt = 0.0

    async def _timed_hue() -> None:
        nonlocal hue_dt
        t0 = time.perf_counter()
        await hue.render(region_gradients)
        hue_dt = (time.perf_counter() - t0) * 1000.0

    await asyncio.gather(_timed_hue(), wled.render(region_gradients))
    total = (time.perf_counter() - t_frame) * 1000.0
    return hue_dt, total


async def split_frame(
    frame: np.ndarray,
    region_plan: dict,
    hue: FakeHue,
    wled: FakeWled,
    n_region: int,
) -> tuple[float, float]:
    """SPLIT (post-fix) path: hue_gradients (n=1, on loop) + wled (n=N, to_thread)."""
    t_frame = time.perf_counter()
    hue_gradients = {
        rid: sub_sample_gradient(frame, mask, 1, orientation="auto")
        for rid, (mask, _, _) in region_plan.items()
    }

    async def _wled_pipeline() -> None:
        def _compute() -> dict[str, np.ndarray]:
            return {
                rid: sub_sample_gradient(frame, mask, n_region, orientation="auto")
                for rid, (mask, _, _) in region_plan.items()
            }
        wled_gradients = await asyncio.to_thread(_compute)
        await wled.render(wled_gradients)

    hue_dt = 0.0

    async def _timed_hue() -> None:
        nonlocal hue_dt
        t0 = time.perf_counter()
        await hue.render(hue_gradients)
        hue_dt = (time.perf_counter() - t0) * 1000.0

    await asyncio.gather(_timed_hue(), _wled_pipeline())
    total = (time.perf_counter() - t_frame) * 1000.0
    return hue_dt, total


# ----- Driver -----

async def measure(
    label: str,
    runner,
    region_plan: dict,
    hue: FakeHue,
    wled: FakeWled,
    n_region: int,
    iters: int = 120,
    warmup: int = 20,
) -> None:
    frame = _make_frame()
    for _ in range(warmup):
        await runner(frame, region_plan, hue, wled, n_region)
    hue_samples: list[float] = []
    total_samples: list[float] = []
    for _ in range(iters):
        hue_dt, total_dt = await runner(frame, region_plan, hue, wled, n_region)
        hue_samples.append(hue_dt)
        total_samples.append(total_dt)
    hue_mean = statistics.mean(hue_samples)
    hue_p95 = sorted(hue_samples)[int(len(hue_samples) * 0.95) - 1]
    total_mean = statistics.mean(total_samples)
    print(
        f"  {label:<40}  hue_loop_ms={hue_mean:6.3f} (p95={hue_p95:6.3f})  "
        f"frame_ms={total_mean:6.3f}"
    )


async def run_scenario(
    name: str,
    n_regions: int,
    n_wled_devices: int,
    led_count: int,
    n_region: int,
    n_hue_channels: int = 6,
) -> None:
    print(
        f"\n[{name}] regions={n_regions} wled_devices={n_wled_devices} "
        f"led_count={led_count} n_region={n_region}"
    )
    region_plan = {
        f"r{i}": (_make_region_mask(), n_region, "auto")
        for i in range(n_regions)
    }
    region_ids = list(region_plan.keys())
    hue = FakeHue(n_channels=n_hue_channels)
    hue.bind(region_ids)
    wled = FakeWled(
        n_devices=n_wled_devices,
        led_count=led_count,
        n_channels_per_dev=1,
    )
    wled.bind(region_ids)
    await measure(
        "CURRENT (shared n=N)",
        current_frame,
        region_plan,
        hue,
        wled,
        n_region,
    )
    await measure(
        "SPLIT  (hue n=1 / wled n=N to_thread)",
        split_frame,
        region_plan,
        hue,
        wled,
        n_region,
    )


async def main() -> None:
    print("WLED activation latency benchmark")
    print("=" * 80)
    await run_scenario("baseline (no wled)", n_regions=6, n_wled_devices=0, led_count=0, n_region=1)
    await run_scenario("wled 1dev 100 LEDs",  n_regions=6, n_wled_devices=1, led_count=100, n_region=100)
    await run_scenario("wled 1dev 300 LEDs",  n_regions=6, n_wled_devices=1, led_count=300, n_region=300)
    await run_scenario("wled 4dev 300 LEDs",  n_regions=6, n_wled_devices=4, led_count=300, n_region=300)
    await run_scenario("wled 4dev 480 LEDs",  n_regions=6, n_wled_devices=4, led_count=480, n_region=480)


if __name__ == "__main__":
    asyncio.run(main())
