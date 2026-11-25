# CareerMatch AI - Simulation Results

Runs per scenario: 10, seed: 42

## Table III - Match relevance (B = keyword baseline)

| Scenario | P (B) | P (Ours) | R (B) | R (Ours) | NDCG (B) | NDCG (Ours) | Viol. (B) | Viol. (Ours) |
|---|---|---|---|---|---|---|---|---|
| Small | 24.8% | 76.8% | 96.4% | 93.7% | 0.879 | 0.932 | 67.1% | 0.0% |
| Medium | 25.5% | 78.6% | 93.9% | 95.1% | 0.805 | 0.943 | 66.7% | 0.0% |
| Large | 32.0% | 80.1% | 88.4% | 94.2% | 0.755 | 0.933 | 60.3% | 0.0% |

## Table IV - Scheduling efficiency

| Scenario | Bookings fulfilled | Desk utilization | Walk-in mean wait | Walk-in P90 wait |
|---|---|---|---|---|
| Small (150/10) | 100.0% | 6.6% | 0.1 min | 0.0 min |
| Medium (400/20) | 100.0% | 16.0% | 1.1 min | 4.7 min |
| Large (800/30) | 100.0% | 31.9% | 15.9 min | 51.8 min |

Scheduled interactions have zero queueing wait by construction; no student-time clashes or desk over-allocations occurred (asserted in every run).
