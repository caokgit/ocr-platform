#!/usr/bin/env python3
"""Register the production weights as region-detector version 1 and point @champion at it (platform engineer, once).

    MLFLOW_TRACKING_URI=http://localhost:5000 ~/.local/bin/uv run --no-project -q --python 3.12 \
      --with mlflow-skinny==3.18.0 --with pyyaml python -I pipelines/detector/register_production.py \
      data/weights/production/production.pt

Spec: docs/specs/training-platform.md#decisions (row 11). The checkpoint's train_args are the recipe file
recipes/production.yaml (read from the checkpoint without executing it); the dataset it was trained on is not recorded.
"""

import hashlib
import sys
from pathlib import Path

import mlflow
import yaml
from mlflow import MlflowClient

MODEL = "region-detector"
CODE = Path(__file__).resolve().parent


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    weights = Path(sys.argv[1])
    body = weights.read_bytes()
    md5, sha = hashlib.md5(body).hexdigest(), hashlib.sha256(body).hexdigest()
    c = MlflowClient()
    if c.search_registered_models(filter_string=f"name='{MODEL}'"):
        sys.exit(f"{MODEL} exists already; version 1 is registered once")
    recipe = yaml.safe_load((CODE / "recipes" / "production.yaml").read_text())
    mlflow.set_experiment(MODEL)
    with mlflow.start_run(run_name="production-import") as run:
        mlflow.log_params(recipe)
        mlflow.set_tags({"dataset": "unknown: trained on Ultralytics Platform, 2026-09-07",
                         "source": "the weights file dev and stg run",
                         "weights_md5": md5, "weights_sha256": sha, "ultralytics": "8.4.142"})
        mlflow.log_artifact(str(weights), "weights")
        c.create_registered_model(MODEL, description="The OCR service's one-class region detector")
        mv = c.create_model_version(MODEL, f"{run.info.artifact_uri}/weights", run_id=run.info.run_id,
                                    tags={"weights_sha256": sha, "weights_md5": md5, "weights_file": weights.name,
                                          "dataset": "unknown", "was_champion": "true"})
    c.set_registered_model_alias(MODEL, "champion", mv.version)
    print(f"registered {MODEL} version {mv.version} (MD5 {md5[:12]}..., sha256 {sha[:12]}...); "
          f"alias champion -> {mv.version}")


if __name__ == "__main__":
    main()
