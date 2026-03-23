"""
DTLS Spike Script — Phase 1 gate for HuePictureControl.

PURPOSE:
    Prove that DTLS transport via hue-entertainment-pykit works against a real
    physical Hue Bridge.  This script is intentionally standalone — no FastAPI,
    no asyncio, no application wiring — just raw credentials → DTLS → light.

    The entire Phase 2 / Phase 3 streaming work is contingent on this gate
    passing.  Do not skip it.

PREREQUISITES:
    1. The backend has been started and the pairing flow completed:
         uvicorn main:app --host 0.0.0.0 --port 8000
         curl -X POST http://localhost:8000/api/hue/pair \\
              -H "Content-Type: application/json" \\
              -d '{"bridge_ip": "YOUR_BRIDGE_IP"}'
    2. At least one Entertainment Configuration exists in the Hue app with at
       least one light assigned to it.
    3. This script MUST be run from the host network (or inside the backend
       container) — DTLS/UDP packets must reach the Hue Bridge directly.

USAGE:
    python -m spike.dtls_test [--db-path PATH] [--color COLOR]
                               [--duration SECONDS] [--config-name NAME]

    Defaults: --db-path /app/data/config.db  --color red  --duration 3

OPEN QUESTIONS (to be resolved empirically by running this spike):
    - Does hue_app_id="" work if the bridge stored a real app ID?
      (We always store the real value, so this should not be empty.)
    - Does swversion=0 work if the real value is unknown?
      (We always store the real value fetched from /api/config, so this is a
       non-issue in practice — but watch the log output to confirm.)
    - Is channel_id=0 always valid?  The first channel in the entertainment
      configuration should map to the first light; if no light reacts, try
      iterating channel IDs.
"""

import argparse
import sqlite3
import time

from hue_entertainment_pykit import create_bridge, Entertainment, Streaming


# ---------------------------------------------------------------------------
# Color presets  (CIE xy + brightness)
# Values sourced from Hue developer documentation for sRGB primaries.
# ---------------------------------------------------------------------------
COLOR_PRESETS: dict[str, tuple[float, float, float]] = {
    "red":   (0.675, 0.322, 0.8),
    "green": (0.17,  0.7,   0.8),
    "blue":  (0.153, 0.048, 0.8),
    "white": (0.3127, 0.3290, 1.0),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DTLS spike: send a color to a Hue light via hue-entertainment-pykit.",
    )
    parser.add_argument(
        "--db-path",
        default="/app/data/config.db",
        help="Path to the SQLite database written by the backend (default: /app/data/config.db).",
    )
    parser.add_argument(
        "--color",
        default="red",
        choices=list(COLOR_PRESETS.keys()),
        help="Color to send (default: red).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=3.0,
        help="How long to hold the color in seconds (default: 3).",
    )
    parser.add_argument(
        "--config-name",
        default=None,
        help="Name of the entertainment configuration to use.  If omitted, the first available config is used.",
    )
    return parser.parse_args()


def load_credentials(db_path: str) -> dict:
    """
    Read bridge credentials from the bridge_config table (row id=1).

    Returns a dict with keys matching create_bridge() parameter names.
    Raises SystemExit if no credentials are found.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT bridge_id, rid, ip_address, username, hue_app_id, client_key, swversion, name "
            "FROM bridge_config WHERE id = 1"
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if row is None:
        print(
            "No bridge credentials found. "
            "Run the pairing flow first: POST /api/hue/pair"
        )
        raise SystemExit(1)

    creds = dict(row)

    # Log actual values so we can answer the open questions above.
    print(f"[spike] Loaded credentials from {db_path!r}:")
    print(f"  bridge_id  = {creds['bridge_id']!r}")
    print(f"  rid        = {creds['rid']!r}")
    print(f"  ip_address = {creds['ip_address']!r}")
    print(f"  username   = {creds['username']!r}")
    print(f"  hue_app_id = {creds['hue_app_id']!r}  (open question: is empty string OK?)")
    print(f"  client_key = {creds['client_key'][:8]}...  (truncated)")
    print(f"  swversion  = {creds['swversion']!r}  (open question: is 0 OK?)")
    print(f"  name       = {creds['name']!r}")

    return creds


def build_bridge(creds: dict):
    """
    Map bridge_config columns → create_bridge() keyword arguments.

    Column mapping (from plan interfaces):
        bridge_id  -> identification
        rid        -> rid
        ip_address -> ip_address
        username   -> username
        hue_app_id -> hue_app_id
        client_key -> clientkey
        swversion  -> swversion
        name       -> name
    """
    return create_bridge(
        identification=creds["bridge_id"],
        rid=creds["rid"],
        ip_address=creds["ip_address"],
        username=creds["username"],
        hue_app_id=creds["hue_app_id"],
        clientkey=creds["client_key"],
        swversion=creds["swversion"],
        name=creds["name"],
    )


def select_entertainment_config(entertainment: Entertainment, config_name: str | None):
    """
    Choose an entertainment configuration.

    If config_name is specified, find one whose name matches (case-insensitive).
    Otherwise, return the first available config.

    Raises SystemExit if no configs exist.
    """
    configs = entertainment.get_entertainment_configs()

    if not configs:
        print(
            "No entertainment configurations found. "
            "Create one in the Hue app."
        )
        raise SystemExit(1)

    print(f"[spike] Found {len(configs)} entertainment configuration(s):")
    for cfg in configs:
        print(f"  - {cfg}")

    if config_name is not None:
        for cfg in configs:
            # The config object's string representation or name attribute —
            # try both to be safe.
            cfg_label = getattr(cfg, "name", str(cfg))
            if cfg_label.lower() == config_name.lower():
                print(f"[spike] Selected config by name: {cfg_label!r}")
                return cfg
        print(f"[spike] WARNING: No config named {config_name!r} found; using first config.")

    selected = configs[0]
    print(f"[spike] Using first entertainment config: {selected}")
    return selected


def main() -> None:
    args = parse_args()

    # 1. Load credentials from SQLite.
    creds = load_credentials(args.db_path)

    # 2. Build the Bridge object.
    print("[spike] Creating Bridge object…")
    bridge = build_bridge(creds)

    # 3. Retrieve entertainment configurations.
    print("[spike] Fetching entertainment configurations…")
    entertainment = Entertainment(bridge)
    config = select_entertainment_config(entertainment, args.config_name)
    repo = entertainment.get_ent_conf_repo()

    # 4. Open a DTLS streaming session.
    print("[spike] Starting DTLS stream…")
    streaming = Streaming(bridge, config, repo)
    streaming.start_stream()
    streaming.set_color_space("xyb")

    # 5. Send the chosen color to channel 0.
    x, y, brightness = COLOR_PRESETS[args.color]
    print(f"[spike] Sending color: {args.color!r}  (x={x}, y={y}, bri={brightness})")
    streaming.set_input(x, y, brightness, channel_id=0)

    print(f"Sent {args.color} to channel 0 — check your light!")

    # 6. Hold the color for the requested duration.
    time.sleep(args.duration)

    # 7. Close the DTLS session cleanly.
    streaming.stop_stream()

    print("DTLS spike complete. Stream closed.")


if __name__ == "__main__":
    main()
