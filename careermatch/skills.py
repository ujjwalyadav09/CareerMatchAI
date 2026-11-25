"""Controlled skill vocabulary and normalization (paper Sec. III-C, VII).

Seven skill clusters over a 40-skill vocabulary. Free-text aliases
(e.g. "JS", "js", "Java Script") are mapped to one canonical tag.
"""

CLUSTERS = {
    "software": ["Python", "Java", "C++", "JavaScript", "React", "Node.js", "SQL", "Git"],
    "data": ["Machine Learning", "Data Analysis", "Statistics", "Pandas", "Deep Learning", "Power BI"],
    "cloud": ["AWS", "Azure", "Docker", "Kubernetes", "Linux", "DevOps"],
    "hardware": ["Embedded C", "VLSI", "PCB Design", "Microcontrollers", "Verilog"],
    "mechanical": ["AutoCAD", "SolidWorks", "CAD/CAM", "Thermodynamics", "ANSYS"],
    "business": ["Excel", "Marketing", "Finance", "Communication", "Project Management"],
    "design": ["UI/UX", "Figma", "Photoshop", "Graphic Design", "Prototyping"],
}

VOCABULARY = [s for skills in CLUSTERS.values() for s in skills]
assert len(VOCABULARY) == 40, len(VOCABULARY)

DOMAINS = list(CLUSTERS.keys())

BRANCHES = ["CSE", "IT", "ECE", "EE", "ME", "MBA", "DES"]

_ALIASES = {
    "js": "JavaScript", "java script": "JavaScript", "javascript": "JavaScript",
    "reactjs": "React", "react.js": "React", "node": "Node.js", "nodejs": "Node.js",
    "cpp": "C++", "c plus plus": "C++", "py": "Python", "python3": "Python",
    "ml": "Machine Learning", "dl": "Deep Learning", "mysql": "SQL", "postgresql": "SQL",
    "k8s": "Kubernetes", "amazon web services": "AWS", "ms excel": "Excel",
    "ux": "UI/UX", "ui": "UI/UX", "ui ux": "UI/UX", "powerbi": "Power BI",
    "data analytics": "Data Analysis", "stats": "Statistics", "cad": "CAD/CAM",
    "embedded": "Embedded C", "pm": "Project Management",
}
_CANON = {s.lower(): s for s in VOCABULARY}


def normalize_skill(raw: str):
    """Map a free-text skill to its canonical tag, or None if unknown."""
    key = " ".join(raw.strip().lower().replace("_", " ").split())
    if not key:
        return None
    return _CANON.get(key) or _ALIASES.get(key)


def normalize_skills(raw) -> list:
    """Normalize a comma string or iterable of skills; drops unknowns and duplicates."""
    items = raw.split(",") if isinstance(raw, str) else raw
    out = []
    for item in items:
        s = normalize_skill(item)
        if s and s not in out:
            out.append(s)
    return out


def unknown_skills(raw) -> list:
    items = raw.split(",") if isinstance(raw, str) else raw
    return [i.strip() for i in items if i.strip() and not normalize_skill(i)]
