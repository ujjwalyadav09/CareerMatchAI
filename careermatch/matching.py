"""Two-stage skill-and-eligibility matching engine (paper Sec. IV).

All functions are pure: they operate on plain dicts so they can be used by
the web app and by the offline simulator alike.

Student dict keys:  skills (set/list), interests (list), cgpa, branch, backlogs
Company dict keys:  required (list), preferred (list), domain, min_cgpa,
                    branches (list), max_backlogs
"""

DEFAULT_WEIGHTS = {"skill": 0.60, "interest": 0.25, "academic": 0.15}
REQUIRED_SHARE = 0.8          # split inside F(s,c), Eq. (2)
DEFAULT_K = 5
DEFAULT_TAU = 0.35


def eligible(s, c) -> bool:
    """Eq. (1): E(s,c) = [Gs >= Gc] * [br_s in Bc] * [b_s <= b_c]."""
    return (
        float(s["cgpa"]) >= float(c["min_cgpa"])
        and s["branch"] in c["branches"]
        and int(s["backlogs"]) <= int(c["max_backlogs"])
    )


def eligibility_reasons(s, c) -> list:
    """Human-readable list of failed eligibility rules (empty when eligible)."""
    out = []
    if float(s["cgpa"]) < float(c["min_cgpa"]):
        out.append(f"CGPA {s['cgpa']} below minimum {c['min_cgpa']}")
    if s["branch"] not in c["branches"]:
        out.append(f"Branch {s['branch']} not permitted")
    if int(s["backlogs"]) > int(c["max_backlogs"]):
        out.append(f"{s['backlogs']} active backlogs exceeds limit {c['max_backlogs']}")
    return out


def skill_fit(s, c) -> float:
    """Eq. (2): F = 0.8*|Rc∩Ks|/|Rc| + 0.2*|Pc∩Ks|/|Pc|."""
    ks = set(s["skills"])
    req, pref = set(c["required"]), set(c["preferred"])
    r = len(req & ks) / len(req) if req else 1.0
    p = len(pref & ks) / len(pref) if pref else 0.0
    if not pref:  # no preferred skills: required coverage carries the full weight
        return r
    return REQUIRED_SHARE * r + (1 - REQUIRED_SHARE) * p


def interest(s, c) -> float:
    return 1.0 if c["domain"] in s["interests"] else 0.0


def academic_margin(s, c) -> float:
    return max(0.0, min(1.0, (float(s["cgpa"]) - float(c["min_cgpa"])) / 3.0))


def score(s, c, weights=None) -> float:
    """Eq. (3): M = E * [w_skill*F + w_interest*I + w_academic*A]."""
    if not eligible(s, c):
        return 0.0
    w = weights or DEFAULT_WEIGHTS
    return (
        w["skill"] * skill_fit(s, c)
        + w["interest"] * interest(s, c)
        + w["academic"] * academic_margin(s, c)
    )


def explain(s, c, weights=None) -> dict:
    """Per-match explanation (Sec. IV-C)."""
    ks = set(s["skills"])
    return {
        "eligible": eligible(s, c),
        "ineligible_reasons": eligibility_reasons(s, c),
        "score": round(score(s, c, weights), 3),
        "skill_fit": round(skill_fit(s, c), 3),
        "matched_required": sorted(set(c["required"]) & ks),
        "missing_required": sorted(set(c["required"]) - ks),
        "matched_preferred": sorted(set(c["preferred"]) & ks),
        "interest_match": bool(interest(s, c)),
        "cgpa_margin": round(float(s["cgpa"]) - float(c["min_cgpa"]), 2),
    }


def recommend_for_student(s, companies, k=DEFAULT_K, tau=DEFAULT_TAU, weights=None):
    """Top-k eligible companies with M >= tau, best first. Returns [(company, score)]."""
    scored = [(c, score(s, c, weights)) for c in companies if eligible(s, c)]
    scored = [x for x in scored if x[1] >= tau]
    scored.sort(key=lambda x: -x[1])
    return scored[:k]


def shortlist_for_company(c, students, tau=DEFAULT_TAU, weights=None, limit=None):
    """Pre-fair ranked shortlist of eligible candidates for a company."""
    scored = [(s, score(s, c, weights)) for s in students if eligible(s, c)]
    scored = [x for x in scored if x[1] >= tau]
    scored.sort(key=lambda x: -x[1])
    return scored[:limit] if limit else scored


# ---------------------------------------------------------------- baseline
def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a or b) else 0.0


def baseline_recommend(s, companies, k=DEFAULT_K, min_overlap=0.15):
    """Keyword-overlap baseline: Jaccard on skills, no eligibility filter."""
    scored = [(c, jaccard(s["skills"], set(c["required"]) | set(c["preferred"]))) for c in companies]
    scored = [x for x in scored if x[1] >= min_overlap]
    scored.sort(key=lambda x: -x[1])
    return scored[:k]
