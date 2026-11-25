"""AI assistant features powered by an LLM, with an offline fallback.

* career_coach(con, student, company, ex)      - personalised preparation plan for a student
* candidate_summary(con, student, company, ex)  - short recruiter-facing brief on a candidate

Supported providers (pick one on Admin -> AI & ML, or via environment variables):
  gemini  - Google Gemini, FREE key from https://aistudio.google.com/apikey   (GEMINI_API_KEY)
  groq    - Groq (open models), FREE key from https://console.groq.com/keys    (GROQ_API_KEY)
  claude  - Anthropic Claude, paid key                                         (ANTHROPIC_API_KEY)
  offline - built-in rule-based generator, no key needed

If no key is configured, or a call fails, the offline generator answers instead, so
the app always works. Responses are cached in the `ai_cache` table.
"""
import hashlib
import json
import os
import urllib.error
import urllib.request

CLAUDE_MODEL = "claude-opus-5-5"
MODEL = CLAUDE_MODEL  # kept for templates that show the Claude model name

PROVIDERS = {
    "gemini": {"label": "Google Gemini (free)", "env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
               "default_model": "gemini-flash-latest", "key_url": "https://aistudio.google.com/apikey"},
    "groq": {"label": "Groq (free)", "env": ("GROQ_API_KEY",), "default_model": "",
             "key_url": "https://console.groq.com/keys"},
    "claude": {"label": "Anthropic Claude (paid)", "env": ("ANTHROPIC_API_KEY",),
               "default_model": CLAUDE_MODEL, "key_url": "https://console.anthropic.com/"},
}
SOURCE_LABELS = {"gemini": "Google Gemini", "groq": "Groq", "claude": "Claude", "offline": "Offline AI assistant (rule-based)"}
TIMEOUT = 40  # seconds per API call


# ------------------------------------------------------------------ configuration
def _setting(con, key):
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row and row["value"] else ""


def api_key(con, provider):
    """Key saved on the admin page wins; otherwise fall back to environment variables."""
    key = _setting(con, f"{provider}_api_key")
    if key:
        return key
    for var in PROVIDERS[provider]["env"]:
        if os.environ.get(var):
            return os.environ[var]
    return ""


def active_provider(con):
    """Return the provider to use ('gemini' | 'groq' | 'claude') or None for offline."""
    if os.environ.get("CAREERMATCH_AI", "").lower() in ("off", "0", "false"):
        return None
    choice = _setting(con, "ai_provider") or "auto"
    if choice == "offline":
        return None
    if choice in PROVIDERS:
        return choice if api_key(con, choice) else None
    for name in ("gemini", "groq", "claude"):  # auto: first provider with a key
        if api_key(con, name):
            return name
    return None


def ai_enabled(con=None) -> bool:
    if con is None:
        from . import db
        con = db.get_db()
    return active_provider(con) is not None


def model_for(con, provider):
    return _setting(con, f"{provider}_model") or PROVIDERS[provider]["default_model"]


def mask(key):
    return f"saved (…{key[-4:]})" if key else "not set"


# ------------------------------------------------------------------ public API

LEARNING_TIPS = {
    "Python": "solve 20-30 problems on HackerRank/LeetCode and build one small Flask or data project",
    "Java": "practise OOP concepts, collections and a small Spring Boot REST API",
    "C++": "revise STL, pointers and memory management; practise DSA problems",
    "JavaScript": "learn ES6+, async/await and DOM basics; build a small interactive page",
    "React": "build a 3-4 page React app with hooks, routing and an API call",
    "Node.js": "build a REST API with Express and connect it to a database",
    "SQL": "practise joins, GROUP BY and window functions on a sample database",
    "Git": "use Git daily: branches, pull requests and resolving merge conflicts",
    "Machine Learning": "complete an end-to-end scikit-learn project with proper train/test evaluation",
    "Data Analysis": "analyse a public dataset and present findings with charts",
    "Statistics": "revise distributions, hypothesis testing and regression",
    "Pandas": "practise cleaning, merging and grouping real CSV datasets",
    "Deep Learning": "train a small CNN or transformer model with PyTorch or Keras",
    "Power BI": "build a dashboard from a sample sales dataset",
    "AWS": "deploy a small app on EC2/S3 using the AWS free tier",
    "Azure": "complete the AZ-900 fundamentals learning path",
    "Docker": "containerise one of your projects and write a docker-compose file",
    "Kubernetes": "deploy a container to a local cluster with minikube or kind",
    "Linux": "get comfortable with the shell, permissions, processes and bash scripting",
    "DevOps": "set up a CI pipeline (GitHub Actions) that tests and builds a project",
    "Embedded C": "program a microcontroller board: GPIO, timers and interrupts",
    "VLSI": "revise digital design and CMOS basics; simulate small circuits",
    "PCB Design": "design a simple two-layer board in KiCad",
    "Microcontrollers": "build a sensor project on Arduino or STM32",
    "Verilog": "write and simulate counters, FSMs and a small ALU",
    "AutoCAD": "practise 2D drafting and dimensioning exercises",
    "SolidWorks": "model and assemble a small mechanical part; prepare drawings",
    "CAD/CAM": "learn toolpath generation for a simple part",
    "Thermodynamics": "revise laws, cycles and numerical problems",
    "ANSYS": "run a basic static structural analysis tutorial",
    "Excel": "master pivot tables, VLOOKUP/XLOOKUP and charts",
    "Marketing": "study a real campaign and prepare a short marketing plan",
    "Finance": "revise financial statements, ratios and basic valuation",
    "Communication": "practise a 2-minute self-introduction and mock group discussions",
    "Project Management": "learn Agile/Scrum basics and plan a project with milestones",
    "UI/UX": "redesign an existing app screen and document your design decisions",
    "Figma": "build a clickable prototype in Figma with components and auto-layout",
    "Photoshop": "practise photo editing and compositing tutorials",
    "Graphic Design": "create a small portfolio of posters and social media creatives",
    "Prototyping": "turn a paper sketch into an interactive prototype and user-test it",
}

INTERVIEW_TOPICS = {
    "software": "data structures & algorithms, OOP, DBMS, operating systems and one project deep-dive",
    "data": "statistics, SQL queries, ML fundamentals (bias/variance, metrics) and a case study",
    "cloud": "Linux, networking basics, containers, CI/CD and cloud service trade-offs",
    "hardware": "digital electronics, microcontroller architecture and circuit debugging",
    "mechanical": "strength of materials, thermodynamics, manufacturing processes and CAD",
    "business": "case interviews, guesstimates, Excel modelling and communication",
    "design": "portfolio walkthrough, design process, usability principles and a whiteboard exercise",
}


# ------------------------------------------------------------------ public API
def career_coach(con, student, company, ex):
    payload = _payload(student, company, ex)
    return _cached(con, "coach", payload, COACH_SYSTEM, lambda: _offline_coach(student, company, ex))


def candidate_summary(con, student, company, ex):
    payload = _payload(student, company, ex)
    return _cached(con, "summary", payload, SUMMARY_SYSTEM, lambda: _offline_summary(student, company, ex))


def test_connection(con, provider):
    """Send a tiny request; returns (ok, message)."""
    key = api_key(con, provider)
    if not key:
        return False, "No API key saved for this provider."
    try:
        text = _call(con, provider, "Reply with the single word OK.", "Connection test")
        return True, f"Connected. Model: {model_for(con, provider)}. Reply: {text[:40]!r}"
    except Exception as e:
        return False, _short_error(e)


# ------------------------------------------------------------------ prompts
COACH_SYSTEM = (
    "You are a campus placement career coach helping a student prepare to meet a recruiter at a career fair. "
    "You get the student's profile, the company's role requirements and the platform's match explanation as JSON. "
    "Write a short, specific preparation plan in plain text (no markdown headings, no bold). Use exactly these "
    "sections, each a label on its own line followed by 2-4 lines starting with '- ':\n"
    "Why you match:\nGaps to close before the fair:\nWhat to say at the booth:\nLikely interview topics:\n"
    "Be concrete and encouraging; refer to the actual skills. Keep it under 200 words. If the student is not "
    "eligible, say so kindly and focus on what they can do instead."
)

SUMMARY_SYSTEM = (
    "You are an assistant to a campus recruiter. Given a candidate's profile, the role requirements and the "
    "platform's match explanation as JSON, write a recruiter brief in plain text (no markdown headings, no bold): "
    "one sentence overall fit, then 'Strengths:' with 2-3 lines starting '- ', then 'Probe in interview:' with 2-3 "
    "lines starting '- ' (questions to verify skills or gaps). Under 120 words. Judge only on skills, academics and "
    "interests given; never comment on name, gender or other personal attributes."
)


# ------------------------------------------------------------------ provider calls
def _call(con, provider, system, user_text):
    if provider == "gemini":
        return _gemini(con, system, user_text)
    if provider == "groq":
        return _groq(con, system, user_text)
    if provider == "claude":
        return _claude(con, system, user_text)
    raise ValueError(f"unknown provider {provider}")


def _http_json(url, body=None, headers=None):
    """POST (or GET when body is None) JSON with the standard library; returns parsed JSON."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "CareerMatchAI/1.0",
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        try:  # both Gemini and Groq return {"error": {"message": ...}}
            detail = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            pass
        raise ApiError(e.code, str(detail)[:200]) from None


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status


def _save_model(con, provider, model):
    con.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"{provider}_model", model))


# ---- Google Gemini (REST: generativelanguage.googleapis.com) ----
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _gemini(con, system, user_text, _retry=True):
    key, model = api_key(con, "gemini"), model_for(con, "gemini")
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1500}}
    try:
        data = _http_json(f"{GEMINI_BASE}/models/{model}:generateContent", body, {"x-goog-api-key": key})
    except ApiError as e:
        if e.status == 404 and _retry:  # model name retired/unknown -> discover a current free Flash model
            _save_model(con, "gemini", _discover_gemini_model(key))
            return _gemini(con, system, user_text, _retry=False)
        raise
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "no candidates"
        raise RuntimeError(f"Gemini returned no text ({reason})")
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise RuntimeError("empty response")
    return text


def _discover_gemini_model(key):
    data = _http_json(f"{GEMINI_BASE}/models?pageSize=200", headers={"x-goog-api-key": key})
    names = [m["name"].split("/", 1)[-1] for m in data.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and not any(x in n for x in ("image", "tts", "audio", "live", "exp"))]
    # prefer the stable "latest" alias, then non-lite, non-preview, newest version first
    pick = sorted(sorted(flash, reverse=True), key=lambda n: ("latest" not in n, "lite" in n, "preview" in n))
    if not pick and not names:
        raise RuntimeError("No Gemini text models available for this key")
    return (pick or names)[0]


# ---- Groq (OpenAI-compatible REST: api.groq.com) ----
GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_PREFERRED = ("openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "qwen/qwen3-32b")


def _groq(con, system, user_text, _retry=True):
    key = api_key(con, "groq")
    model = model_for(con, "groq")
    if not model:
        model = _discover_groq_model(key)
        _save_model(con, "groq", model)
    body = {"model": model, "temperature": 0.4, "max_tokens": 1500,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}]}
    try:
        data = _http_json(f"{GROQ_BASE}/chat/completions", body, {"Authorization": f"Bearer {key}"})
    except ApiError as e:
        if e.status in (400, 404) and _retry and "model" in str(e).lower():  # decommissioned model
            _save_model(con, "groq", _discover_groq_model(key, exclude=model))
            return _groq(con, system, user_text, _retry=False)
        raise
    text = (data["choices"][0]["message"].get("content") or "").strip()
    if not text:
        raise RuntimeError("empty response")
    return text


def _discover_groq_model(key, exclude=None):
    data = _http_json(f"{GROQ_BASE}/models", headers={"Authorization": f"Bearer {key}"})
    ids = [m["id"] for m in data.get("data", []) if m.get("active", True) and m["id"] != exclude
           and not any(x in m["id"] for x in ("whisper", "tts", "guard", "embed", "vision"))]
    for pref in GROQ_PREFERRED:
        if pref in ids:
            return pref
    if not ids:
        raise RuntimeError("No Groq chat models available for this key")
    return ids[0]


# ---- Anthropic Claude (official SDK) ----
def _claude(con, system, user_text):
    import anthropic  # imported lazily so the app runs without the SDK

    client = anthropic.Anthropic(api_key=api_key(con, "claude"), timeout=TIMEOUT)
    response = client.beta.messages.create(
        model=model_for(con, "claude"),
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request")
    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("empty response")
    return text


def _short_error(e):
    if isinstance(e, ApiError):
        hint = {400: "check the key", 401: "invalid key", 403: "key not allowed", 429: "free quota reached, try later"}
        return f"{e} ({hint[e.status]})" if e.status in hint else str(e)
    if isinstance(e, urllib.error.URLError):
        return f"Network error: {e.reason}. Check the internet connection."
    return f"{type(e).__name__}: {e}"[:220]


def _payload(s, c, ex):
    return {
        "student": {"skills": sorted(s["skills"]), "interests": s["interests"], "cgpa": s["cgpa"],
                    "branch": s["branch"], "active_backlogs": s["backlogs"], "graduation_year": s.get("grad_year")},
        "company": {"name": c["name"], "role": c.get("role_title"), "domain": c["domain"],
                    "required_skills": c["required"], "preferred_skills": c["preferred"],
                    "min_cgpa": c["min_cgpa"], "allowed_branches": c["branches"], "max_backlogs": c["max_backlogs"]},
        "match": {k: ex[k] for k in ("eligible", "ineligible_reasons", "score", "skill_fit", "matched_required",
                                     "missing_required", "matched_preferred", "interest_match", "cgpa_margin")},
    }


def _cached(con, kind, payload, system, offline_fn):
    key = kind + ":" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    row = con.execute("SELECT source, text FROM ai_cache WHERE key = ?", (key,)).fetchone()
    provider = active_provider(con)
    # reuse a cached LLM answer; regenerate an offline one once an LLM becomes available
    if row and (row["source"] != "offline" or provider is None):
        return {"source": row["source"], "text": row["text"]}
    source, text, error = "offline", None, None
    if provider:
        try:
            text, source = _call(con, provider, system, json.dumps(payload, indent=1)), provider
        except Exception as e:  # network/auth/quota/refusal: fall back, never break the page
            error = _short_error(e)
    if text is None:
        text = offline_fn()
    con.execute("INSERT INTO ai_cache(key, source, text) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET source=excluded.source, text=excluded.text", (key, source, text))
    return {"source": source, "text": text, "error": error}


# ------------------------------------------------------------------ offline fallback
def _offline_coach(s, c, ex):
    lines = []
    if not ex["eligible"]:
        lines.append("Eligibility:")
        lines += [f"- {r}" for r in ex["ineligible_reasons"]]
        lines.append(f"- You can't book {c['name']} this time, but the skills below are still worth building for similar roles.")
    lines.append("Why you match:")
    if ex["matched_required"]:
        lines.append(f"- You already have {len(ex['matched_required'])} of {len(c['required'])} required skills: "
                     f"{', '.join(ex['matched_required'])}.")
    if ex["matched_preferred"]:
        lines.append(f"- Bonus skills they like: {', '.join(ex['matched_preferred'])}.")
    if ex["interest_match"]:
        lines.append(f"- The {c['domain']} domain is one of your declared interests, so show that enthusiasm.")
    if ex["cgpa_margin"] >= 0:
        lines.append(f"- Your CGPA clears their cut-off by {ex['cgpa_margin']:.2f} points.")
    if len(lines) == 1 or lines[-1].endswith("match:"):
        lines.append("- Your profile has limited overlap with this role so far.")

    lines.append("Gaps to close before the fair:")
    gaps = ex["missing_required"] or [p for p in c["preferred"] if p not in s["skills"]][:2]
    if gaps:
        lines += [f"- {g}: {LEARNING_TIPS.get(g, 'do a short hands-on project using it')}." for g in gaps[:4]]
    else:
        lines.append("- No required-skill gaps. Polish one project that uses their stack end to end.")

    lines.append("What to say at the booth:")
    top = ", ".join((ex["matched_required"] or sorted(s["skills"]))[:3]) or "your strongest skills"
    lines.append(f"- Open with a 30-second pitch on a project that used {top}.")
    if ex["missing_required"]:
        lines.append(f"- Be honest that you're learning {ex['missing_required'][0]} and say what you've done so far.")
    lines.append(f"- Ask what a first project looks like for a {c.get('role_title') or 'new hire'} at {c['name']}.")

    lines.append("Likely interview topics:")
    lines.append(f"- {INTERVIEW_TOPICS.get(c['domain'], 'core subject fundamentals and your projects')}.")
    return "\n".join(lines)


def _offline_summary(s, c, ex):
    pct = round(ex["score"] * 100)
    fit = "Strong" if pct >= 70 else "Good" if pct >= 50 else "Partial"
    lines = [f"{fit} fit ({pct}/100) for {c.get('role_title') or c['name']}: covers "
             f"{len(ex['matched_required'])}/{len(c['required'])} required skills, {s['branch']}, CGPA {s['cgpa']}."]
    lines.append("Strengths:")
    if ex["matched_required"]:
        lines.append(f"- Required skills: {', '.join(ex['matched_required'])}.")
    if ex["matched_preferred"]:
        lines.append(f"- Preferred skills: {', '.join(ex['matched_preferred'])}.")
    if ex["interest_match"]:
        lines.append(f"- Declared interest in {c['domain']}.")
    if ex["cgpa_margin"] > 0.5:
        lines.append(f"- Comfortably above CGPA cut-off (+{ex['cgpa_margin']:.2f}).")
    lines.append("Probe in interview:")
    if ex["missing_required"]:
        lines.append(f"- Exposure to {', '.join(ex['missing_required'])} (listed as missing).")
    if ex["matched_required"]:
        lines.append(f"- Ask for a project where they applied {ex['matched_required'][0]} in depth.")
    lines.append("- Self-reported skills: verify with a short practical question.")
    return "\n".join(lines)
