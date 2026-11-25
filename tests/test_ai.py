import random

import pytest

from careermatch import ai, learning
from careermatch import matching as M
from careermatch.app import create_app

S = {"id": 1, "skills": ["Python", "SQL", "Git"], "interests": ["software"], "cgpa": 8.0,
     "branch": "CSE", "backlogs": 0, "grad_year": 2026}
C = {"id": 1, "name": "NimbusSoft", "role_title": "SWE", "required": ["Python", "Java", "SQL", "Git"],
     "preferred": ["React"], "domain": "software", "min_cgpa": 7.0, "branches": ["CSE"], "max_backlogs": 0}


@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "a.db"), "SECRET_KEY": "t"})


def test_offline_coach_mentions_gaps_and_strengths(app, monkeypatch):
    monkeypatch.setattr(ai, "active_provider", lambda con: None)
    with app.app_context():
        from careermatch import db
        r = ai.career_coach(db.get_db(), S, C, M.explain(S, C))
    assert r["source"] == "offline"
    assert "Java" in r["text"] and "Gaps to close" in r["text"] and "Python" in r["text"]


def test_llm_used_when_enabled_and_cached(app, monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "active_provider", lambda con: "gemini")
    monkeypatch.setattr(ai, "_call", lambda con, p, system, text: calls.append(p) or "Why you match:\n- great")
    with app.app_context():
        from careermatch import db
        ex = M.explain(S, C)
        r1 = ai.candidate_summary(db.get_db(), S, C, ex)
        r2 = ai.candidate_summary(db.get_db(), S, C, ex)
    assert r1["source"] == r2["source"] == "gemini" and calls == ["gemini"]


def test_llm_failure_falls_back(app, monkeypatch):
    def boom(*_):
        raise RuntimeError("network down")
    monkeypatch.setattr(ai, "active_provider", lambda con: "groq")
    monkeypatch.setattr(ai, "_call", boom)
    with app.app_context():
        from careermatch import db
        r = ai.career_coach(db.get_db(), S, C, M.explain(S, C))
    assert r["source"] == "offline" and "network down" in r["error"]


def test_learning_recovers_skill_dominance():
    rng = random.Random(3)
    X, y = [], []
    for _ in range(400):
        x = [rng.random(), float(rng.random() < 0.5), rng.random()]
        p = 1 / (1 + pow(2.718, -(-3 + 6 * x[0] + 0.5 * x[1])))
        X.append(x); y.append(int(rng.random() < p))
    w, _ = learning.train_logreg(X, y)
    assert w[0] > w[1] > abs(w[2]) - 0.5      # skill >> interest, academic ~ 0
    assert learning.auc([x[0] for x in X], y) > 0.75


def test_admin_ai_flow(app):
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin123"})
    r = c.post("/admin/ai/train", follow_redirects=True)
    assert b"Need at least 20" in r.data                      # no data yet
    c.post("/admin/auto-schedule")
    r = c.post("/admin/ai/simulate", follow_redirects=True)
    assert b"Simulated fair day" in r.data
    r = c.post("/admin/ai/train", follow_redirects=True)
    assert b"hold-out AUC" in r.data
    r = c.post("/admin/ai/apply", follow_redirects=True)
    assert b"Applied learned weights" in r.data
    assert c.get("/admin/analytics").status_code == 200


def test_coach_and_brief_pages(app):
    c = app.test_client()
    c.post("/login", data={"username": "demo", "password": "student123"})
    r = c.get("/student/company/1?coach=1")
    assert r.status_code == 200 and b"Why you match" in r.data
    c.get("/logout")
    c.post("/login", data={"username": "nimbussoft", "password": "company123"})
    r = c.get("/company")
    sid = r.data.split(b"/company/candidate/")[1].split(b'"')[0].decode()
    r = c.get(f"/company/candidate/{sid}?brief=1")
    assert r.status_code == 200 and b"Probe in interview" in r.data


def _with_key(app, provider, key="test-key-1234"):
    from careermatch import db
    db.get_db().execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (f"{provider}_api_key", key))


def test_gemini_request_and_404_model_discovery(app, monkeypatch):
    sent = []

    def fake_http(url, body=None, headers=None):
        sent.append((url, body, headers))
        if url.endswith(":generateContent") and "gemini-flash-latest" in url:
            raise ai.ApiError(404, "model not found")
        if "/models?" in url:
            return {"models": [
                {"name": "models/gemini-9-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-9-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-9", "supportedGenerationMethods": ["embedContent"]}]}
        return {"candidates": [{"content": {"parts": [{"text": "Why you match:\n- strong Python"}]}}]}

    monkeypatch.setattr(ai, "_http_json", fake_http)
    with app.app_context():
        from careermatch import db
        _with_key(app, "gemini")
        assert ai.active_provider(db.get_db()) == "gemini"
        r = ai.career_coach(db.get_db(), S, C, M.explain(S, C))
        assert r["source"] == "gemini" and "strong Python" in r["text"]
        assert ai.model_for(db.get_db(), "gemini") == "gemini-9-flash"      # discovered + saved
    final_url, body, headers = sent[-1]
    assert final_url.endswith("/models/gemini-9-flash:generateContent")
    assert headers["x-goog-api-key"] == "test-key-1234" and "test-key" not in final_url
    assert "system_instruction" in body and "Python" in body["contents"][0]["parts"][0]["text"]


def test_groq_auto_model_and_parsing(app, monkeypatch):
    def fake_http(url, body=None, headers=None):
        assert headers["Authorization"] == "Bearer gsk-abc"
        if url.endswith("/models"):
            return {"data": [{"id": "whisper-large-v3"}, {"id": "llama-3.3-70b-versatile"}, {"id": "some-model"}]}
        assert body["model"] == "llama-3.3-70b-versatile" and body["messages"][0]["role"] == "system"
        return {"choices": [{"message": {"content": "Strengths:\n- SQL"}}]}

    monkeypatch.setattr(ai, "_http_json", fake_http)
    with app.app_context():
        from careermatch import db
        _with_key(app, "groq", "gsk-abc")
        r = ai.candidate_summary(db.get_db(), S, C, M.explain(S, C))
    assert r["source"] == "groq" and "SQL" in r["text"]


def test_admin_can_save_provider_key(app, monkeypatch):
    monkeypatch.setattr(ai, "_http_json", lambda url, body=None, headers=None:
                        {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin123"})
    r = c.post("/admin/ai/provider", data={"ai_provider": "gemini", "gemini_api_key": "AIzaTESTKEY9876",
                                           "test": "1"}, follow_redirects=True)
    assert b"Connected" in r.data
    assert b"AIzaTESTKEY9876" not in r.data and "…9876".encode() in r.data   # key is masked in the UI
