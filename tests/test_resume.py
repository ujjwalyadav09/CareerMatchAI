import io
import zipfile

import pytest

from careermatch.app import create_app
from careermatch.resume import extract_text, parse_resume

RESUME = """PRIYA SHARMA
priya.sharma@example.edu | +91 98765 43210

EDUCATION
B.Tech in Computer Science and Engineering, Lovely Professional University   2022 - 2026
CGPA: 8.42 / 10      No active backlogs

SKILLS
Python, Java, SQL, Git, React.js, JS, ML, Pandas, Docker, Excel

PROJECTS
Built a placement portal using Flask at 5 pm deadlines; used JavaScript and Machine Learning.
"""


def make_docx(text):
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.splitlines())
    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_parse_resume_fields():
    p = parse_resume(RESUME)
    assert p["name"] == "Priya Sharma"
    assert p["email"] == "priya.sharma@example.edu"
    assert p["cgpa"] == 8.42
    assert p["branch"] == "CSE"
    assert p["grad_year"] == 2026
    assert p["backlogs"] == 0
    for s in ["Python", "Java", "SQL", "Git", "React", "JavaScript", "Machine Learning", "Pandas", "Docker", "Excel"]:
        assert s in p["skills"], s
    assert "Project Management" not in p["skills"]   # "pm" must not be read as a skill
    assert p["interests"][0] == "software"


def test_java_not_confused_with_javascript():
    assert parse_resume("Skills: JavaScript, React")["skills"] == ["JavaScript", "React"]


def test_gpa_on_4_scale_and_backlogs():
    p = parse_resume("GPA 3.6/4.0, Mechanical Engineering, 2 backlogs, batch of 2027")
    assert p["cgpa"] == 9.0 and p["branch"] == "ME" and p["backlogs"] == 2 and p["grad_year"] == 2027


def test_docx_extraction():
    assert "CGPA: 8.42" in extract_text("cv.docx", make_docx(RESUME))


@pytest.fixture
def client(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "t.db"), "SECRET_KEY": "t"})
    c = app.test_client()
    c.post("/register", data={"name": "New Student", "username": "newbie", "password": "secret1"})
    c.post("/login", data={"username": "newbie", "password": "secret1"})
    return c


def test_upload_prefills_profile_and_serves_file(client):
    r = client.post("/student/resume", data={"resume": (io.BytesIO(make_docx(RESUME)), "cv.docx")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert b"Resume read" in r.data
    assert b'value="Priya Sharma"' in r.data
    assert b'value="8.42"' in r.data
    assert b"Machine Learning" in r.data
    # file is stored and visible to its owner
    r = client.get("/student/profile")
    assert b"/resume/" in r.data
    sid = r.data.split(b"/resume/")[1].split(b'"')[0].decode()
    assert client.get(f"/resume/{sid}").status_code == 200
    assert client.get(f"/resume/{int(sid) - 1}").status_code == 403   # other students' resumes are private


def test_upload_rejects_bad_type(client):
    r = client.post("/student/resume", data={"resume": (io.BytesIO(b"x"), "cv.exe")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"must be a PDF, DOCX or TXT" in r.data
