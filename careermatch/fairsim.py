"""'Simulate fair day': fills a representative post-fair state for demonstrations.

For every active booking it records attendance (~88% attend), interview/offer outcomes
(whose probability rises with true fit), and student + company feedback. This lets the
analytics dashboard and the weight-learning model be demonstrated before a real fair.
"""
import math
import random

from . import matching as M


def _sig(z):
    return 1 / (1 + math.exp(-z))


def simulate_fair_day(con, students, companies, rng=None):
    rng = rng or random.Random()
    st = {s["id"]: s for s in students}
    co = {c["id"]: c for c in companies}
    rows = con.execute("SELECT * FROM bookings WHERE status != 'cancelled'").fetchall()
    stats = {"attended": 0, "no_show": 0, "interview": 0, "offer": 0, "s_feedback": 0, "c_feedback": 0}
    per_company = {}
    con.execute("BEGIN")
    for b in rows:
        s, c = st.get(b["student_id"]), co.get(b["company_id"])
        if not s or not c:
            continue
        F, I, A = M.skill_fit(s, c), M.interest(s, c), M.academic_margin(s, c)
        if rng.random() < 0.12:
            con.execute("UPDATE bookings SET status='no_show' WHERE id=?", (b["id"],))
            stats["no_show"] += 1
            continue
        con.execute("UPDATE bookings SET status='attended' WHERE id=?", (b["id"],))
        stats["attended"] += 1
        # recruiters mostly care about skills; interest helps a bit, academics a little
        p_interview = _sig(-5.0 + 6.0 * F + 0.8 * I + 0.5 * A + rng.gauss(0, 0.3))
        stage = None
        if rng.random() < p_interview:
            stage = "offer" if rng.random() < _sig(-2.5 + 3.0 * F) else "interview"
            con.execute("INSERT INTO outcomes(student_id, company_id, stage) VALUES (?,?,?) "
                        "ON CONFLICT(student_id, company_id) DO UPDATE SET stage=excluded.stage",
                        (s["id"], c["id"], stage))
            stats[stage] += 1
        else:
            con.execute("DELETE FROM outcomes WHERE student_id=? AND company_id=?", (s["id"], c["id"]))
        clamp = lambda v: max(1, min(5, round(v)))
        relevance = clamp(1.5 + 3.0 * F + 0.6 * I + rng.gauss(0, 0.6))
        con.execute(
            "INSERT INTO student_feedback(student_id, company_id, relevance, usefulness, convenience, wait_minutes,"
            " comments) VALUES (?,?,?,?,?,?, '') ON CONFLICT(student_id, company_id) DO UPDATE SET"
            " relevance=excluded.relevance, usefulness=excluded.usefulness, convenience=excluded.convenience,"
            " wait_minutes=excluded.wait_minutes",
            (s["id"], c["id"], relevance, clamp(relevance + rng.gauss(0, 0.7)), clamp(rng.gauss(4.3, 0.6)),
             max(0, round(rng.expovariate(1 / 2.0)))))
        stats["s_feedback"] += 1
        pc = per_company.setdefault(c["id"], {"F": [], "interviews": 0})
        pc["F"].append(F)
        pc["interviews"] += stage is not None
    for cid, pc in per_company.items():
        q = sum(pc["F"]) / len(pc["F"])
        clamp = lambda v: max(1, min(5, round(v)))
        con.execute(
            "INSERT INTO company_feedback(company_id, candidate_quality, skill_alignment, to_interview,"
            " shortlist_accuracy, comments) VALUES (?,?,?,?,?, 'Simulated fair-day feedback')"
            " ON CONFLICT(company_id) DO UPDATE SET candidate_quality=excluded.candidate_quality,"
            " skill_alignment=excluded.skill_alignment, to_interview=excluded.to_interview,"
            " shortlist_accuracy=excluded.shortlist_accuracy, comments=excluded.comments",
            (cid, clamp(1.5 + 3.5 * q + rng.gauss(0, 0.3)), clamp(1.2 + 4 * q + rng.gauss(0, 0.3)),
             pc["interviews"], clamp(2 + 3 * q + rng.gauss(0, 0.3))))
        stats["c_feedback"] += 1
    con.execute("COMMIT")
    return stats
