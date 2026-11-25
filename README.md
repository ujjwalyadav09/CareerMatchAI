# CareerMatch AI

Implementation of the paper *"CareerMatch AI: A Skill-and-Eligibility-Based Matching, Slot-Scheduling
and Analytics Platform for Campus Career Fairs"* (Yadav & Yadav, LPU).

A Flask + SQLite web app with three roles: **students**, **companies** and the **placement office**.
It also includes a synthetic-fair simulator that reproduces the paper's evaluation (Sec. VIII).

**Documents:** [Technical documentation](docs/TECHNICAL_DOCUMENTATION.md) · [Evaluation report](docs/EVALUATION_REPORT.md)

## Project deliverables

| Expected delivery | Where |
|---|---|
| Functional career-fair matching and scheduling platform | `python run.py` |
| Skill-and-eligibility-based matching engine | `careermatch/matching.py` |
| Slot-booking system | `careermatch/scheduling.py`, student company pages, admin auto-scheduler |
| Company-facing shortlist and profile-review interface | Company → Shortlist & Schedule, candidate pages |
| Post-event feedback from students and companies | Student → Feedback, Company → Feedback |
| Placement-office analytics dashboard | Admin → Analytics (+ CSV export) |
| Evaluation report (match relevance, scheduling efficiency) | [`docs/EVALUATION_REPORT.md`](docs/EVALUATION_REPORT.md), `python -m careermatch.simulate` |
| Technical documentation + demo with representative scenarios | [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md) §11, Admin → AI settings → Simulate fair day |

## AI features

| Feature | What it does |
|---|---|
| **Resume → profile** | Reads a PDF/DOCX/TXT resume and pre-fills skills, interests, CGPA, branch, graduation year, backlogs |
| **AI Career Coach** (students) | Personalised plan per company: why you match, gaps to close (with learning tasks), booth pitch, interview topics |
| **AI recruiter brief** (companies) | Short candidate summary: overall fit, strengths, what to probe in the interview |
| **Learned match weights** (admin) | Logistic regression on fair outcomes learns better weights for the match score; reports hold-out AUC vs current weights |

The Coach and the brief can use a **free** AI provider. Without a key they use a built-in offline generator,
so the app always works.

**Turn on free AI (2 minutes, no credit card):**
1. Get a free key: **Google Gemini** at https://aistudio.google.com/apikey (sign in with a Google account → *Create API key*),
   or **Groq** at https://console.groq.com/keys.
2. Run the app, log in as `admin` → **AI settings** → paste the key into the matching row → **Save & test connection**.

The model is detected automatically (leave the model field blank). Environment variables `GEMINI_API_KEY`, `GROQ_API_KEY`
or (paid) `ANTHROPIC_API_KEY` also work.

## Features (mapped to the paper)

| Paper section | What's implemented | Where |
|---|---|---|
| III-C Data model | Students (skills, interests, CGPA, branch, backlogs, grad year, resume link), companies (role, domain, required/preferred skills, eligibility rules, desks), bookings, feedback, outcomes | `careermatch/db.py` |
| VII Skill normalization | 40-skill controlled vocabulary in 7 clusters, aliases (`JS` → `JavaScript`, `ML` → `Machine Learning`, …) | `careermatch/skills.py` |
| Resume → profile (extension) | Upload a PDF/DOCX/TXT resume; name, email, skills (mapped to the vocabulary), interest domains, CGPA (10- or 4-point), branch, graduation year and backlogs are extracted and pre-filled for the student to review. The file is stored and visible only to the student, the admin and matched/booked companies | `careermatch/resume.py`, `/student/resume` |
| IV-A Eligibility filter, Eq. (1) | `E = [CGPA ≥ min]·[branch ∈ allowed]·[backlogs ≤ max]`; ineligible pairs never scored or shown | `matching.eligible` |
| IV-B Match score, Eq. (2)–(3) | `F = 0.8·req coverage + 0.2·pref coverage`, `M = E·(0.60F + 0.25I + 0.15A)`; weights configurable by the admin | `matching.score` |
| IV-C Shortlists & explanations | Top-k (k=5, τ=0.35) per student; ranked pre-fair shortlist per company; matched/missing skills, interest alignment, CGPA margin | `matching.explain` |
| V Slot booking | Manual booking with checks (a) free desk, (b) no student clash, (c) eligible match, (d) booking limit; transactional (`BEGIN IMMEDIATE` + partial unique indexes); cancellation returns slot to the pool | `scheduling.py`, `/student/book` |
| V Auto-scheduling | Pairs processed by descending score, random free valid slot each | `scheduling.auto_schedule`, Admin → *Run auto-scheduler* |
| VI-A Feedback (Table I) | Student: relevance, usefulness, convenience, wait time, comments. Company: candidate quality, skill alignment, # to interview, shortlist accuracy, comments | `/student/feedback`, `/company/feedback` |
| VI-B Analytics | Engagement, match quality, desk utilization by company & hour, interviews/offers by company & branch, skill-gap insights; filters by branch/company/domain; CSV export | `careermatch/analytics.py`, `/admin/analytics` |
| IX Privacy | Companies can open only candidates who matched them or booked them | `/company/candidate/<id>` |
| VIII Evaluation | Synthetic fair generator, keyword (Jaccard) baseline, Precision / Recall@5 / NDCG@5 / violation rate, walk-in queue model | `careermatch/simulate.py` |

## Quick start

```bash
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:5000. On first start the database (`instance/careermatch.db`) is created and seeded with
12 fictional companies and 150 synthetic students.

| Role | Username | Password |
|---|---|---|
| Student | `demo` (or `student1` … `student149`) | `student123` |
| Company | `nimbussoft`, `brightpath`, `quantleaf`, `neuron`, `stratocloud`, `helix`, `siliconcrest`, `forgeworks`, `ledgerline`, `pixelfield`, `orbitops`, `marketly` | `company123` |
| Placement office | `admin` | `admin123` |

To start fresh, stop the server and delete the `instance/` folder.

### Suggested demo walk-through
1. **Student** `demo`: see top matches with explanations → open a company → book a slot → try booking a
   clashing slot (rejected) → edit profile (try `js, ml`) → submit feedback.
   Or sign up a new student → Profile → **Upload & auto-fill** a resume → review → Save → matches appear.
2. **Admin** `admin`: run the auto-scheduler → **AI settings** → Simulate fair day → Train model → Apply learned weights →
   open Analytics, try the filters → export CSVs.
3. **Company** `nimbussoft`: view ranked shortlist → open a candidate → **Generate summary** → mark attendance and
   interview/offer → submit feedback. Students can click **Show preparation guide** on any company page.
4. Back in **Admin → Analytics**: attendance, outcomes and feedback ratings now appear.

## Evaluation

```bash
python -m careermatch.simulate --runs 10 --out results.md
```

Output from this implementation (10 runs per scenario, seed 42) is in [`results.md`](results.md):

| Scenario | P (Baseline) | P (Ours) | NDCG@5 (B) | NDCG@5 (Ours) | Baseline eligibility violations | Ours |
|---|---|---|---|---|---|---|
| Small 150/10 | 24.8% | 76.8% | 0.879 | 0.932 | 67.1% | 0% |
| Medium 400/20 | 25.5% | 78.6% | 0.805 | 0.943 | 66.7% | 0% |
| Large 800/30 | 32.0% | 80.1% | 0.755 | 0.933 | 60.3% | 0% |

The scheduler fulfilled 100% of requested bookings with zero clashes in every scenario; the walk-in model's
mean wait in the large scenario was ~16 min (P90 ~52 min) versus zero for scheduled slots.

The trends match the paper (big precision gain, zero violations, NDCG ≈ 0.93–0.94, queueing only at scale).
The exact numbers differ from the paper's Table III/IV because the synthetic generator's distributions are a
re-implementation, not the authors' original code.

## Tests

```bash
python -m pytest
```

26 tests cover the eligibility rules, Eq. (2)–(3), explanations, all four booking constraints, auto-schedule
priority, resume parsing, the AI assistant (Gemini/Groq requests mocked, model auto-detection, offline fallback, caching), weight learning, and
end-to-end flows for all three roles.

## Project layout

```
CareerMatchAI/
├── run.py                  # start the web server
├── careermatch/
│   ├── app.py              # Flask routes (student / company / admin)
│   ├── db.py               # SQLite schema + helpers
│   ├── skills.py           # vocabulary + alias normalization
│   ├── matching.py         # eligibility filter, score, explanations, baseline
│   ├── scheduling.py       # booking constraints + auto-scheduler
│   ├── analytics.py        # dashboard metrics
│   ├── resume.py           # resume text extraction + profile parsing
│   ├── ai.py               # AI coach / recruiter brief: Gemini, Groq or Claude (+ offline fallback)
│   ├── learning.py         # logistic-regression weight learning
│   ├── fairsim.py          # "simulate fair day" demo data
│   ├── simulate.py         # synthetic evaluation (Tables III & IV)
│   └── seed.py             # demo data
├── templates/              # Jinja2 pages
├── static/style.css
├── docs/                   # technical documentation + evaluation report
├── tests/
└── results.md              # simulation output
```

## Notes
- Set the `SECRET_KEY` environment variable before deploying anywhere other than your own machine.
- All company names and student records in the demo are fictional/synthetic.
