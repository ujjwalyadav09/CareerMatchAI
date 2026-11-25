import pytest

from careermatch.app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True, "SECRET_KEY": "t"})
    return app.test_client()


def login(c, u, p):
    return c.post("/login", data={"username": u, "password": p}, follow_redirects=True)


def test_student_flow(client):
    r = login(client, "demo", "student123")
    assert b"Top matches for you" in r.data
    assert b"NimbusSoft" in r.data
    # find NimbusSoft id via company page links
    r = client.get("/student/company/1")
    assert r.status_code == 200 and b"Book an interaction slot" in r.data
    r = client.post("/student/book", data={"company_id": 1, "slot": 3}, follow_redirects=True)
    assert b"Booked NimbusSoft" in r.data
    # clash: same slot with another company
    r = client.post("/student/book", data={"company_id": 3, "slot": 3}, follow_redirects=True)
    assert b"Could not book" in r.data
    # feedback
    r = client.post("/student/feedback", data={"company_id": 1, "relevance": 5, "usefulness": 4,
                                               "convenience": 5, "wait_minutes": 0, "comments": "good"},
                    follow_redirects=True)
    assert b"Thanks for your feedback" in r.data


def test_role_protection(client):
    login(client, "demo", "student123")
    assert client.get("/admin").status_code == 403
    assert client.get("/company").status_code == 403


def test_company_and_admin_flow(client):
    login(client, "admin", "admin123")
    r = client.post("/admin/auto-schedule", follow_redirects=True)
    assert b"Auto-scheduler placed" in r.data
    r = client.get("/admin/analytics")
    assert r.status_code == 200 and b"Desk utilization by company" in r.data
    r = client.get("/admin/analytics?branch=CSE&domain=software")
    assert r.status_code == 200
    r = client.get("/admin/export/bookings.csv")
    assert r.status_code == 200 and r.data.startswith(b"booking_id")
    client.get("/logout")

    login(client, "nimbussoft", "company123")
    r = client.get("/company")
    assert b"Pre-fair ranked shortlist" in r.data
    r = client.post("/company/feedback", data={"candidate_quality": 4, "skill_alignment": 4,
                                               "shortlist_accuracy": 5, "to_interview": 3},
                    follow_redirects=True)
    assert b"Feedback saved" in r.data
