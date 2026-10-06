"""Spike runner (milestone M0, throwaway).

Copies a game from an SDK into .cache/work, injects one spike script, runs it with no window,
and prints the events the script wrote.

    python spikes/run.py SPIKE.rpy [--sdk 8.6.0] [--game the_question] [--path 0,1] [--timeout 60]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".cache" / "work"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spike")
    ap.add_argument("--sdk", default="8.6.0")
    ap.add_argument("--game", default="the_question")
    ap.add_argument("--path", default="")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--command", default="run")
    ap.add_argument("--keep", action="store_true", help="reuse the existing working copy")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    sdk = ROOT / ".cache" / "sdk" / f"renpy-{args.sdk}-sdk"
    game = WORK / f"{args.game}-{args.sdk}"
    if not args.keep and game.exists():
        shutil.rmtree(game)
    if not game.exists():
        shutil.copytree(sdk / args.game, game)
    for old in (game / "game").glob("zzz_renpytester_*"):
        old.unlink()
    shutil.copy(ROOT / "spikes" / args.spike, game / "game" / "zzz_renpytester_spike.rpy")

    run_dir = WORK / "run"
    shutil.rmtree(run_dir, ignore_errors=True)
    (run_dir / "logs").mkdir(parents=True)
    events = run_dir / "events.jsonl"

    env = dict(os.environ)
    env.update(
        RENPYTESTER_EVENTS=str(events),
        RENPYTESTER_PATH=args.path,
        RENPY_LOG_BASE=str(run_dir / "logs"),
        RENPY_PERFORMANCE_TEST="0",
        RENPY_RENDERER="sw",
        RENPY_SKIP_MAIN_MENU="1",
        RENPY_SKIP_SPLASHSCREEN="",
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
    )
    env["RENPY_DISABLE_BACKUPS"] = "I take responsibility for this."

    python = sdk / "lib" / "py3-windows-x86_64" / "python.exe"
    cmd = [str(python), str(sdk / "renpy.py"), str(game), args.command, "--savedir", str(run_dir / "saves")]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, env=env, timeout=args.timeout, capture_output=True, text=True)
        code = proc.returncode
        out = (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired as e:
        code = "TIMEOUT"
        out = ((e.stdout or b"").decode(errors="replace") + (e.stderr or b"").decode(errors="replace")).strip()
    elapsed = time.time() - t0

    if events.exists() and not args.quiet:
        for line in events.read_text().splitlines():
            ev = json.loads(line)
            print(json.dumps(ev)[:600])
    if out:
        print("--- process output (tail)")
        print("\n".join(out.splitlines()[-25:]))
    print(f"--- exit={code} wall={elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
