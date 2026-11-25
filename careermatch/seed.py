"""Populate the database with a demo fair (fictional companies, synthetic students)."""
import random
import sqlite3

from werkzeug.security import generate_password_hash

from .simulate import gen_student

FIRST = ["Aarav", "Diya", "Kabir", "Ananya", "Rohan", "Ishita", "Vihaan", "Meera", "Arjun", "Sanya",
         "Aditya", "Priya", "Karan", "Neha", "Yash", "Riya", "Dev", "Tanvi", "Nikhil", "Pooja",
         "Harsh", "Simran", "Manav", "Kavya", "Siddharth", "Aditi", "Raghav", "Nisha", "Varun", "Sneha"]
LAST = ["Sharma", "Verma", "Singh", "Gupta", "Yadav", "Mehta", "Kapoor", "Reddy", "Nair", "Joshi"]

COMPANIES = [
    # name, role, domain, required, preferred, min_cgpa, branches, max_backlogs, desks
    ("NimbusSoft", "Software Engineer", "software", "Python,Java,SQL,Git", "React,Docker", 7.0, "CSE,IT", 0, 3),
    ("BrightPath Web", "Frontend Developer", "software", "JavaScript,React,Git", "Node.js,UI/UX", 6.5, "CSE,IT,DES", 1, 2),
    ("QuantLeaf Analytics", "Data Analyst", "data", "Python,SQL,Data Analysis,Statistics", "Power BI,Pandas", 7.0, "CSE,IT,MBA", 1, 3),
    ("Neuron Labs", "ML Engineer", "data", "Python,Machine Learning,Deep Learning", "Pandas,Statistics", 7.5, "CSE,IT", 0, 2),
    ("StratoCloud", "Cloud Engineer", "cloud", "AWS,Linux,Docker", "Kubernetes,DevOps", 6.5, "CSE,IT,ECE", 1, 3),
    ("Helix Devices", "Embedded Engineer", "hardware", "Embedded C,Microcontrollers,PCB Design", "Verilog", 6.5, "ECE,EE", 1, 2),
    ("SiliconCrest", "VLSI Design Engineer", "hardware", "VLSI,Verilog,Embedded C", "PCB Design", 7.5, "ECE,EE", 0, 2),
    ("ForgeWorks Motors", "Design Engineer", "mechanical", "AutoCAD,SolidWorks,ANSYS", "Thermodynamics,CAD/CAM", 6.5, "ME", 2, 3),
    ("Ledgerline Finance", "Business Analyst", "business", "Excel,Finance,Communication", "Power BI,Project Management", 6.0, "MBA,CSE,IT", 2, 3),
    ("Pixelfield Studio", "Product Designer", "design", "UI/UX,Figma,Prototyping", "Photoshop,Graphic Design", 6.0, "DES,CSE,IT", 2, 2),
    ("OrbitOps", "DevOps Engineer", "cloud", "Linux,Docker,Kubernetes,DevOps", "AWS,Git", 7.0, "CSE,IT", 0, 2),
    ("Marketly", "Marketing Associate", "business", "Marketing,Communication,Excel", "Graphic Design", 6.0, "MBA,DES", 2, 2),
]


def seed(path, n_students=150, seed_value=7):
    rng = random.Random(seed_value)
    con = sqlite3.connect(path)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        con.close()
        return False
    hashes = {p: generate_password_hash(p) for p in ("admin123", "company123", "student123")}
    pw = hashes.__getitem__  # hash each demo password once
    con.execute("INSERT INTO users(username, password_hash, role) VALUES ('admin', ?, 'admin')", (pw("admin123"),))

    for (name, role, dom, req, pref, mc, br, mb, desks) in COMPANIES:
        cur = con.execute(
            "INSERT INTO companies(name, role_title, domain, description, required, preferred, min_cgpa,"
            " branches, max_backlogs, desks) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (name, role, dom, f"{name} is hiring a {role} for its {dom} team.", req, pref, mc, br, mb, desks))
        uname = name.split()[0].lower()
        con.execute("INSERT INTO users(username, password_hash, role, ref_id) VALUES (?,?, 'company', ?)",
                    (uname, pw("company123"), cur.lastrowid))

    used = set()
    for i in range(n_students):
        s = gen_student(i, rng)
        while True:
            nm = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if nm not in used:
                used.add(nm)
                break
        uname = "demo" if i == 0 else f"student{i}"
        if i == 0:  # a predictable demo profile
            s.update(skills={"Python", "SQL", "Git", "Java", "Data Analysis", "Statistics"},
                     interests=["software", "data"], branch="CSE", cgpa=8.1, backlogs=0)
        cur = con.execute(
            "INSERT INTO students(name, email, skills, interests, cgpa, branch, backlogs, grad_year, resume_url)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (nm, f"{uname}@example.edu", ",".join(sorted(s["skills"])), ",".join(s["interests"]),
             s["cgpa"], s["branch"], s["backlogs"], rng.choice([2026, 2027]), ""))
        con.execute("INSERT INTO users(username, password_hash, role, ref_id) VALUES (?,?, 'student', ?)",
                    (uname, pw("student123"), cur.lastrowid))
    con.commit()
    con.close()
    return True
