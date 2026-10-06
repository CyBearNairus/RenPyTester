"""The machine-readable report (spec REP-002). Its schema is documented in docs/report-schema.md."""

import json
from pathlib import Path


def write(report, output_dir):
    path = Path(output_dir) / (report.name + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
