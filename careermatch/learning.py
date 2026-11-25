"""Machine-learned match weights (paper Sec. X, future scope: "learning the score weights
from feedback and interview outcomes").

Each attended booking becomes a training example with features
    x = [F (skill fit), I (interest), A (academic margin)]
and label y = 1 if the company moved the student to interview/offer, else 0. If no
outcomes have been recorded at all, the student's relevance rating (>= 4) is used instead.

A logistic-regression model is trained by gradient descent (pure Python, no extra
dependencies). Its positive coefficients, normalised to sum to 1, become suggested
weights for Eq. (3). We report hold-out AUC of the current weights vs. the learned ones.
"""
import math
import random

from . import matching as M

FEATURES = ("skill", "interest", "academic")


def features(s, c):
    return [M.skill_fit(s, c), M.interest(s, c), M.academic_margin(s, c)]


def build_dataset(students, companies, bookings, outcomes, s_feedback):
    st = {s["id"]: s for s in students}
    co = {c["id"]: c for c in companies}
    pos = {(o["student_id"], o["company_id"]) for o in outcomes}
    rel = {(f["student_id"], f["company_id"]): f["relevance"] for f in s_feedback if f.get("relevance")}
    X, y = [], []
    for b in bookings:
        if b["status"] != "attended":
            continue
        s, c = st.get(b["student_id"]), co.get(b["company_id"])
        if not s or not c:
            continue
        key = (s["id"], c["id"])
        if pos:
            label = int(key in pos)
        elif key in rel:
            label = int(rel[key] >= 4)
        else:
            continue
        X.append(features(s, c))
        y.append(label)
    return X, y


def _sigmoid(z):
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def train_logreg(X, y, epochs=3000, lr=0.5, l2=0.001):
    w = [0.0] * len(X[0])
    b = 0.0
    n = len(X)
    for _ in range(epochs):
        gw = [0.0] * len(w)
        gb = 0.0
        for xi, yi in zip(X, y):
            err = _sigmoid(sum(a * x for a, x in zip(w, xi)) + b) - yi
            for j, x in enumerate(xi):
                gw[j] += err * x
            gb += err
        w = [wj - lr * (g / n + l2 * wj) for wj, g in zip(w, gw)]
        b -= lr * gb / n
    return w, b


def auc(scores, labels):
    """Probability a random positive scores above a random negative (ties = 0.5)."""
    P = [s for s, l in zip(scores, labels) if l == 1]
    N = [s for s, l in zip(scores, labels) if l == 0]
    if not P or not N:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in P for n in N)
    return wins / (len(P) * len(N))


def learn_weights(students, companies, bookings, outcomes, s_feedback, current, seed=0):
    """Return a report dict, or {'ok': False, 'reason': ...} when there is too little data."""
    X, y = build_dataset(students, companies, bookings, outcomes, s_feedback)
    if len(X) < 20 or sum(y) < 5 or sum(y) > len(y) - 5:
        return {"ok": False, "n": len(X), "positives": sum(y),
                "reason": "Need at least 20 attended interactions with 5+ positive and 5+ negative outcomes. "
                          "Record attendance/outcomes or use 'Simulate fair day'."}
    idx = list(range(len(X)))
    random.Random(seed).shuffle(idx)
    cut = int(0.7 * len(idx))
    tr, te = idx[:cut], idx[cut:]
    w, b = train_logreg([X[i] for i in tr], [y[i] for i in tr])

    # keep a small floor so no signal is switched off completely by a noisy fit
    pos_w = [max(0.0, v) for v in w]
    pos_w = [v + 0.05 * (sum(pos_w) or 1.0) for v in pos_w]
    total = sum(pos_w) or 1.0
    learned = {k: round(v / total, 3) for k, v in zip(FEATURES, pos_w)}

    def score_with(weights, xi):
        return sum(weights[k] * x for k, x in zip(FEATURES, xi))

    yte = [y[i] for i in te]
    auc_current = auc([score_with(current, X[i]) for i in te], yte)
    auc_learned = auc([score_with(learned, X[i]) for i in te], yte)
    preds = [_sigmoid(sum(a * x for a, x in zip(w, X[i])) + b) >= 0.5 for i in te]
    acc = sum(int(p) == l for p, l in zip(preds, yte)) / len(te) if te else None
    return {"ok": True, "n": len(X), "positives": sum(y), "train": len(tr), "test": len(te),
            "coefficients": dict(zip(FEATURES, [round(v, 3) for v in w])), "intercept": round(b, 3),
            "learned": learned, "current": current, "auc_current": auc_current,
            "auc_learned": auc_learned, "accuracy": acc}
