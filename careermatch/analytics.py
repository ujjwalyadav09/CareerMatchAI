"""Placement-office analytics (paper Sec. VI-B). Pure functions over plain records."""
from collections import Counter, defaultdict

from . import matching as M

PROFILE_FIELDS = ("email", "skills", "interests", "cgpa", "branch", "grad_year", "resume_url")


def profile_completion(s) -> float:
    filled = sum(1 for f in PROFILE_FIELDS if s.get(f))
    return filled / len(PROFILE_FIELDS)


def compute(students, companies, bookings, s_feedback, c_feedback, outcomes, cfg,
            branch=None, company_id=None, domain=None):
    """Return the dashboard metrics dict. `bookings` are non-cancelled booking dicts."""
    w = {"skill": float(cfg["w_skill"]), "interest": float(cfg["w_interest"]),
         "academic": float(cfg["w_academic"])}
    tau, num_slots = float(cfg["tau"]), int(cfg["num_slots"])
    slot_len, start = int(cfg["slot_len"]), cfg["start_time"]

    st_by_id = {s["id"]: s for s in students}
    co_by_id = {c["id"]: c for c in companies}

    # ---- filters
    if branch:
        students = [s for s in students if s["branch"] == branch]
    if domain:
        companies = [c for c in companies if c["domain"] == domain]
    if company_id:
        companies = [c for c in companies if c["id"] == company_id]
    sids, cids = {s["id"] for s in students}, {c["id"] for c in companies}
    bookings = [b for b in bookings if b["student_id"] in sids and b["company_id"] in cids]
    s_feedback = [f for f in s_feedback if f["student_id"] in sids and f["company_id"] in cids]
    c_feedback = [f for f in c_feedback if f["company_id"] in cids]
    outcomes = [o for o in outcomes if o["student_id"] in sids and o["company_id"] in cids]

    n_students = len(students) or 1
    # ---- engagement
    booked_students = {b["student_id"] for b in bookings}
    attended = sum(1 for b in bookings if b["status"] == "attended")
    no_show = sum(1 for b in bookings if b["status"] == "no_show")
    engagement = {
        "students": len(students),
        "companies": len(companies),
        "profile_completion": sum(profile_completion(s) for s in students) / n_students,
        "students_with_booking": len(booked_students) / n_students,
        "bookings": len(bookings),
        "bookings_per_student": len(bookings) / n_students,
        "attended": attended,
        "no_show": no_show,
        "attendance_rate": attended / (attended + no_show) if attended + no_show else None,
    }

    # ---- match quality
    scores, eligible_count = [], 0
    for b in bookings:
        s, c = st_by_id.get(b["student_id"]), co_by_id.get(b["company_id"])
        if s and c:
            scores.append(M.score(s, c, w))
            eligible_count += M.eligible(s, c)
    rel = [f["relevance"] for f in s_feedback if f["relevance"]]
    quality = {
        "mean_score": sum(scores) / len(scores) if scores else None,
        "eligible_share": eligible_count / len(bookings) if bookings else None,
        "mean_relevance": sum(rel) / len(rel) if rel else None,
        "mean_usefulness": _mean(f["usefulness"] for f in s_feedback),
        "mean_convenience": _mean(f["convenience"] for f in s_feedback),
        "mean_wait": _mean(f["wait_minutes"] for f in s_feedback),
        "mean_candidate_quality": _mean(f["candidate_quality"] for f in c_feedback),
        "mean_skill_alignment": _mean(f["skill_alignment"] for f in c_feedback),
        "mean_shortlist_accuracy": _mean(f["shortlist_accuracy"] for f in c_feedback),
        "student_responses": len(s_feedback),
        "company_responses": len(c_feedback),
    }

    # ---- load: utilization by company and by hour band
    per_company = Counter(b["company_id"] for b in bookings)
    load_company = sorted(
        ({"name": c["name"], "bookings": per_company[c["id"]],
          "capacity": c["desks"] * num_slots,
          "util": per_company[c["id"]] / (c["desks"] * num_slots) if c["desks"] else 0}
         for c in companies), key=lambda x: -x["util"])
    slots_per_band = max(1, 60 // slot_len)
    total_desks = sum(c["desks"] for c in companies) or 1
    band_counts = Counter(b["slot"] // slots_per_band for b in bookings)
    h0, m0 = map(int, start.split(":"))
    load_time = []
    for band in range((num_slots + slots_per_band - 1) // slots_per_band):
        mins = h0 * 60 + m0 + band * 60
        load_time.append({"label": f"{mins // 60:02d}:{mins % 60:02d}",
                          "bookings": band_counts[band],
                          "util": band_counts[band] / (total_desks * slots_per_band)})

    # ---- outcomes by company and branch
    oc = defaultdict(lambda: {"interview": 0, "offer": 0})
    ob = defaultdict(lambda: {"interview": 0, "offer": 0})
    for o in outcomes:
        c, s = co_by_id.get(o["company_id"]), st_by_id.get(o["student_id"])
        if c:
            oc[c["name"]][o["stage"]] += 1
        if s:
            ob[s["branch"]][o["stage"]] += 1

    # ---- skill gaps among unmatched / low-scoring students
    gaps = Counter()
    low = 0
    for s in students:
        best = max((M.score(s, c, w) for c in companies), default=0)
        if best < max(tau, 0.5):
            low += 1
            for c in companies:
                if c["domain"] in s["interests"]:
                    gaps.update(set(c["required"]) - set(s["skills"]))

    return {
        "engagement": engagement, "quality": quality,
        "load_company": load_company, "load_time": load_time,
        "outcomes_company": dict(oc), "outcomes_branch": dict(ob),
        "skill_gaps": gaps.most_common(10), "low_match_students": low,
    }


def _mean(values):
    vals = [v for v in values if v is not None and v != ""]
    return sum(vals) / len(vals) if vals else None
