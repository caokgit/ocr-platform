#!/usr/bin/env python3
"""The gate step: version N of region-detector against @champion on the frozen test split; report and tags.

Spec: docs/specs/training-platform.md#the-gate. Settings from the WorkflowTemplate's environment: CANDIDATE (a
version number), DATASET, MARGINS ("m1,m2"), MLFLOW_TRACKING_URI, S3_ENDPOINT and the S3 key. The gate never
moves an alias; it exits 0 whether the version passed or failed: the report is its result.
"""

import json
import os
from pathlib import Path

import labio

WORK = Path(os.environ.get("WORK", "/work"))
MODEL = "region-detector"


def weights_of(client, version, dest):
    import mlflow
    mv = client.get_model_version(MODEL, str(version))
    folder = Path(mlflow.artifacts.download_artifacts(artifact_uri=mv.source, dst_path=str(dest)))
    name = mv.tags.get("weights_file", "best.pt")
    return mv, folder / name


def main():
    import mlflow
    from mlflow import MlflowClient
    import gate

    c = MlflowClient()
    candidate = os.environ["CANDIDATE"]
    champion = c.get_model_version_by_alias(MODEL, "champion")
    m1, m2 = (float(x) for x in os.environ.get("MARGINS", "0.02,0.02").split(","))
    s3 = labio.s3()
    listing = labio.test_list(s3, os.environ["DATASET"], WORK)
    pages = gate.test_pages(None, listing)
    copy = WORK / "data" / os.environ["DATASET"]
    labio.fetch_copy(s3, os.environ["DATASET"], copy, only=pages)
    _, champ_w = weights_of(c, champion.version, WORK / "champion")
    cand_mv, cand_w = weights_of(c, candidate, WORK / "candidate")
    out = WORK / "gate"
    out.mkdir(parents=True, exist_ok=True)
    report, lines = gate.run(copy, out, str(champ_w), str(cand_w), (m1, m2), listing)
    print("\n".join(lines), flush=True)

    result = "passed" if report["rule"]["passed"] else "failed"
    mlflow.set_experiment(f"{MODEL}-gate")
    with mlflow.start_run(run_name=f"v{candidate}-vs-v{champion.version}") as run:
        mlflow.log_params({"candidate_version": candidate, "champion_version": champion.version,
                           "margin_mAP50_95": m1, "margin_recall_service": m2, "dataset": os.environ["DATASET"],
                           "test_split_sha256": gate.TEST_SHA256, "resamples": gate.RESAMPLES, "seed": gate.SEED})
        for role, m in (("champion", report["models"][0]), ("candidate", report["models"][1])):
            for k in ("mAP50_95", "mAP50", "recall_service", "precision_service"):
                mlflow.log_metrics({f"{role}.{k}": m[k]["value"], f"{role}.{k}.low": m[k]["interval"][0],
                                    f"{role}.{k}.high": m[k]["interval"][1]})
        for k, d in report["difference"].items():
            mlflow.log_metrics({f"diff.{k}": d["value"], f"diff.{k}.low": d["interval"][0],
                                f"diff.{k}.high": d["interval"][1]})
        mlflow.set_tags({"result": result, "better": str(report["rule"]["better"]).lower(),
                         "candidate_weights_sha256": cand_mv.tags.get("weights_sha256", "")})
        mlflow.log_artifact(str(out / "report.json"))
        mlflow.log_artifact(str(out / "report.txt"))
        for key, value in {"gate": result, "gate_champion_version": champion.version,
                           "gate_run_id": run.info.run_id,
                           "gate_mAP50_95": str(report["models"][1]["mAP50_95"]["value"])}.items():
            c.set_model_version_tag(MODEL, candidate, key, value)
    print(json.dumps({"version": candidate, "champion": champion.version, "gate": result,
                      "better": report["rule"]["better"]}))


if __name__ == "__main__":
    main()
