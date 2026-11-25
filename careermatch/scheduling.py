"""Constraint-aware slot booking (paper Sec. V).

A booking (student s, company c, slot t) is valid when
  (a) company c has a free desk at slot t,
  (b) s has no other booking at slot t,
  (c) (s, c) is an eligible match,
  (d) s is under the booking limit.
We additionally forbid booking the same company twice.
"""
import random
from collections import defaultdict


class ScheduleState:
    def __init__(self, desks_by_company: dict, num_slots: int, max_bookings: int = 4):
        self.desks = dict(desks_by_company)
        self.num_slots = num_slots
        self.max_bookings = max_bookings
        self.desk_used = defaultdict(set)       # (company, slot) -> {desk}
        self.student_slots = defaultdict(set)   # student -> {slot}
        self.student_companies = defaultdict(set)
        self.bookings = []                      # (student, company, slot, desk)

    @classmethod
    def from_bookings(cls, desks_by_company, num_slots, max_bookings, bookings):
        st = cls(desks_by_company, num_slots, max_bookings)
        for s, c, t, d in bookings:
            st._record(s, c, t, d)
        return st

    def _record(self, s, c, t, d):
        self.desk_used[(c, t)].add(d)
        self.student_slots[s].add(t)
        self.student_companies[s].add(c)
        self.bookings.append((s, c, t, d))

    def free_desk(self, c, t):
        used = self.desk_used[(c, t)]
        for d in range(1, self.desks.get(c, 0) + 1):
            if d not in used:
                return d
        return None

    def validate(self, s, c, t, is_eligible: bool):
        """Return (ok, reason)."""
        if not is_eligible:
            return False, "Not an eligible match for this company."
        if not (0 <= t < self.num_slots):
            return False, "Invalid slot."
        if len(self.student_companies[s]) >= self.max_bookings:
            return False, f"Booking limit of {self.max_bookings} reached."
        if c in self.student_companies[s]:
            return False, "You already have a slot with this company."
        if t in self.student_slots[s]:
            return False, "You already have another booking at this time."
        if self.free_desk(c, t) is None:
            return False, "All desks are taken for this slot."
        return True, ""

    def book(self, s, c, t, is_eligible=True):
        ok, reason = self.validate(s, c, t, is_eligible)
        if not ok:
            raise ValueError(reason)
        d = self.free_desk(c, t)
        self._record(s, c, t, d)
        return d

    def free_slots(self, s, c):
        """Slots where student s could book company c right now."""
        return [t for t in range(self.num_slots)
                if t not in self.student_slots[s] and self.free_desk(c, t) is not None]


def auto_schedule(pairs, state: ScheduleState, rng=None):
    """Process (student, company, score) pairs by descending score; assign each a
    random valid free slot. Returns (placed, unplaced) lists."""
    rng = rng or random.Random()
    placed, unplaced = [], []
    for s, c, sc in sorted(pairs, key=lambda x: -x[2]):
        if c in state.student_companies[s] or len(state.student_companies[s]) >= state.max_bookings:
            continue  # already booked / at limit: not a request we can serve
        options = state.free_slots(s, c)
        if not options:
            unplaced.append((s, c))
            continue
        t = rng.choice(options)
        d = state.book(s, c, t)
        placed.append((s, c, t, d))
    return placed, unplaced


def slot_label(slot: int, start="09:00", slot_len=10) -> str:
    h, m = map(int, start.split(":"))
    mins = h * 60 + m + slot * slot_len
    end = mins + slot_len
    return f"{mins // 60:02d}:{mins % 60:02d}–{end // 60:02d}:{end % 60:02d}"
