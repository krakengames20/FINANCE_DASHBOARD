"""Opt-in live sidecar check; never run by the offline test suite.

python scripts/check_google_trends.py --terms "ChatGPT, Claude, Gemini"
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.google_trends import WINDOWS, TrendsError, build_query, fetch_interest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terms", default="ChatGPT, Claude, Gemini")
    parser.add_argument("--geo", default="US")
    parser.add_argument("--window", choices=list(WINDOWS))
    parser.add_argument("--provider", choices=["browser", "http"], default="browser")
    args = parser.parse_args()
    windows = [args.window] if args.window else list(WINDOWS)
    destination = Path(__file__).resolve().parents[1] / ".cache" / "google_trends"
    destination.mkdir(parents=True, exist_ok=True)
    for index, window in enumerate(windows):
        if index:
            time.sleep(3)
        try:
            query = build_query(args.terms, window, args.geo)
            result = fetch_interest(query, refresh=True, provider=args.provider)
        except (TrendsError, ValueError) as exc:
            print(f"FAIL {window}: {exc}", flush=True)
            return 1
        path = destination / f"live_{window.replace(' ', '_')}.csv"
        path.write_bytes(result.csv_bytes())
        print(f"OK {window} ({result.source}): {len(result.values)} observations, "
              f"{result.values.index.min()} to {result.values.index.max()}, "
              f"{int(result.partial.sum())} partial periods; saved {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
