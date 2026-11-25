"""CareerMatch AI web application (Flask)."""
import csv
import io
import os
import random
import sqlite3
from functools import wraps

from flask import (Flask, Response, abort, flash, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import json

from . import ai, analytics, db, fairsim, learning, resume
from . import matching as M
from .scheduling import ScheduleState, auto_schedule, slot_label
from .skills import BRANCHES, CLUSTERS, DOMAINS, VOCABULARY, normalize_skills, unknown_skills

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app(test_config=None):
    app = Flask(__name__, template_folder=os.path.join(ROOT, "templates"),
                static_folder=os.path.join(ROOT, "static"))
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        # Vercel's filesystem is read-only except /tmp, so keep the DB there when deployed.
        DATABASE=os.environ.get("DATABASE_PATH") or (
            "/tmp/careermatch/careermatch.db" if os.environ.get("VERCEL")
            else os.path.join(ROOT, "instance", "careermatch.db")),
        SEED=True,
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,  # 5 MB resume limit
    )
    if test_config:
        app.config.update(test_config)
    app.config.setdefault("UPLOAD_FOLDER", os.path.join(os.path.dirname(app.config["DATABASE"]), "uploads"))

    db.init_db(app.config["DATABASE"])
    if app.config["SEED"]:
        from .seed import seed
        seed(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)

    # ------------------------------------------------------------ helpers
    def cfg():
        return db.settings()

    def label(slot):
        c = cfg()
        return slot_label(slot, c["start_time"], int(c["slot_len"]))

    @app.context_processor
    def inject():
        return {"user": session.get("user"), "slot_label": label, "fair": cfg(),
                "pct": lambda v: "–" if v is None else f"{v * 100:.1f}%",
                "num": lambda v, d=2: "–" if v is None else f"{v:.{d}f}"}

    def login_required(role):
        def deco(fn):
            @wraps(fn)
            def wrapper(*a, **kw):
                u = session.get("user")
                if not u:
                    return redirect(url_for("login", next=request.path))
                if u["role"] != role:
                    abort(403)
                return fn(*a, **kw)
            return wrapper
        return deco

    def schedule_state():
        c = cfg()
        comps = db.all_companies(participating_only=False)
        rows = db.active_bookings()
        return ScheduleState.from_bookings(
            {x["id"]: x["desks"] for x in comps}, int(c["num_slots"]), int(c["max_bookings"]),
            [(r["student_id"], r["company_id"], r["slot"], r["desk"]) for r in rows])

    # ------------------------------------------------------------ auth
    @app.route("/")
    def index():
        u = session.get("user")
        if not u:
            return render_template("home.html")
        return redirect(url_for({"student": "student_home", "company": "company_home",
                                 "admin": "admin_home"}[u["role"]]))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            r = db.get_db().execute("SELECT * FROM users WHERE username = ?",
                                    (request.form.get("username", "").strip(),)).fetchone()
            if r and check_password_hash(r["password_hash"], request.form.get("password", "")):
                session.clear()
                session["user"] = {"id": r["id"], "username": r["username"], "role": r["role"],
                                   "ref_id": r["ref_id"]}
                nxt = request.args.get("next")
                return redirect(nxt if nxt and nxt.startswith("/") else url_for("index"))
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            f = request.form
            uname, name, pw = f.get("username", "").strip(), f.get("name", "").strip(), f.get("password", "")
            if not uname or not name or len(pw) < 6:
                flash("Name, username and a password of at least 6 characters are required.", "error")
                return render_template("register.html")
            con = db.get_db()
            if con.execute("SELECT 1 FROM users WHERE username = ?", (uname,)).fetchone():
                flash("That username is taken.", "error")
                return render_template("register.html")
            con.execute("BEGIN")
            cur = con.execute("INSERT INTO students(name, email) VALUES (?, ?)", (name, f.get("email", "")))
            con.execute("INSERT INTO users(username, password_hash, role, ref_id) VALUES (?,?, 'student', ?)",
                        (uname, generate_password_hash(pw), cur.lastrowid))
            con.execute("COMMIT")
            flash("Account created. Please log in and complete your profile.", "ok")
            return redirect(url_for("login"))
        return render_template("register.html")

    # ------------------------------------------------------------ student
    @app.route("/student")
    @login_required("student")
    def student_home():
        c = cfg()
        s = db.get_student(session["user"]["ref_id"])
        comps = db.all_companies()
        recs = M.recommend_for_student(s, comps, k=int(c["top_k"]), tau=float(c["tau"]), weights=db.weights(c))
        matches = [(co, M.explain(s, co, db.weights(c))) for co, _ in recs]
        bookings = db.active_bookings("AND b.student_id = ?", (s["id"],))
        booked_ids = {b["company_id"] for b in bookings}
        others = [(co, M.explain(s, co, db.weights(c))) for co in comps
                  if co["id"] not in {m[0]["id"] for m in matches}]
        others.sort(key=lambda x: -x[1]["score"])
        return render_template("student_home.html", s=s, matches=matches, others=others,
                               bookings=bookings, booked_ids=booked_ids,
                               completion=analytics.profile_completion(s))

    @app.route("/student/profile", methods=["GET", "POST"])
    @login_required("student")
    def student_profile():
        sid = session["user"]["ref_id"]
        if request.method == "POST":
            f = request.form
            raw_skills = f.get("skills", "")
            skills = normalize_skills(raw_skills)
            bad = unknown_skills(raw_skills)
            interests = [d for d in f.getlist("interests") if d in DOMAINS]
            try:
                cgpa = float(f.get("cgpa") or 0)
                backlogs = int(f.get("backlogs") or 0)
                grad = int(f.get("grad_year")) if f.get("grad_year") else None
                assert 0 <= cgpa <= 10 and backlogs >= 0
            except (ValueError, AssertionError):
                flash("CGPA must be 0–10 and backlogs a non-negative number.", "error")
                return redirect(url_for("student_profile"))
            db.get_db().execute(
                "UPDATE students SET name=?, email=?, skills=?, interests=?, cgpa=?, branch=?, backlogs=?,"
                " grad_year=?, resume_url=? WHERE id=?",
                (f.get("name", "").strip() or "Student", f.get("email", ""), ",".join(skills), ",".join(interests),
                 cgpa, f.get("branch", ""), backlogs, grad, f.get("resume_url", "").strip(), sid))
            if bad:
                flash("Ignored unrecognised skills: " + ", ".join(bad), "error")
            flash("Profile saved.", "ok")
            return redirect(url_for("student_home"))
        return render_template("student_profile.html", s=db.get_student(sid), vocab=VOCABULARY,
                               domains=DOMAINS, branches=BRANCHES, clusters=CLUSTERS)

    @app.route("/student/company/<int:cid>")
    @login_required("student")
    def student_company(cid):
        c = cfg()
        s, co = db.get_student(session["user"]["ref_id"]), db.get_company(cid)
        if not co or not co["participating"]:
            abort(404)
        ex = M.explain(s, co, db.weights(c))
        can_book = ex["eligible"] and ex["score"] >= float(c["tau"])
        st = schedule_state()
        free = st.free_slots(s["id"], cid) if can_book else []
        already = cid in st.student_companies[s["id"]]
        coach = ai.career_coach(db.get_db(), s, co, ex) if request.args.get("coach") else None
        return render_template("student_company.html", s=s, co=co, ex=ex, can_book=can_book,
                               free=free, already=already, coach=coach)

    @app.route("/student/book", methods=["POST"])
    @login_required("student")
    def student_book():
        c = cfg()
        sid = session["user"]["ref_id"]
        cid, slot = int(request.form["company_id"]), int(request.form["slot"])
        s, co = db.get_student(sid), db.get_company(cid)
        if not co:
            abort(404)
        sc = M.score(s, co, db.weights(c))
        con = db.get_db()
        con.execute("BEGIN IMMEDIATE")  # serialize booking writes
        try:
            st = schedule_state()
            desk = st.book(sid, cid, slot, is_eligible=M.eligible(s, co) and sc >= float(c["tau"]))
            con.execute("INSERT INTO bookings(student_id, company_id, slot, desk, score, source)"
                        " VALUES (?,?,?,?,?, 'manual')", (sid, cid, slot, desk, sc))
            con.execute("COMMIT")
            flash(f"Booked {co['name']} at {label(slot)} (desk {desk}).", "ok")
        except (ValueError, sqlite3.IntegrityError) as e:
            con.execute("ROLLBACK")
            flash(f"Could not book: {e if isinstance(e, ValueError) else 'slot was just taken.'}", "error")
            return redirect(url_for("student_company", cid=cid))
        return redirect(url_for("student_home"))

    @app.route("/student/cancel/<int:bid>", methods=["POST"])
    @login_required("student")
    def student_cancel(bid):
        n = db.get_db().execute("UPDATE bookings SET status='cancelled' WHERE id=? AND student_id=? AND status='booked'",
                                (bid, session["user"]["ref_id"])).rowcount
        flash("Booking cancelled; the slot is back in the pool." if n else "Nothing to cancel.", "ok" if n else "error")
        return redirect(url_for("student_home"))

    @app.route("/student/feedback", methods=["GET", "POST"])
    @login_required("student")
    def student_feedback():
        sid = session["user"]["ref_id"]
        con = db.get_db()
        if request.method == "POST":
            f = request.form
            cid = int(f["company_id"])
            if not con.execute("SELECT 1 FROM bookings WHERE student_id=? AND company_id=? AND status!='cancelled'",
                               (sid, cid)).fetchone():
                abort(403)
            con.execute(
                "INSERT INTO student_feedback(student_id, company_id, relevance, usefulness, convenience,"
                " wait_minutes, comments) VALUES (?,?,?,?,?,?,?) ON CONFLICT(student_id, company_id) DO UPDATE SET"
                " relevance=excluded.relevance, usefulness=excluded.usefulness, convenience=excluded.convenience,"
                " wait_minutes=excluded.wait_minutes, comments=excluded.comments",
                (sid, cid, _rating(f, "relevance"), _rating(f, "usefulness"), _rating(f, "convenience"),
                 _int(f.get("wait_minutes")), f.get("comments", "")))
            flash("Thanks for your feedback!", "ok")
            return redirect(url_for("student_feedback"))
        bookings = db.active_bookings("AND b.student_id = ?", (sid,))
        given = {r["company_id"]: r for r in con.execute("SELECT * FROM student_feedback WHERE student_id=?", (sid,))}
        return render_template("student_feedback.html", bookings=bookings, given=given)

    @app.route("/student/resume", methods=["POST"])
    @login_required("student")
    def student_resume():
        """Upload a resume, parse it, and show the profile form pre-filled for review."""
        sid = session["user"]["ref_id"]
        f = request.files.get("resume")
        if not f or not f.filename:
            flash("Choose a resume file to upload.", "error")
            return redirect(url_for("student_profile"))
        if not resume.allowed_file(f.filename):
            flash("Resume must be a PDF, DOCX or TXT file.", "error")
            return redirect(url_for("student_profile"))
        data = f.read()
        try:
            text = resume.extract_text(f.filename, data)
        except Exception:
            flash("Could not read that file. Try a different PDF/DOCX, or a text-based (not scanned) PDF.", "error")
            return redirect(url_for("student_profile"))
        if len(text.strip()) < 30:
            flash("Hardly any text was found in the resume (is it a scanned image?). Please fill the profile manually.", "error")
            return redirect(url_for("student_profile"))

        # store the file so recruiters who are matched can open it
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        ext = f.filename.rsplit(".", 1)[1].lower()
        for old in os.listdir(app.config["UPLOAD_FOLDER"]):
            if old.startswith(f"{sid}."):
                os.remove(os.path.join(app.config["UPLOAD_FOLDER"], old))
        with open(os.path.join(app.config["UPLOAD_FOLDER"], f"{sid}.{ext}"), "wb") as out:
            out.write(data)
        db.get_db().execute("UPDATE students SET resume_url=? WHERE id=?", (url_for("resume_file", sid=sid), sid))

        parsed = resume.parse_resume(text)
        s = db.get_student(sid)
        draft = dict(s)
        for key in ("name", "email", "cgpa", "branch", "grad_year", "backlogs"):
            if parsed[key] not in (None, ""):
                draft[key] = parsed[key]
        if parsed["skills"]:
            draft["skills"] = parsed["skills"]
        if parsed["interests"]:
            draft["interests"] = parsed["interests"]
        found = [k for k in ("name", "email", "skills", "interests", "cgpa", "branch", "grad_year", "backlogs")
                 if parsed[k] not in (None, "", [])]
        missing = [k for k in ("cgpa", "branch", "grad_year", "backlogs") if parsed[k] is None]
        return render_template("student_profile.html", s=draft, vocab=VOCABULARY, domains=DOMAINS,
                               branches=BRANCHES, clusters=CLUSTERS, parsed=parsed, found=found, missing=missing)

    @app.route("/resume/<int:sid>")
    def resume_file(sid):
        u = session.get("user")
        if not u:
            return redirect(url_for("login", next=request.path))
        if u["role"] == "student" and u["ref_id"] != sid:
            abort(403)
        if u["role"] == "company" and not company_can_view(db.get_company(u["ref_id"]), sid):
            abort(403)
        folder = app.config["UPLOAD_FOLDER"]
        names = [n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if n.startswith(f"{sid}.")]
        if not names:
            abort(404)
        return send_from_directory(folder, names[0])

    def company_can_view(co, sid):
        """Role-based visibility: companies see only candidates matched to or booked with them."""
        c = cfg()
        s = db.get_student(sid)
        if not s or not co:
            return False
        booked = db.get_db().execute("SELECT 1 FROM bookings WHERE student_id=? AND company_id=? AND status!='cancelled'",
                                     (sid, co["id"])).fetchone()
        return bool(booked) or (M.eligible(s, co) and M.score(s, co, db.weights(c)) >= float(c["tau"]))

    # ------------------------------------------------------------ company
    def my_company():
        return db.get_company(session["user"]["ref_id"])

    @app.route("/company")
    @login_required("company")
    def company_home():
        c = cfg()
        co = my_company()
        shortlist = [(s, M.explain(s, co, db.weights(c)))
                     for s, _ in M.shortlist_for_company(co, db.all_students(), tau=float(c["tau"]),
                                                         weights=db.weights(c))]
        schedule = db.active_bookings("AND b.company_id = ?", (co["id"],))
        booked_sids = {b["student_id"] for b in schedule}
        outcomes = {r["student_id"]: r["stage"] for r in
                    db.get_db().execute("SELECT * FROM outcomes WHERE company_id=?", (co["id"],))}
        return render_template("company_home.html", co=co, shortlist=shortlist, schedule=schedule,
                               booked_sids=booked_sids, outcomes=outcomes)

    @app.route("/company/profile", methods=["GET", "POST"])
    @login_required("company")
    def company_profile():
        co = my_company()
        if request.method == "POST":
            f = request.form
            try:
                min_cgpa, max_bl, desks = float(f.get("min_cgpa") or 0), int(f.get("max_backlogs") or 0), int(f.get("desks") or 1)
                assert 0 <= min_cgpa <= 10 and max_bl >= 0 and 1 <= desks <= 20
            except (ValueError, AssertionError):
                flash("Check CGPA (0–10), backlogs (≥0) and desks (1–20).", "error")
                return redirect(url_for("company_profile"))
            req = normalize_skills(f.get("required", ""))
            if not req:
                flash("At least one recognised required skill is needed.", "error")
                return redirect(url_for("company_profile"))
            pref = [p for p in normalize_skills(f.get("preferred", "")) if p not in req]
            branches = [b for b in f.getlist("branches") if b in BRANCHES]
            db.get_db().execute(
                "UPDATE companies SET name=?, role_title=?, domain=?, description=?, required=?, preferred=?,"
                " min_cgpa=?, branches=?, max_backlogs=?, desks=? WHERE id=?",
                (f.get("name", co["name"]).strip() or co["name"], f.get("role_title", ""), f.get("domain", ""),
                 f.get("description", ""), ",".join(req), ",".join(pref), min_cgpa, ",".join(branches),
                 max_bl, desks, co["id"]))
            flash("Requirements saved.", "ok")
            return redirect(url_for("company_home"))
        return render_template("company_profile.html", co=co, domains=DOMAINS, branches=BRANCHES, vocab=VOCABULARY)

    @app.route("/company/candidate/<int:sid>")
    @login_required("company")
    def company_candidate(sid):
        c = cfg()
        co, s = my_company(), db.get_student(sid)
        if not s:
            abort(404)
        if not company_can_view(co, sid):
            abort(403)
        ex = M.explain(s, co, db.weights(c))
        brief = ai.candidate_summary(db.get_db(), s, co, ex) if request.args.get("brief") else None
        return render_template("company_candidate.html", co=co, s=s, ex=ex, brief=brief)

    @app.route("/company/booking/<int:bid>/status", methods=["POST"])
    @login_required("company")
    def company_booking_status(bid):
        status = request.form.get("status")
        if status not in ("attended", "no_show", "booked"):
            abort(400)
        db.get_db().execute("UPDATE bookings SET status=? WHERE id=? AND company_id=? AND status!='cancelled'",
                            (status, bid, session["user"]["ref_id"]))
        return redirect(url_for("company_home") + "#schedule")

    @app.route("/company/outcome", methods=["POST"])
    @login_required("company")
    def company_outcome():
        cid, sid, stage = session["user"]["ref_id"], int(request.form["student_id"]), request.form.get("stage")
        con = db.get_db()
        if not con.execute("SELECT 1 FROM bookings WHERE student_id=? AND company_id=? AND status!='cancelled'",
                           (sid, cid)).fetchone():
            abort(403)
        if stage == "none":
            con.execute("DELETE FROM outcomes WHERE student_id=? AND company_id=?", (sid, cid))
        elif stage in ("interview", "offer"):
            con.execute("INSERT INTO outcomes(student_id, company_id, stage) VALUES (?,?,?)"
                        " ON CONFLICT(student_id, company_id) DO UPDATE SET stage=excluded.stage", (sid, cid, stage))
        else:
            abort(400)
        return redirect(url_for("company_home") + "#schedule")

    @app.route("/company/feedback", methods=["GET", "POST"])
    @login_required("company")
    def company_feedback():
        cid = session["user"]["ref_id"]
        con = db.get_db()
        if request.method == "POST":
            f = request.form
            con.execute(
                "INSERT INTO company_feedback(company_id, candidate_quality, skill_alignment, to_interview,"
                " shortlist_accuracy, comments) VALUES (?,?,?,?,?,?) ON CONFLICT(company_id) DO UPDATE SET"
                " candidate_quality=excluded.candidate_quality, skill_alignment=excluded.skill_alignment,"
                " to_interview=excluded.to_interview, shortlist_accuracy=excluded.shortlist_accuracy,"
                " comments=excluded.comments",
                (cid, _rating(f, "candidate_quality"), _rating(f, "skill_alignment"), _int(f.get("to_interview")),
                 _rating(f, "shortlist_accuracy"), f.get("comments", "")))
            flash("Feedback saved. Thank you!", "ok")
            return redirect(url_for("company_feedback"))
        fb = con.execute("SELECT * FROM company_feedback WHERE company_id=?", (cid,)).fetchone()
        return render_template("company_feedback.html", fb=fb, co=my_company())

    # ------------------------------------------------------------ admin
    @app.route("/admin")
    @login_required("admin")
    def admin_home():
        comps = db.all_companies(participating_only=False)
        counts = {r["company_id"]: r["n"] for r in db.get_db().execute(
            "SELECT company_id, COUNT(*) n FROM bookings WHERE status!='cancelled' GROUP BY company_id")}
        n_students = db.get_db().execute("SELECT COUNT(*) FROM students").fetchone()[0]
        return render_template("admin_home.html", comps=comps, counts=counts, n_students=n_students,
                               n_bookings=sum(counts.values()))

    @app.route("/admin/settings", methods=["POST"])
    @login_required("admin")
    def admin_settings():
        f = request.form
        try:
            vals = {
                "fair_name": f["fair_name"].strip() or "Career Fair", "fair_date": f["fair_date"],
                "start_time": f["start_time"], "slot_len": str(int(f["slot_len"])),
                "num_slots": str(int(f["num_slots"])), "max_bookings": str(int(f["max_bookings"])),
                "w_skill": str(float(f["w_skill"])), "w_interest": str(float(f["w_interest"])),
                "w_academic": str(float(f["w_academic"])), "tau": str(float(f["tau"])),
                "top_k": str(int(f["top_k"])),
            }
            assert int(vals["slot_len"]) > 0 and 0 < int(vals["num_slots"]) <= 200
            h, m = map(int, vals["start_time"].split(":"))
            assert 0 <= h < 24 and 0 <= m < 60
        except (KeyError, ValueError, AssertionError):
            flash("Invalid settings.", "error")
            return redirect(url_for("admin_home"))
        con = db.get_db()
        for k, v in vals.items():
            con.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        flash("Fair settings updated.", "ok")
        return redirect(url_for("admin_home"))

    @app.route("/admin/company/<int:cid>/toggle", methods=["POST"])
    @login_required("admin")
    def admin_toggle(cid):
        db.get_db().execute("UPDATE companies SET participating = 1 - participating WHERE id=?", (cid,))
        return redirect(url_for("admin_home"))

    @app.route("/admin/company/new", methods=["POST"])
    @login_required("admin")
    def admin_new_company():
        f = request.form
        name, uname, pw = f.get("name", "").strip(), f.get("username", "").strip(), f.get("password", "")
        if not name or not uname or len(pw) < 6:
            flash("Company name, username and a 6+ character password are required.", "error")
            return redirect(url_for("admin_home"))
        con = db.get_db()
        if con.execute("SELECT 1 FROM users WHERE username=?", (uname,)).fetchone():
            flash("Username taken.", "error")
            return redirect(url_for("admin_home"))
        con.execute("BEGIN")
        cur = con.execute("INSERT INTO companies(name, branches, required) VALUES (?, ?, '')", (name, ",".join(BRANCHES)))
        con.execute("INSERT INTO users(username, password_hash, role, ref_id) VALUES (?,?, 'company', ?)",
                    (uname, generate_password_hash(pw), cur.lastrowid))
        con.execute("COMMIT")
        flash(f"Company {name} created. They can log in as '{uname}' and set requirements.", "ok")
        return redirect(url_for("admin_home"))

    @app.route("/admin/auto-schedule", methods=["POST"])
    @login_required("admin")
    def admin_auto_schedule():
        c = cfg()
        w = db.weights(c)
        comps, students = db.all_companies(), db.all_students()
        con = db.get_db()
        con.execute("BEGIN IMMEDIATE")
        try:
            st = schedule_state()
            pairs = []
            for s in students:
                for co, sc in M.recommend_for_student(s, comps, k=st.max_bookings, tau=float(c["tau"]), weights=w):
                    pairs.append((s["id"], co["id"], sc))
            scores = {(a, b): sc for a, b, sc in pairs}
            placed, unplaced = auto_schedule(pairs, st, random.Random())
            con.executemany("INSERT INTO bookings(student_id, company_id, slot, desk, score, source)"
                            " VALUES (?,?,?,?,?, 'auto')", [(s, co, t, d, scores[(s, co)]) for s, co, t, d in placed])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        flash(f"Auto-scheduler placed {len(placed)} bookings; {len(unplaced)} could not be placed.", "ok")
        return redirect(url_for("admin_home"))

    @app.route("/admin/reset-bookings", methods=["POST"])
    @login_required("admin")
    def admin_reset_bookings():
        con = db.get_db()
        con.execute("DELETE FROM bookings")
        con.execute("DELETE FROM outcomes")
        flash("All bookings and outcomes cleared.", "ok")
        return redirect(url_for("admin_home"))

    # ------------------------------------------------------------ AI / ML (admin)
    @app.route("/admin/ai")
    @login_required("admin")
    def admin_ai():
        raw = cfg().get("ml_report")
        report = json.loads(raw) if raw else None
        con = db.get_db()
        counts = {r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) n FROM bookings WHERE status != 'cancelled' GROUP BY status")}
        n_outcomes = con.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
        provider = ai.active_provider(con)
        providers = [{"id": pid, **meta, "key": ai.mask(ai.api_key(con, pid)), "model": ai.model_for(con, pid)}
                     for pid, meta in ai.PROVIDERS.items()]
        return render_template("admin_ai.html", report=report, provider=provider, providers=providers,
                               choice=cfg().get("ai_provider") or "auto", labels=ai.SOURCE_LABELS,
                               counts=counts, n_outcomes=n_outcomes)

    @app.route("/admin/ai/provider", methods=["POST"])
    @login_required("admin")
    def admin_ai_provider():
        f = request.form
        choice = f.get("ai_provider", "auto")
        if choice not in ("auto", "offline", *ai.PROVIDERS):
            abort(400)
        _set_setting("ai_provider", choice)
        for pid in ai.PROVIDERS:
            key = f.get(f"{pid}_api_key", "").strip()
            if key:
                _set_setting(f"{pid}_api_key", key)
            if f.get(f"{pid}_clear"):
                _set_setting(f"{pid}_api_key", "")
            if f"{pid}_model" in f:
                _set_setting(f"{pid}_model", f.get(f"{pid}_model", "").strip())
        if f.get("test"):
            target = ai.active_provider(db.get_db())
            if not target:
                flash("No provider with a saved key. Paste a free Gemini or Groq key first.", "error")
            else:
                ok, msg = ai.test_connection(db.get_db(), target)
                flash(f"{ai.SOURCE_LABELS[target]}: {msg}", "ok" if ok else "error")
        else:
            flash("AI settings saved.", "ok")
        return redirect(url_for("admin_ai"))

    @app.route("/admin/ai/simulate", methods=["POST"])
    @login_required("admin")
    def admin_simulate():
        con = db.get_db()
        if not con.execute("SELECT 1 FROM bookings WHERE status != 'cancelled'").fetchone():
            flash("No bookings yet. Run the auto-scheduler first.", "error")
            return redirect(url_for("admin_ai"))
        st = fairsim.simulate_fair_day(con, db.all_students(), db.all_companies(participating_only=False))
        flash(f"Simulated fair day: {st['attended']} attended, {st['no_show']} no-shows, {st['interview']} interviews, "
              f"{st['offer']} offers, {st['s_feedback']} student + {st['c_feedback']} company feedback forms.", "ok")
        return redirect(url_for("admin_ai"))

    @app.route("/admin/ai/train", methods=["POST"])
    @login_required("admin")
    def admin_train():
        inp = _analytics_inputs()
        report = learning.learn_weights(inp["students"], inp["companies"], inp["bookings"], inp["outcomes"],
                                        inp["s_feedback"], db.weights())
        _set_setting("ml_report", json.dumps(report))
        flash("Model trained." if report["ok"] else report["reason"], "ok" if report["ok"] else "error")
        return redirect(url_for("admin_ai"))

    @app.route("/admin/ai/apply", methods=["POST"])
    @login_required("admin")
    def admin_apply_weights():
        raw = cfg().get("ml_report")
        report = json.loads(raw) if raw else None
        if not report or not report.get("ok"):
            abort(400)
        lw = report["learned"]
        for key, name in (("w_skill", "skill"), ("w_interest", "interest"), ("w_academic", "academic")):
            _set_setting(key, str(lw[name]))
        flash(f"Applied learned weights: skill {lw['skill']}, interest {lw['interest']}, academic {lw['academic']}.", "ok")
        return redirect(url_for("admin_ai"))

    def _set_setting(key, value):
        db.get_db().execute("INSERT INTO settings(key, value) VALUES (?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def _analytics_inputs():
        con = db.get_db()
        return dict(
            students=db.all_students(), companies=db.all_companies(),
            bookings=[dict(r) for r in db.active_bookings()],
            s_feedback=[dict(r) for r in con.execute("SELECT * FROM student_feedback")],
            c_feedback=[dict(r) for r in con.execute("SELECT * FROM company_feedback")],
            outcomes=[dict(r) for r in con.execute("SELECT * FROM outcomes")], cfg=cfg())

    @app.route("/admin/analytics")
    @login_required("admin")
    def admin_analytics():
        branch = request.args.get("branch") or None
        domain = request.args.get("domain") or None
        company_id = request.args.get("company", type=int) or None
        data = analytics.compute(**_analytics_inputs(), branch=branch, domain=domain, company_id=company_id)
        return render_template("admin_analytics.html", a=data, branches=BRANCHES, domains=DOMAINS,
                               comps=db.all_companies(), f={"branch": branch, "domain": domain, "company": company_id})

    @app.route("/admin/export/<kind>.csv")
    @login_required("admin")
    def admin_export(kind):
        con = db.get_db()
        c = cfg()
        buf = io.StringIO()
        w = csv.writer(buf)
        if kind == "bookings":
            w.writerow(["booking_id", "student", "branch", "company", "slot", "time", "desk", "score", "source", "status"])
            for b in con.execute("SELECT b.*, s.name sn, s.branch, c.name cn FROM bookings b JOIN students s ON s.id=b.student_id"
                                 " JOIN companies c ON c.id=b.company_id WHERE b.status!='cancelled' ORDER BY c.name, b.slot"):
                w.writerow([b["id"], b["sn"], b["branch"], b["cn"], b["slot"], label(b["slot"]), b["desk"],
                            f"{b['score'] or 0:.3f}", b["source"], b["status"]])
        elif kind == "matches":
            w.writerow(["student", "branch", "company", "score", "skill_fit", "interest", "cgpa_margin", "missing_required"])
            comps = db.all_companies()
            for s in db.all_students():
                for co, _ in M.recommend_for_student(s, comps, k=int(c["top_k"]), tau=float(c["tau"]), weights=db.weights(c)):
                    ex = M.explain(s, co, db.weights(c))
                    w.writerow([s["name"], s["branch"], co["name"], ex["score"], ex["skill_fit"], ex["interest_match"],
                                ex["cgpa_margin"], ";".join(ex["missing_required"])])
        elif kind == "feedback":
            w.writerow(["type", "student", "company", "relevance/quality", "usefulness/alignment",
                        "convenience/shortlist_accuracy", "wait_min/to_interview", "comments"])
            for r in con.execute("SELECT f.*, s.name sn, c.name cn FROM student_feedback f JOIN students s ON s.id=f.student_id"
                                 " JOIN companies c ON c.id=f.company_id"):
                w.writerow(["student", r["sn"], r["cn"], r["relevance"], r["usefulness"], r["convenience"],
                            r["wait_minutes"], r["comments"]])
            for r in con.execute("SELECT f.*, c.name cn FROM company_feedback f JOIN companies c ON c.id=f.company_id"):
                w.writerow(["company", "", r["cn"], r["candidate_quality"], r["skill_alignment"],
                            r["shortlist_accuracy"], r["to_interview"], r["comments"]])
        else:
            abort(404)
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={kind}.csv"})

    @app.errorhandler(413)
    def too_large(_e):
        flash("That file is larger than 5 MB.", "error")
        return redirect(url_for("student_profile"))

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, msg="You do not have access to this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, msg="Page not found."), 404

    return app


def _rating(form, key):
    try:
        v = int(form.get(key))
        return v if 1 <= v <= 5 else None
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return None
