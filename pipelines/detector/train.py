#!/usr/bin/env python3
"""The train step of train-detector: check the card, fetch the copy, cut validation by document, train, register.

Spec: docs/specs/training-platform.md#the-job. Runs in the Ultralytics image (decision 7); its settings come from
the WorkflowTemplate's environment: DATASET, RECIPE, EPOCHS (empty: the recipe's), WORKERS, MIN_FREE_MIB,
LAB_GIT_COMMIT, IMAGE_REF, BASE_WEIGHTS_KEY, BASE_WEIGHTS_SHA256, MLFLOW_TRACKING_URI, S3_ENDPOINT and the S3 key.
MIN_FREE_MIB_REQUEST (a submission's min_free_mib, which may only raise the floor).
Writes the registered version number to /tmp/version for the gate step.
"""

import hashlib
import json
import os
import signal
import sys
from pathlib import Path

import yaml

import labio

CODE = Path(__file__).absolute().parent  # not resolved: a ConfigMap mount is a symlink into a hidden folder
WORK = Path(os.environ.get("WORK", "/work"))
MODEL = "region-detector"
CARD_BUSY = 75  # not retried: the template's retryStrategy retries only lost pods (decision 14)


def check_card():
    import torch
    free, total = torch.cuda.mem_get_info(0)
    props = torch.cuda.get_device_properties(0)
    card = {"gpu_name": props.name, "gpu_uuid": str(getattr(props, "uuid", "")),
            "gpu_free_mib_at_start": free >> 20, "gpu_total_mib": total >> 20}
    print(json.dumps(card), flush=True)
    # the template's floor; a submission may raise it (min_free_mib), never lower it
    floor = max(int(os.environ.get("MIN_FREE_MIB", "4096")), int(os.environ.get("MIN_FREE_MIB_REQUEST") or 0))
    if card["gpu_free_mib_at_start"] < floor:
        print(f"card busy: {card['gpu_free_mib_at_start']} MiB free, the floor is {floor} MiB; not starting",
              flush=True)
        sys.exit(CARD_BUSY)
    return card


def main():
    import mlflow
    card = check_card()
    dataset, recipe_name = os.environ["DATASET"], os.environ["RECIPE"]
    recipe_file = CODE / "recipes" / f"{recipe_name}.yaml"
    recipe = yaml.safe_load(recipe_file.read_text())
    base = recipe.pop("model")
    if os.environ.get("EPOCHS"):
        recipe["epochs"] = int(os.environ["EPOCHS"])

    client = labio.s3()
    data = WORK / "data" / dataset
    labio.test_list(client, dataset, WORK)
    import gate
    test_pages = gate.test_pages(None, WORK / "test.txt")  # sha256 checked against the frozen split
    manifest, files = labio.fetch_copy(client, dataset, data)
    split = os.environ.get("SPLIT") or "by-document"
    if split == "as-copy":  # diagnostic only: the test documents are trained on (spec, row 16)
        train, val, val_docs = labio.split_as_copy(manifest)
    elif split == "by-document":
        train, val, val_docs = labio.split_for_training(manifest, test_pages)
    else:
        sys.exit(f"split {split!r}: by-document or as-copy")
    (WORK / "train.txt").write_text("".join(f"{data / p}\n" for p in train))
    (WORK / "val.txt").write_text("".join(f"{data / p}\n" for p in val))
    val_docs_text = "".join(f"{d}\n" for d in val_docs)
    (WORK / "data.yaml").write_text(f"train: {WORK / 'train.txt'}\nval: {WORK / 'val.txt'}\nnames:\n  0: item\n")
    print(f"copy {dataset}: {files} files; split {split}: train {len(train)} pages, validation {len(val)} pages "
          f"({len(val_docs)} documents), test {len(test_pages)} pages left out", flush=True)

    weights = labio.fetch(client, os.environ["BASE_WEIGHTS_KEY"], WORK / base)
    if labio.sha256(weights) != os.environ["BASE_WEIGHTS_SHA256"]:
        sys.exit(f"base weights {weights.name}: sha256 differs from the pinned one")

    mlflow.set_experiment(MODEL)
    run = mlflow.start_run(run_name=os.environ.get("ARGO_WORKFLOW", "train-detector"))

    main_pid, run_id = os.getpid(), run.info.run_id
    killed = {"signal": False}

    def stopped(signum, frame):  # lab-down or a person stopped the workflow (spec: the job)
        # The signal reaches the whole process group: the DataLoader workers, forked from here, inherit this handler
        # and only leave; the main process ends the run itself, by a direct call, before PyTorch notices its workers
        # are gone (seen 2026-11-15: the run stayed RUNNING)
        if os.getpid() != main_pid:
            os._exit(0)
        killed["signal"] = True
        from mlflow import MlflowClient
        MlflowClient().set_terminated(run_id, "KILLED")
        os._exit(128 + signum)
    signal.signal(signal.SIGTERM, stopped)

    try:  # the dataset as a run input; the tags below carry the same id if this API refuses
        from mlflow.data.meta_dataset import MetaDataset
        from mlflow.data.http_dataset_source import HTTPDatasetSource
        mlflow.log_input(MetaDataset(source=HTTPDatasetSource(f"s3://{labio.BUCKET}/datasets/ultralytics/{dataset}/"),
                                     name="ultralytics-detector-copy", digest=dataset[-12:]), context="training")
    except Exception as e:  # noqa: BLE001
        print(f"log_input refused ({type(e).__name__}: {e}); the dataset id stays in the tags", flush=True)
    mlflow.set_tags({"dataset": dataset, "recipe": recipe_name, "recipe_sha256": labio.sha256(recipe_file),
                     "git_commit": os.environ.get("LAB_GIT_COMMIT", "unknown"),
                     "image_digest": os.environ.get("IMAGE_REF", "unknown"),
                     "base_weights": base, "base_weights_sha256": os.environ["BASE_WEIGHTS_SHA256"],
                     "test_split_sha256": gate.TEST_SHA256,
                     "val_docs_sha256": hashlib.sha256(val_docs_text.encode()).hexdigest(),
                     "code_sha256": json.dumps({p.name: labio.sha256(p) for p in sorted(CODE.glob("*.py"))}),
                     "argo_workflow": os.environ.get("ARGO_WORKFLOW", ""), "split": split, **card})
    if split == "as-copy":
        mlflow.set_tag("diagnostic", "trained-on-test")
    mlflow.log_text(val_docs_text, "split/val_documents.txt")
    mlflow.log_params({"lab.train_pages": len(train), "lab.val_pages": len(val), "lab.val_documents": len(val_docs)})

    import ultralytics.utils as ul
    from ultralytics import YOLO
    # the image's default folders (/ultralytics/...) are not writable for user 1000; /work also holds the pinned
    # base weights, so the AMP check loads them instead of downloading its own copy. WEIGHTS_DIR is fixed when
    # ultralytics.utils is imported, and check_amp reads it at call time, so it is set here too.
    ul.SETTINGS.update(weights_dir=str(WORK), runs_dir=str(WORK / "runs"), datasets_dir=str(WORK / "data"), sync=False)
    ul.WEIGHTS_DIR = WORK
    os.chdir(WORK)
    try:
        YOLO(str(weights)).train(data=str(WORK / "data.yaml"), device=0, project=str(WORK / "runs"), name="train",
                                 exist_ok=True, workers=int(os.environ.get("WORKERS", "4")), **recipe)
    except BaseException:  # any failure ends the run, so none stays RUNNING
        mlflow.end_run("KILLED" if killed["signal"] else "FAILED")
        raise

    best = WORK / "runs" / "train" / "weights" / "best.pt"
    digest = labio.sha256(best)
    from mlflow import MlflowClient
    c = MlflowClient()
    if not c.search_registered_models(filter_string=f"name='{MODEL}'"):
        c.create_registered_model(MODEL)
    artifacts = {a.path for a in c.list_artifacts(run.info.run_id, "weights")}
    if "weights/best.pt" not in artifacts:  # Ultralytics' callback logs the weights folder at the end
        mlflow.log_artifact(str(best), "weights")
    mv = c.create_model_version(MODEL, f"{run.info.artifact_uri}/weights", run_id=run.info.run_id,
                                tags={"weights_sha256": digest, "weights_file": "best.pt", "dataset": dataset, "split": split,
                                      **({"diagnostic": "trained-on-test"} if split == "as-copy" else {}),
                                      "git_commit": os.environ.get("LAB_GIT_COMMIT", "unknown")})
    mlflow.set_tag("model_version", mv.version)
    mlflow.end_run()
    Path("/tmp/version").write_text(str(mv.version))
    print(f"registered {MODEL} version {mv.version} from run {run.info.run_id} (sha256 of the weights: {digest})")


if __name__ == "__main__":
    main()
