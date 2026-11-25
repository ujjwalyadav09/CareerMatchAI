# CareerMatch AI: Technical Documentation

## 1. Overview

CareerMatch AI is a web platform for campus career fairs with three user roles:

| Role | Can do |
|---|---|
| **Student** | Build a profile (manually or from a resume), see ranked company matches with explanations, get AI coaching, book clash-free slots, give feedback |
| **Company** | Set role requirements and eligibility rules, review a ranked pre-fair shortlist and candidate profiles, get AI recruiter briefs, mark attendance and outcomes, give feedback |
| **Placement office (admin)** | Configure the fair, add companies, run the auto-scheduler, view analytics, export CSVs, simulate a fair day, train the weight-learning model |

**Stack:** Python 3.10+, Flask 3, SQLite (standard library), Jinja2 templates, plain CSS. Optional: a free Google Gemini or Groq API key (called over HTTPS with the standard library), the `anthropic` SDK
if you prefer paid Claude, and `pypdf` for PDF resumes. No JavaScript framework, no build step.

## 2. Architecture

```
 Browser ──HTTP──► Flask app (careermatch/app.py)  ── role-based routes + session auth
                     │
   ┌─────────────────┼───────────────────────────────────────────────┐
   │ skills.py     vocabulary + alias normalisation                    │
   │ resume.py     resume text extraction + profile parsing (NLP)      │
   │ matching.py   eligibility filter, weighted score, explanations    │  pure functions,
   │ scheduling.py booking constraints, auto-scheduler                 │  unit-testable
   │ analytics.py  dashboard metrics                                   │
   │ learning.py   logistic-regression weight learning                 │
   │ ai.py         AI coach / recruiter brief: Gemini/Groq/Claude      │
   │ fairsim.py    simulated fair day for demos                        │
   │ simulate.py   offline evaluation (Tables III & IV)                │
   └─────────────────┼───────────────────────────────────────────────┘
                     ▼
               db.py → SQLite (instance/careermatch.db) + instance/uploads/ (resumes)
```

The matching, scheduling, analytics and learning modules don't depend on Flask or the database. They take plain dicts, so
the web app and the offline evaluator use the same code.

## 3. Data model

| Table | Key columns |
|---|---|
| `users` | username, password_hash (Werkzeug scrypt), role ∈ {student, company, admin}, ref_id → students/companies |
| `students` | name, email, skills (CSV of canonical tags), interests (CSV of domains), cgpa, branch, backlogs, grad_year, resume_url |
| `companies` | name, role_title, domain, description, required, preferred, min_cgpa, branches, max_backlogs, desks, participating |
| `bookings` | student_id, company_id, slot, desk, score, source (manual/auto), status ∈ {booked, cancelled, attended, no_show} |
| `student_feedback` | relevance, usefulness, convenience (1–5), wait_minutes, comments; unique per (student, company) |
| `company_feedback` | candidate_quality, skill_alignment, shortlist_accuracy (1–5), to_interview, comments; one per company |
| `outcomes` | (student, company) → stage ∈ {interview, offer} |
| `settings` | fair configuration, matching weights, τ, k, last ML report (JSON) |
| `ai_cache` | cached AI responses keyed by a hash of the prompt inputs |

**Integrity guarantees** (partial unique indexes over non-cancelled bookings): one student per desk-slot, one booking per
student-slot, and one booking per student-company pair. Booking writes run inside `BEGIN IMMEDIATE` transactions, so two
students can't take the same desk at the same time.

## 4. Matching engine (`matching.py`)

1. **Hard eligibility filter (Eq. 1):** `E = [CGPA ≥ min] · [branch ∈ allowed] · [backlogs ≤ max]`. Pairs with E = 0 are
   never scored or shown. Failed rules are returned as readable reasons.
2. **Skill fit (Eq. 2):** `F = 0.8·|R∩K|/|R| + 0.2·|P∩K|/|P|` (R = required, P = preferred, K = student skills).
3. **Score (Eq. 3):** `M = E · (w_s·F + w_i·I + w_a·A)` where I = 1 if the role domain is among the student's interests, and
   A = min(1, (CGPA − min)/3). Default weights are 0.60/0.25/0.15. The admin can change them or replace them with learned ones.
4. **Outputs:** top-k (default 5) companies with M ≥ τ (default 0.35) per student; a ranked shortlist per company; and an
   explanation per pair (matched/missing required skills, matched preferred skills, interest match, CGPA margin).

## 5. Scheduling (`scheduling.py`)

A booking is valid when (a) the company has a free desk at the slot, (b) the student has no other booking at that time,
(c) the pair is an eligible match above τ, (d) the student is under the booking limit (default 4), and the student has no
existing booking with that company.

- **Manual:** students see only slots that pass (a) and (b) and pick one. Validation is repeated inside the transaction.
- **Auto:** all (student, top-match) pairs are processed in descending score order, and each gets a random valid free slot.
  Best-fit pairs get priority when capacity is short, and random slot choice spreads load across the day.
- Cancelling returns the slot to the pool.

## 6. AI components

### 6.1 Resume → profile (`resume.py`)
Text is extracted from PDF (pypdf), DOCX (read straight from the document XML) or TXT. Rule-based NLP then finds:
- skills: word-boundary matching against the 40-skill vocabulary and its aliases (ambiguous short aliases like "pm" are ignored)
- interests: the skill clusters with the most detected skills
- CGPA (10-point, or a 4-point GPA converted ×2.5), branch, graduation year, backlogs, email and name

The parsed values fill in the profile form, and nothing is saved until the student reviews it.

### 6.2 AI Career Coach and recruiter brief (`ai.py`)
- **Providers.** The admin chooses one on *AI & ML*:
  - **Google Gemini**: free key from Google AI Studio. REST `generateContent`, with the key sent in the `x-goog-api-key` header.
  - **Groq**: free key. OpenAI-compatible `chat/completions`.
  - **Anthropic Claude**: paid. Official `anthropic` SDK.
  - **Offline**: no key needed.
  "Auto" uses the first provider that has a key. Keys can be pasted in the UI (stored in the local database, shown masked)
  or set as environment variables.
- **Model auto-detection.** Gemini starts with the `gemini-flash-latest` alias. If that returns 404, the app lists the
  models available to the key and picks the newest non-lite Flash model. For Groq, the app lists the available models and
  picks one from a preference list (GPT-OSS 120B, Llama 3.3 70B, …), or the first chat model. The chosen model is saved,
  and the admin can override it.
- **Prompting.** The prompt contains only the structured profile (skills, interests, CGPA, branch, backlogs), the company's
  requirements and the match explanation. It never includes the student's name, email or resume text. The recruiter-brief
  prompt tells the model to judge only on skills, academics and interests.
- **Offline fallback.** With no key, or if a call fails (network, invalid key, free quota reached), a rule-based generator
  builds the same sections from the match explanation: strengths, gaps with a concrete learning task for each of the 40
  skills, a booth pitch, and interview topics by domain. The page shows why it fell back.
- **Caching.** Responses are stored in `ai_cache`, keyed by a hash of the inputs, so each student-company pair uses at most
  one API call, which helps stay within free-tier limits. Once an AI provider is configured, cached offline answers are
  replaced with AI ones.

### 6.3 Learned match weights (`learning.py`)
Logistic regression (gradient descent, L2 = 0.001) on attended interactions, with features [F, I, A] and label =
interview/offer. 70/30 train/test split. Positive coefficients get a small floor (5%) and are normalised to sum to 1, which
gives the suggested weights. Hold-out AUC is reported for the current and the learned weights, and the admin chooses whether
to apply them.

## 7. Analytics (`analytics.py`)
- **Engagement:** profile completion, share of students with ≥ 1 booking, bookings per student, attendance vs no-show.
- **Match quality:** mean score of booked pairs, share of bookings from eligible matches, mean student relevance,
  usefulness, convenience and reported wait, and company-rated candidate quality, alignment and shortlist accuracy.
- **Load:** desk utilisation by company and by hour.
- **Outcomes:** interviews and offers by company and by branch.
- **Skill gaps:** most common missing required skills among unmatched or low-scoring students, within their interest domains.

Filters: branch, domain, company. CSV exports: bookings, matches, feedback.

## 8. Security and privacy
- Passwords are hashed with Werkzeug (scrypt). Sessions are signed with `SECRET_KEY`; set your own outside local demos.
- Every route checks the role. Companies can open a candidate's profile or resume only if that student matched or booked them.
  Students can open only their own resume.
- Resume uploads are limited to PDF/DOCX/TXT, 5 MB, and stored as `<student_id>.<ext>`, never under the uploaded filename.
- The AI prompts carry no name, email or resume text. Only skills, academics and interests are sent.
- API keys pasted in the UI are stored in the local SQLite database and never shown again in full (masked to the last 4 characters).

## 9. Configuration

| Setting | Where | Default |
|---|---|---|
| Fair name/date/start time, slot length, slots per desk, max bookings, top-k, weights, τ | Admin → Fair setup | see `db.DEFAULT_SETTINGS` |
| `SECRET_KEY` | environment variable | `dev-change-me` |
| AI provider + API keys | Admin → AI settings (or env `GEMINI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`) | Auto; offline when no key |
| `CAREERMATCH_AI=off` | environment variable | forces offline AI even when a key is set |
| `PORT` | environment variable | 5000 |

## 10. Running, testing, resetting

```bash
pip install -r requirements.txt
python run.py                         # http://127.0.0.1:5000
python -m pytest                      # 26 tests: engine, scheduling, resume, AI, ML, end-to-end flows
python -m careermatch.simulate        # evaluation tables
```
Delete the `instance/` folder to reset the database, demo data and uploaded resumes.

## 11. Demonstration script (representative fair scenario)

The demo database contains 150 synthetic students and 12 fictional companies in all 7 domains.

0. (Optional) **admin** → **AI settings** → paste a free Gemini or Groq key → **Save & test connection**.
1. **admin / admin123** → *Fair setup*: review the configuration → **Run auto-scheduler**.
2. **AI settings** → **Simulate fair day** (attendance, outcomes and feedback for every booking) → **Train model**, and
   compare AUCs → **Apply learned weights**.
3. **Analytics**: engagement, match quality, utilisation by company and hour, outcomes, skill gaps. Try the filters, then
   export CSVs.
4. **demo / student123**: matches with explanations → open a company → **Show preparation guide** → book a slot → try a clashing
   slot (rejected).
5. **Student sign-up** (new account) → Profile → **Upload & auto-fill** a resume → review → Save → see matches.
6. **nimbussoft / company123**: ranked shortlist → open a candidate → **Generate summary** → schedule (attendance and
   outcomes) → feedback.
7. Offline evaluation: `python -m careermatch.simulate` (see `docs/EVALUATION_REPORT.md`).
