# CareerMatch AI: Evaluation Report

This report covers **match relevance** and **scheduling efficiency** (the two evaluation targets in the project brief),
plus an evaluation of the **machine-learned weight model**. All numbers can be regenerated with the commands shown.

## 1. Method

Real career-fair outcome data was not available, so evaluation uses a synthetic fair generator
(`careermatch/simulate.py`) designed to resemble campus conditions:

- **Skills:** 7 clusters (software, data, cloud, hardware, mechanical, business, design), 40-skill vocabulary.
- **Students:** each has a hidden "true" skill set (3–6 skills from one cluster, sometimes 1–2 from a neighbouring cluster).
  The *observed* profile keeps each true skill with 85% probability and adds 0–2 spurious skills, which mimics incomplete,
  noisy self-reporting. Interests match the student's cluster 80% of the time. CGPA ~ N(7.2, 1.0) clipped to [5, 10];
  backlogs 0/1/2/3 with 75/15/7/3% probability; branch follows the cluster 90% of the time.
- **Companies:** 3–5 required and 1–3 preferred skills, minimum CGPA in {6.0 … 8.0}, permitted branches, and a backlog limit of 0–2.
- **Ground truth:** a company is *relevant* to a student if the student is eligible **and** truly holds at least 60% of the
  company's required skills (judged on hidden true skills, not the noisy profile).
- **Baseline:** rank all companies by Jaccard keyword overlap between the student's skills and the company's skills, with
  **no eligibility filter**, keeping the top 5 with overlap ≥ 0.15.
- **Proposed method:** the hard eligibility filter (Eq. 1) followed by the weighted score
  M = 0.60·F + 0.25·I + 0.15·A (Eq. 2–3), top k = 5 with M ≥ τ = 0.35.

| Parameter | Value |
|---|---|
| Fair duration / slot length | 8 h / 10 min (48 slots per desk) |
| Recruiter desks per company | 3 |
| Scenarios (students/companies) | 150/10, 400/20, 800/30 |
| Bookings per student (max) | 4 (top-ranked matches) |
| Shortlist size k / threshold τ | 5 / 0.35 |
| Independent runs per scenario | 10 (mean reported), seed 42 |

Run: `python -m careermatch.simulate --runs 10 --out results.md`

## 2. Match relevance

Metrics: **P** = precision of the delivered shortlist, **R** = recall@5 against the relevant set,
**NDCG@5** with binary relevance, **Viol.** = share of recommendations that break at least one company eligibility rule.

| Scenario | P (Baseline) | P (Ours) | R (B) | R (Ours) | NDCG (B) | NDCG (Ours) | Viol. (B) | Viol. (Ours) |
|---|---|---|---|---|---|---|---|---|
| Small 150/10 | 24.8% | **76.8%** | 96.4% | 93.7% | 0.879 | **0.932** | 67.1% | **0.0%** |
| Medium 400/20 | 25.5% | **78.6%** | 93.9% | 95.1% | 0.805 | **0.943** | 66.7% | **0.0%** |
| Large 800/30 | 32.0% | **80.1%** | 88.4% | 94.2% | 0.755 | **0.933** | 60.3% | **0.0%** |

**Findings**

- Precision roughly **triples** (25–32% → 77–80%): most baseline recommendations are irrelevant, mainly because they ignore
  eligibility.
- **60–67% of baseline recommendations violate an eligibility rule**, so students would queue at booths that cannot hire them.
  The proposed engine produces **zero** violations by construction, because ineligible pairs are filtered before ranking.
- NDCG@5 stays at about 0.93–0.94 for the proposed method at every scale, while the baseline drops from 0.88 to 0.76 as more
  companies compete for each student.
- Baseline recall falls from 96% to 88% as the fair grows. The proposed method holds about 94%.

## 3. Scheduling efficiency

Scheduled interactions are compared against a **walk-in model**: students arrive at random, peak-heavy times (most arrive in
the first hours) and visit their matched booths in sequence. Each visit is served by the first free desk, with 10-minute
conversations and a 2-minute walk between booths.

| Scenario | Bookings fulfilled | Desk utilization | Walk-in mean wait | Walk-in P90 wait | Scheduled wait |
|---|---|---|---|---|---|
| Small (150/10) | 100% | 6.6% | 0.1 min | 0.0 min | 0 |
| Medium (400/20) | 100% | 16.0% | 1.1 min | 4.7 min | 0 |
| Large (800/30) | 100% | 31.9% | **15.9 min** | **51.8 min** | **0** |

**Findings**

- The scheduler placed **100% of requested bookings** in every run, with **zero student-time clashes and zero desk
  over-allocations** (checked by assertion in every run).
- At small and medium scale, walk-in queues are short because capacity is plentiful. At large scale, walk-in visitors wait
  ~16 minutes on average and 1 in 10 waits nearly an hour. Pre-booked slots remove that queueing entirely.

## 4. Machine-learned match weights

The placement office can train a logistic-regression model on attended interactions (features F, I, A; label = moved to
interview/offer) and compare it with the current weights on a 30% hold-out set (`careermatch/learning.py`, Admin → AI settings).

Example demo run (150 students, 12 companies; auto-schedule → *Simulate fair day* → *Train model*). Exact values vary between
runs because slot assignment is random:

| | Skill | Interest | Academic | Hold-out AUC |
|---|---|---|---|---|
| Current (paper) weights | 0.60 | 0.25 | 0.15 | 0.752 |
| Learned weights | 0.88 | 0.04 | 0.07 | **0.788** |

144 examples (64 positive). The model correctly identifies skill fit as the dominant driver of interview outcomes in the
simulated fair, and the learned weights rank hold-out interactions better than the hand-set ones.

## 5. Limitations

1. The data is synthetic, and its ground truth uses the same skill vocabulary as the matcher, so absolute numbers will differ
   at a real fair. The comparison is best read as relative.
2. These figures differ from the original paper's Tables III/IV (which report 84–89% precision) because the generator is a
   re-implementation; the trends are the same.
3. The walk-in model is a simplified queue (no group visits or changes of mind).
4. The weight model is trained only on interactions that were booked, which are already high-scoring pairs (selection bias).
   It also needs a real fair's outcomes to be meaningful; the "Simulate fair day" data is for demonstration only.
5. AI coach and recruiter-brief quality has not been formally evaluated. Recruiters should treat briefs as decision support,
   not decisions.
