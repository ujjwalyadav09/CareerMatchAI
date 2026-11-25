import random

import pytest

from careermatch import matching as M
from careermatch.scheduling import ScheduleState, auto_schedule, slot_label
from careermatch.skills import normalize_skills, unknown_skills

STUDENT = {"skills": ["Python", "SQL", "Git"], "interests": ["software"], "cgpa": 8.0,
           "branch": "CSE", "backlogs": 0}
COMPANY = {"required": ["Python", "Java", "SQL", "Git"], "preferred": ["React", "Docker"],
           "domain": "software", "min_cgpa": 7.0, "branches": ["CSE", "IT"], "max_backlogs": 0}


# ---------------------------------------------------------------- skills
def test_alias_normalization():
    assert normalize_skills("JS, js , ML, python3, k8s, Unknown") == ["JavaScript", "Machine Learning", "Python", "Kubernetes"]
    assert unknown_skills("JS, Cobolx") == ["Cobolx"]


# ---------------------------------------------------------------- matching
def test_eligibility_rules():
    assert M.eligible(STUDENT, COMPANY)
    assert not M.eligible({**STUDENT, "cgpa": 6.9}, COMPANY)
    assert not M.eligible({**STUDENT, "branch": "ME"}, COMPANY)
    assert not M.eligible({**STUDENT, "backlogs": 1}, COMPANY)
    assert len(M.eligibility_reasons({**STUDENT, "cgpa": 5, "branch": "ME", "backlogs": 3}, COMPANY)) == 3


def test_score_formula():
    # F = 0.8*3/4 + 0.2*0/2 = 0.6 ; I = 1 ; A = min(1, 1/3)
    expected = 0.60 * 0.6 + 0.25 * 1 + 0.15 * (1 / 3)
    assert M.score(STUDENT, COMPANY) == pytest.approx(expected)
    assert M.score({**STUDENT, "cgpa": 6.0}, COMPANY) == 0.0  # E = 0


def test_explanation():
    ex = M.explain(STUDENT, COMPANY)
    assert ex["missing_required"] == ["Java"]
    assert ex["matched_required"] == ["Git", "Python", "SQL"]
    assert ex["interest_match"] and ex["cgpa_margin"] == 1.0


def test_recommend_never_returns_ineligible():
    rng = random.Random(1)
    from careermatch.simulate import gen_company, gen_student
    comps = [gen_company(j, rng) for j in range(20)]
    for i in range(200):
        s = gen_student(i, rng)
        recs = M.recommend_for_student(s, comps)
        assert len(recs) <= 5
        assert all(M.eligible(s, c) and sc >= 0.35 for c, sc in recs)
        assert [sc for _, sc in recs] == sorted((sc for _, sc in recs), reverse=True)


# ---------------------------------------------------------------- scheduling
def test_booking_constraints():
    st = ScheduleState({"A": 1, "B": 2}, num_slots=4, max_bookings=2)
    assert st.book("s1", "A", 0) == 1
    with pytest.raises(ValueError, match="desks"):
        st.book("s2", "A", 0)                      # (a) desk full
    with pytest.raises(ValueError, match="another booking"):
        st.book("s1", "B", 0)                      # (b) student clash
    with pytest.raises(ValueError, match="eligible"):
        st.book("s3", "B", 1, is_eligible=False)   # (c) not eligible
    with pytest.raises(ValueError, match="already"):
        st.book("s1", "A", 2)                      # same company twice
    st.book("s1", "B", 1)
    with pytest.raises(ValueError, match="limit"):
        st.book("s1", "C", 3)                      # (d) booking limit


def test_auto_schedule_no_clashes_and_priority():
    st = ScheduleState({"A": 1}, num_slots=2, max_bookings=4)
    pairs = [("low", "A", 0.4), ("high", "A", 0.9), ("mid", "A", 0.6)]
    placed, unplaced = auto_schedule(pairs, st, random.Random(0))
    assert {p[0] for p in placed} == {"high", "mid"}       # best-fit first
    assert unplaced == [("low", "A")]
    slots = [(c, t, d) for _, c, t, d in placed]
    assert len(slots) == len(set(slots))


def test_slot_label():
    assert slot_label(0) == "09:00–09:10"
    assert slot_label(47) == "16:50–17:00"
