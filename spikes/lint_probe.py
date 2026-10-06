"""Spike for M2: run the engine's lint on a game and print what it writes.

    python spikes/lint_probe.py GAME_DIR [--sdk 8.6.0] [lint options...]
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from renpytester import discovery  # noqa: E402
from renpytester.launcher import build_environment  # noqa: E402


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    version = "8.6.0"
    if "--sdk" in argv:
        index = argv.index("--sdk")
        version = argv[index + 1]
        del argv[index:index + 2]
    source, extra = Path(argv[0]), argv[1:]
    sdk = ROOT / ".cache" / "sdk" / ("renpy-%s-sdk" % version)

    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        copy = work / "game"
        shutil.copytree(source, copy)
        game = discovery.discover(copy, sdk)
        (work / "logs").mkdir()
        env = build_environment(work / "events.jsonl", {}, work / "logs")
        del env["RENPYTESTER_EVENTS"]
        report = work / "lint.txt"
        cmd = [str(game.python), str(game.main_script), str(game.basedir), "lint", str(report), *extra]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        print("exit code:", result.returncode)
        if report.exists():
            print(report.read_text(encoding="utf-8-sig", errors="replace"))
        else:
            print("no report written; output was:")
            print((result.stdout + result.stderr)[-3000:])
        print("files left beside the game:", sorted(p.name for p in copy.iterdir()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
