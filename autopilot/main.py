"""Autopilot long-running loop.

Usage:
    python -m autopilot.main                    # default: tick every 60s
    python -m autopilot.main --interval 30      # custom tick
    python -m autopilot.main --max-iterations 5 # bounded for testing
    python -m autopilot.main --once             # run_once() and exit

Stops cleanly on:
- autopilot/PAUSE file present (polled each tick)
- max-iterations reached (if specified)
- KeyboardInterrupt (Ctrl-C)

After each iteration, appends to today's digest at autopilot/runs/digest-<date>.md.
"""
import argparse
import datetime
import sys
import time
from typing import List

from autopilot.digest import write_digest
from autopilot.killswitch import is_paused
from autopilot.loop import LoopResult, run_once
from server.logging_setup import configure_logging, get_logger

configure_logging()
_log = get_logger("autopilot_main")


def run_loop(interval_seconds: int = 60,
             max_iterations: int | None = None,
             pause_path: str = "autopilot/PAUSE") -> List[LoopResult]:
    """Run the autopilot tick forever (or until max_iterations / PAUSE).

    Returns the list of LoopResults observed (useful for testing and for
    one final digest write at shutdown).
    """
    results: List[LoopResult] = []
    iteration = 0
    _log.info("autopilot_main_start", interval_seconds=interval_seconds,
              max_iterations=max_iterations)

    try:
        while True:
            iteration += 1
            if max_iterations is not None and iteration > max_iterations:
                _log.info("autopilot_main_max_iterations_reached", n=iteration - 1)
                break
            if is_paused(pause_path):
                _log.info("autopilot_main_paused", iteration=iteration)
                results.append(LoopResult(status="paused"))
            else:
                _log.info("autopilot_main_tick", iteration=iteration)
                try:
                    result = run_once(pause_path=pause_path)
                except Exception as e:
                    _log.error("autopilot_main_tick_failed", error=str(e), iteration=iteration)
                    result = LoopResult(status="error", detail=str(e)[:200])
                results.append(result)
                _log.info("autopilot_main_tick_done", iteration=iteration,
                          status=result.status, item=result.item_slug,
                          branch=result.branch)
                # Refresh today's digest after every meaningful event.
                if result.status not in ("idle", "paused"):
                    try:
                        path = write_digest(results)
                        _log.info("digest_updated", path=path, results_count=len(results))
                    except Exception as e:
                        _log.warning("digest_write_failed", error=str(e))

            if max_iterations is not None and iteration >= max_iterations:
                break

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        _log.info("autopilot_main_interrupted")

    # Final digest at shutdown so even an empty run leaves a marker.
    try:
        path = write_digest(results)
        _log.info("autopilot_main_shutdown_digest", path=path)
    except Exception as e:
        _log.warning("digest_write_failed_shutdown", error=str(e))

    return results


def main():
    ap = argparse.ArgumentParser(description="Autopilot long-running tick loop")
    ap.add_argument("--interval", type=int, default=60, help="seconds between ticks")
    ap.add_argument("--max-iterations", type=int, default=None,
                    help="stop after N ticks (default: unbounded)")
    ap.add_argument("--once", action="store_true", help="run a single tick and exit")
    ap.add_argument("--pause-path", default="autopilot/PAUSE")
    args = ap.parse_args()

    if args.once:
        args.max_iterations = 1
        args.interval = 0

    results = run_loop(interval_seconds=args.interval,
                       max_iterations=args.max_iterations,
                       pause_path=args.pause_path)
    print(f"finished {len(results)} iterations")
    for r in results:
        print(f"  - {r.status}: {r.item_slug or '-'} {r.branch or ''} {r.detail}")


if __name__ == "__main__":
    main()
