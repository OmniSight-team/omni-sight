"""Train Algorithm 3's modality classifier C and write its file (OMNI-711, D-38).

Logistic regression on the SigLIP 2 text vector of each query of
`datasets/eval/modality_train.csv` (scene or action), scikit-learn's defaults; none of those
queries is in the SM-1 set, and SM-1's queries are never read here. Prints the 5-fold
cross-validated accuracy (fixed seed) and the weights the held-out queries got, then trains on
all of them and writes `omnisight_common/modality_classifier.json`: the coefficients, the
intercept, the text encoder they belong to, the training file's SHA-256 and the accuracy.

The vectors come from ai_workers on the running stack (about a second a query on this CPU), so
that part runs inside `query`; this script, run on the host, pipes itself in and trains here:

    docker compose up -d
    uv run python scripts/train_modality_classifier.py
"""

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "datasets" / "eval" / "modality_train.csv"
OUT = ROOT / "services" / "common" / "omnisight_common" / "modality_classifier.json"
FOLDS = 5
SEED = 711


def _encode_inside(texts: list[str]) -> dict:
    """Inside `query`: each text's vector, from ai_workers' pinned SigLIP 2."""
    import httpx

    vectors, model, revision = [], None, None
    for text in texts:
        response = httpx.post("http://ai-workers:8000/encode/text", json={"q": text}, timeout=120)
        response.raise_for_status()
        body = response.json()
        vectors.append(body["vector"])
        model, revision = body["model"], body["model_revision"]
    return {"vectors": vectors, "model": model, "model_revision": revision}


def _encode(texts: list[str]) -> dict:
    return json.loads(subprocess.run(
        ["docker", "compose", "exec", "-T", "query", "uv", "run", "--package", "omnisight-query", "python", "-", "--inside", json.dumps(texts)],
        input=Path(__file__).read_bytes(), capture_output=True, check=True,
    ).stdout)


def train(vectors, labels: list[str]) -> dict:
    """C on these vectors; `w_f` is the probability of `scene`. scikit-learn orders the classes
    alphabetically, so `scene` is the positive class of its one set of coefficients."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    x, y = np.asarray(vectors, np.float64), np.asarray(labels)
    folds = StratifiedKFold(FOLDS, shuffle=True, random_state=SEED)
    held_out = cross_val_predict(LogisticRegression(), x, y, cv=folds, method="predict_proba")[:, 1]
    predicted = np.where(held_out >= 0.5, "scene", "action")
    model = LogisticRegression().fit(x, y)
    assert list(model.classes_) == ["action", "scene"]
    return {
        "coefficients": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "cv_accuracy": float((predicted == y).mean()),
        "cv_wrong": np.flatnonzero(predicted != y).tolist(),
        "cv_w_f_scene": float(held_out[y == "scene"].mean()),
        "cv_w_f_action": float(held_out[y == "action"].mean()),
    }


def main() -> int:
    with open(TRAIN, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    texts, labels = [r["text"] for r in rows], [r["label"] for r in rows]
    encoded = _encode(texts)
    result = train(encoded["vectors"], labels)
    wrong = result.pop("cv_wrong")
    print(f"{len(rows)} queries, {FOLDS}-fold cross-validated accuracy {result['cv_accuracy']:.1%}")
    print(f"held-out mean w_f: scene queries {result['cv_w_f_scene']:.3f}, action queries {result['cv_w_f_action']:.3f}")
    for i in wrong:
        print(f"  wrong: [{labels[i]}] {texts[i]}")
    data = {
        "model": encoded["model"],
        "model_revision": encoded["model_revision"],
        "trained_on": TRAIN.relative_to(ROOT).as_posix(),
        "trained_on_sha256": hashlib.sha256(TRAIN.read_bytes()).hexdigest(),
        "cv_folds": FOLDS,
        "cv_seed": SEED,
        **result,
    }
    OUT.write_text(json.dumps(data) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT).as_posix()}: {OUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--inside"]:
        sys.stdout.write(json.dumps(_encode_inside(json.loads(sys.argv[2]))))
        sys.exit(0)
    sys.exit(main())
