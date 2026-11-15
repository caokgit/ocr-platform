#!/usr/bin/env python3
"""Move @champion of region-detector, by a person: only to a version that passed its gate against the current champion.

    MLFLOW_TRACKING_URI=http://localhost:5000 ~/.local/bin/uv run --no-project -q --python 3.12 \
      --with mlflow-skinny==3.18.0 python -I pipelines/detector/promote.py <version>
    ... promote.py --rollback <version>     # back to a version that was champion before

Spec: docs/specs/training-platform.md#decisions (row 12). Records who, when and the previous champion as tags.
The MLflow UI can still move an alias by hand; this command is the guard, not MLflow.
"""

import argparse
import getpass
import sys
from datetime import datetime, timezone

from mlflow import MlflowClient

MODEL = "region-detector"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version")
    ap.add_argument("--rollback", action="store_true", help="the version was champion before; no new gate needed")
    a = ap.parse_args()
    c = MlflowClient()
    current = c.get_model_version_by_alias(MODEL, "champion")
    mv = c.get_model_version(MODEL, a.version)
    if mv.tags.get("diagnostic"):
        sys.exit(f"refused: version {mv.version} is diagnostic ({mv.tags['diagnostic']}), never promotable")
    if mv.version == current.version:
        sys.exit(f"version {mv.version} is already @champion")
    if a.rollback:
        if mv.tags.get("was_champion") != "true":
            sys.exit(f"refused: version {mv.version} was never @champion, so it cannot be rolled back to")
    else:
        gate, against = mv.tags.get("gate"), mv.tags.get("gate_champion_version")
        if gate != "passed":
            sys.exit(f"refused: version {mv.version}'s gate is {gate or 'not run'}")
        if against != current.version:
            sys.exit(f"refused: version {mv.version} passed against version {against}, but @champion is "
                     f"{current.version} now; run its gate again")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    c.set_model_version_tag(MODEL, current.version, "was_champion", "true")
    c.set_registered_model_alias(MODEL, "champion", mv.version)
    for k, v in {"was_champion": "true", "promoted_at": now, "promoted_by": getpass.getuser(),
                 "previous_champion": current.version, "promoted_as": "rollback" if a.rollback else "gate"}.items():
        c.set_model_version_tag(MODEL, mv.version, k, v)
    print(f"alias champion: {current.version} -> {mv.version} ({'rollback' if a.rollback else 'gate passed'})")


if __name__ == "__main__":
    main()
