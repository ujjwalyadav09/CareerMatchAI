"""Synthetic fair generator and evaluation (paper Sec. VIII).

Run:  python -m careermatch.simulate          (prints Tables III and IV)
      python -m careermatch.simulate --runs 3 --out results.md
"""
import argparse
import heapq
import math
import random
import statistics as st

from .skills import CLUSTERS, VOCABULARY
from . import matching as M
from .scheduling import ScheduleState, auto_schedule

CLUSTER_BRANCHES = {
    "software": ["CSE", "IT"], "data": ["CSE", "IT"], "cloud": ["CSE", "IT"],
    "hardware": ["ECE", "EE"], "mechanical": ["ME"], "business": ["MBA"], "design": ["DES"],
}
ALL_BRANCHES = sorted({b for bs in CLUSTER_BRANCHES.values() for b in bs})
NEIGHBOURS = {
    "software": ["data", "cloud"], "data": ["software"], "cloud": ["software"],
    "hardware": ["software"], "mechanical": ["hardware"], "business": ["design", "data"],
    "design": ["software", "business"],
}

SCENARIOS = {"Small": (150, 10), "Medium": (400, 20), "Large": (800, 30)}
SLOTS, SLOT_LEN, DESKS, MAX_BOOK, K, TAU = 48, 10, 3, 4, 5, 0.35


# ------------------------------------------------------------------ generator
def gen_student(i, rng):
    cl = rng.choice(list(CLUSTERS))
    true = set(rng.sample(CLUSTERS[cl], min(len(CLUSTERS[cl]), rng.randint(3, 6))))
    if rng.random() < 0.5:
        nb = rng.choice(NEIGHBOURS[cl])
        true |= set(rng.sample(CLUSTERS[nb], rng.randint(1, 2)))
    observed = {s for s in true if rng.random() < 0.85}
    observed |= set(rng.sample(VOCABULARY, rng.randint(0, 2)))          # spurious entries
    interests = [cl] if rng.random() < 0.8 else [rng.choice(list(CLUSTERS))]
    if rng.random() < 0.3:
        interests.append(rng.choice(NEIGHBOURS[cl]))
    branch = rng.choice(CLUSTER_BRANCHES[cl]) if rng.random() < 0.9 else rng.choice(ALL_BRANCHES)
    cgpa = round(min(10.0, max(5.0, rng.gauss(7.2, 1.0))), 2)
    backlogs = rng.choices([0, 1, 2, 3], weights=[75, 15, 7, 3])[0]
    return {"id": i, "skills": observed, "true_skills": true, "interests": interests,
            "branch": branch, "cgpa": cgpa, "backlogs": backlogs}


def gen_company(j, rng):
    cl = rng.choice(list(CLUSTERS))
    required = rng.sample(CLUSTERS[cl], rng.randint(3, min(5, len(CLUSTERS[cl]))))
    pool = [s for s in CLUSTERS[cl] if s not in required] + CLUSTERS[rng.choice(NEIGHBOURS[cl])]
    preferred = rng.sample([s for s in pool if s not in required], rng.randint(1, 3))
    branches = list(CLUSTER_BRANCHES[cl])
    if rng.random() < 0.4:
        branches.append(rng.choice(ALL_BRANCHES))
    return {"id": j, "domain": cl, "required": required, "preferred": preferred,
            "min_cgpa": rng.choice([6.0, 6.5, 7.0, 7.5, 8.0]),
            "branches": sorted(set(branches)), "max_backlogs": rng.choice([0, 0, 1, 2]),
            "desks": DESKS}


def is_relevant(s, c):
    if not M.eligible(s, c):
        return False
    req = set(c["required"])
    return len(req & s["true_skills"]) / len(req) >= 0.6


# ------------------------------------------------------------------ metrics
def ndcg_at_k(rels, n_relevant, k=K):
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rels[:k]))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, n_relevant)))
    return dcg / ideal if ideal else None


def evaluate_matching(students, companies, recommender):
    hits = shown = viol = 0
    recalls, ndcgs = [], []
    for s in students:
        recs = [c for c, _ in recommender(s, companies)]
        relevant = {c["id"] for c in companies if is_relevant(s, c)}
        rels = [1 if c["id"] in relevant else 0 for c in recs]
        hits += sum(rels)
        shown += len(recs)
        viol += sum(0 if M.eligible(s, c) else 1 for c in recs)
        if relevant:
            recalls.append(sum(rels) / min(K, len(relevant)))
            nd = ndcg_at_k(rels, len(relevant))
            if nd is not None:
                ndcgs.append(nd)
    return {"P": hits / shown if shown else 0, "R": st.mean(recalls) if recalls else 0,
            "NDCG": st.mean(ndcgs) if ndcgs else 0, "Viol": viol / shown if shown else 0}


def ours(s, cs):
    return M.recommend_for_student(s, cs, k=K, tau=TAU)


def baseline(s, cs):
    return M.baseline_recommend(s, cs, k=K, min_overlap=0.15)


# ------------------------------------------------------------------ scheduling
def requested_pairs(students, companies):
    pairs = []
    for s in students:
        for c, sc in M.recommend_for_student(s, companies, k=MAX_BOOK, tau=TAU):
            pairs.append((s["id"], c["id"], sc))
    return pairs


def evaluate_scheduling(students, companies, rng):
    pairs = requested_pairs(students, companies)
    state = ScheduleState({c["id"]: c["desks"] for c in companies}, SLOTS, MAX_BOOK)
    placed, unplaced = auto_schedule(pairs, state, rng)
    # sanity: no clashes, no over-allocation
    seen_student, seen_desk = set(), set()
    for s, c, t, d in placed:
        assert (s, t) not in seen_student and (c, t, d) not in seen_desk
        seen_student.add((s, t)); seen_desk.add((c, t, d))
    capacity = len(companies) * DESKS * SLOTS
    fulfilled = len(placed) / len(pairs) if pairs else 1.0
    utilization = len(placed) / capacity

    # walk-in model: students arrive at random (peak-heavy) times and visit
    # their matched booths in sequence; each booth has DESKS servers, 10-min talks.
    visits = {}
    for s, c, _ in pairs:
        visits.setdefault(s, []).append(c)
    desk_free = {c["id"]: [0.0] * DESKS for c in companies}
    heap = []
    horizon = SLOTS * SLOT_LEN
    for s, booths in visits.items():
        rng.shuffle(booths)
        arrival = min(horizon * 0.75, abs(rng.gauss(90, 70)))  # crowding in the first hours
        heapq.heappush(heap, (arrival, s, 0, booths))
    waits = []
    while heap:
        t, s, idx, booths = heapq.heappop(heap)
        c = booths[idx]
        free = desk_free[c]
        d = min(range(DESKS), key=lambda k: free[k])
        start = max(t, free[d])
        waits.append(start - t)
        free[d] = start + SLOT_LEN
        if idx + 1 < len(booths):
            heapq.heappush(heap, (start + SLOT_LEN + 2, s, idx + 1, booths))  # 2-min walk
    waits.sort()
    p90 = waits[int(0.9 * (len(waits) - 1))] if waits else 0
    return {"fulfilled": fulfilled, "util": utilization,
            "wait_mean": st.mean(waits) if waits else 0, "wait_p90": p90,
            "unplaced": len(unplaced)}


# ------------------------------------------------------------------ driver
def run(runs=10, seed=42):
    res = {}
    for name, (ns, nc) in SCENARIOS.items():
        agg = {"B": [], "O": [], "S": []}
        for r in range(runs):
            rng = random.Random(seed * 1000 + r * 17 + ns)
            students = [gen_student(i, rng) for i in range(ns)]
            companies = [gen_company(j, rng) for j in range(nc)]
            agg["B"].append(evaluate_matching(students, companies, baseline))
            agg["O"].append(evaluate_matching(students, companies, ours))
            agg["S"].append(evaluate_scheduling(students, companies, rng))
        mean = lambda rows: {k: st.mean(r[k] for r in rows) for k in rows[0]}
        res[name] = {k: mean(v) for k, v in agg.items()}
    return res


def format_tables(res):
    lines = ["## Table III - Match relevance (B = keyword baseline)", "",
             "| Scenario | P (B) | P (Ours) | R (B) | R (Ours) | NDCG (B) | NDCG (Ours) | Viol. (B) | Viol. (Ours) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for n, r in res.items():
        b, o = r["B"], r["O"]
        lines.append(f"| {n} | {b['P']:.1%} | {o['P']:.1%} | {b['R']:.1%} | {o['R']:.1%} | "
                     f"{b['NDCG']:.3f} | {o['NDCG']:.3f} | {b['Viol']:.1%} | {o['Viol']:.1%} |")
    lines += ["", "## Table IV - Scheduling efficiency", "",
              "| Scenario | Bookings fulfilled | Desk utilization | Walk-in mean wait | Walk-in P90 wait |",
              "|---|---|---|---|---|"]
    for n, r in res.items():
        s = r["S"]
        ns, nc = SCENARIOS[n]
        lines.append(f"| {n} ({ns}/{nc}) | {s['fulfilled']:.1%} | {s['util']:.1%} | "
                     f"{s['wait_mean']:.1f} min | {s['wait_p90']:.1f} min |")
    lines += ["", "Scheduled interactions have zero queueing wait by construction; "
              "no student-time clashes or desk over-allocations occurred (asserted in every run)."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="CareerMatch AI synthetic evaluation")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", help="write results as Markdown to this file")
    a = ap.parse_args()
    text = format_tables(run(a.runs, a.seed))
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("# CareerMatch AI - Simulation Results\n\n"
                    f"Runs per scenario: {a.runs}, seed: {a.seed}\n\n" + text + "\n")


if __name__ == "__main__":
    main()
