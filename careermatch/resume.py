"""Resume parsing: build a student profile draft from an uploaded resume.

Supports PDF (via pypdf), DOCX (read directly from the zip XML) and plain text.
Extraction is rule-based against the controlled skill vocabulary, so every
detected skill is a canonical tag the matcher understands.
"""
import io
import re
import zipfile
from collections import Counter

from .skills import CLUSTERS, VOCABULARY, _ALIASES

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}

# aliases that are too ambiguous to trust in free text ("pm" = time, "py" = file ext, ...)
_SKIP_ALIASES = {"pm", "py", "dl", "ui", "cad", "node", "embedded", "stats"}

_SKILL_TERMS = [(s.lower(), s) for s in VOCABULARY] + \
               [(a, s) for a, s in _ALIASES.items() if a not in _SKIP_ALIASES]
_SKILL_TERMS.sort(key=lambda x: -len(x[0]))  # longest first

_CLUSTER_OF = {s: cl for cl, skills in CLUSTERS.items() for s in skills}

# ordered: more specific phrases first
_BRANCH_PATTERNS = [
    (r"computer science|\bcse\b|computer engineering", "CSE"),
    (r"information technology|\bb\.?\s?tech\.?\s*\(?it\)?\b|\bit\s+branch", "IT"),
    (r"electronics\s*(and|&)\s*communication|\bece\b", "ECE"),
    (r"electrical|\beee?\b", "EE"),
    (r"mechanical", "ME"),
    (r"\bmba\b|business administration", "MBA"),
    (r"\bb\.?\s?des\b|bachelor of design|\bm\.?\s?des\b", "DES"),
]


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text(filename: str, data: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if ext == "docx":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:tab/>", " ", xml)
        return re.sub(r"<[^>]+>", "", xml)
    return data.decode("utf-8", "ignore")


def _find_skills(text: str) -> list:
    low = " " + text.lower() + " "
    found = []
    for term, canon in _SKILL_TERMS:
        pat = r"(?<![a-z0-9+#])" + re.escape(term) + r"(?![a-z0-9+#])"
        if re.search(pat, low) and canon not in found:
            found.append(canon)
    return [s for s in VOCABULARY if s in found]


def _find_cgpa(text: str):
    low = text.lower()
    for m in re.finditer(r"(c\.?g\.?p\.?a|cpi|gpa|sgpa)\D{0,20}?(\d{1,2}(?:\.\d{1,2})?)\s*(/\s*(10|4))?", low):
        val = float(m.group(2))
        scale = m.group(4)
        if scale == "4" and val <= 4:
            return round(val * 2.5, 2)
        if 0 < val <= 10:
            return val
    m = re.search(r"(\d{1,2}\.\d{1,2})\s*/\s*10", low)
    if m and float(m.group(1)) <= 10:
        return float(m.group(1))
    return None


def _find_branch(text: str):
    low = text.lower()
    for pat, branch in _BRANCH_PATTERNS:
        if re.search(pat, low):
            return branch
    return None


def _find_grad_year(text: str):
    low = text.lower()
    m = re.search(r"(expected|graduat\w*|batch|class of|passing)\D{0,25}(20[2-3]\d)", low)
    if m:
        return int(m.group(2))
    ranges = re.findall(r"(20[1-3]\d)\s*[-–—to]+\s*(20[2-3]\d)", low)
    if ranges:
        return max(int(b) for _, b in ranges)
    return None


def _find_backlogs(text: str):
    low = text.lower()
    if re.search(r"\b(no|zero|nil)\s+(active\s+)?backlogs?\b", low):
        return 0
    m = re.search(r"(\d+)\s+(active\s+)?backlogs?\b", low) or re.search(r"backlogs?\s*[:\-]\s*(\d+)", low)
    return int(m.group(1)) if m else None


def _find_email(text: str):
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    return m.group(0) if m else None


def _find_name(text: str):
    for line in text.splitlines()[:8]:
        line = line.strip()
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z.'-]+", w) for w in words) \
                and not re.search(r"resume|curriculum|vitae|profile", line, re.I):
            return " ".join(w.capitalize() if w.isupper() else w for w in words)
    return None


def parse_resume(text: str) -> dict:
    """Return a profile draft; fields that could not be found are None/empty."""
    skills = _find_skills(text)
    counts = Counter(_CLUSTER_OF[s] for s in skills)
    interests = [cl for cl, n in counts.most_common() if n >= 2][:2] or \
                [cl for cl, _ in counts.most_common(1)]
    return {
        "name": _find_name(text),
        "email": _find_email(text),
        "skills": skills,
        "interests": interests,
        "cgpa": _find_cgpa(text),
        "branch": _find_branch(text),
        "grad_year": _find_grad_year(text),
        "backlogs": _find_backlogs(text),
    }
