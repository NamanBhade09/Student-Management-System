import csv
import hmac
import io
import os
import calendar as cal
from datetime import datetime, date, time as dtime, timedelta, timezone
from functools import wraps

import pyodbc
from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, session, url_for)

from werkzeug.security import check_password_hash, generate_password_hash

from connection import get_db_connection

app = Flask(__name__)
app.secret_key = os.environ.get("SMS_SECRET_KEY", "change-this-secret-key")

IST = timezone(timedelta(hours=5, minutes=30))
LEAVE_TYPES = {"Sick Leave", "Casual Leave"}
ATT_STATUSES = {"Present", "Absent", "Late", "Half-day"}


# ---------------------------------------------------------------- helpers
def now_ist():
    return datetime.now(IST).replace(tzinfo=None)


def run(sql, params=(), fetch=None):
    """Run one statement. fetch: 'one' | 'all' | None. Returns rows or rowcount."""
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("Database is unavailable. Please try again later.")
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def run_insert(sql, params=()):
    """INSERT ... OUTPUT INSERTED.id and return the new id."""
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("Database is unavailable. Please try again later.")
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        new_id = cur.fetchone()[0]
        conn.commit()
        return new_id
    finally:
        conn.close()


def fmt_time(dt):
    return dt.strftime("%I:%M:%S %p").lower() if dt else "--:--:--"


def fmt_duration(start, end):
    if not start or not end:
        return "00:00:00"
    secs = max(int((end - start).total_seconds()), 0)
    return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


def login_required(role):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if session.get("role") != role:
                if request.path.startswith("/api/"):
                    return jsonify(success=False, message="Please sign in again."), 401
                return redirect(url_for("login_page"))
            return fn(*a, **kw)
        return wrapper
    return deco


def student(fn):
    return login_required("Student")(fn)


def admin(fn):
    return login_required("Admin")(fn)


@app.errorhandler(pyodbc.Error)
@app.errorhandler(RuntimeError)
def db_error(e):
    app.logger.error("DB error: %s", e)
    msg = "Database error. Please try again later."
    if request.path.startswith("/api/"):
        return jsonify(success=False, message=msg), 500
    return msg, 500


def today_attendance(student_id):
    return run(
        "SELECT TOP 1 clock_in_time, clock_out_time FROM Attendance "
        "WHERE student_id=? AND CAST(clock_in_time AS DATE)=? "
        "ORDER BY clock_in_time DESC",
        (student_id, now_ist().date()), "one")


# ---------------------------------------------------------------- auth
@app.route("/")
def login_page():
    role = session.get("role")
    if role == "Admin":
        return redirect(url_for("dashboard_admin"))
    if role == "Student":
        return redirect(url_for("dashboard_student"))
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify(success=False, message="Username and password are required.")
    row = run(
        "SELECT u.user_id, u.role, u.username, u.password_hash, s.student_id, s.firstname "
        "FROM users u LEFT JOIN Student s ON s.user_id = u.user_id "
        "WHERE u.username=?", (username,), "one")
    ok, upgrade = verify_pw(row.password_hash, password) if row else (False, False)
    if not ok:
        return jsonify(success=False, message="Invalid username or password.")
    if upgrade:  # legacy plain-text password: re-store it hashed
        run("UPDATE users SET password_hash=? WHERE user_id=?", (hash_pw(password), row.user_id))
    session.clear()
    session.update(user_id=row.user_id, role=row.role, username=row.username,
                   student_id=row.student_id, name=row.firstname or row.username)
    return jsonify(success=True, role=row.role)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ---------------------------------------------------------------- student pages
@app.route("/dashboard_student")
@student
def dashboard_student():
    sid = session["student_id"]
    counts = {r.status: r.n for r in run(
        "SELECT status, COUNT(*) AS n FROM Task WHERE student_id=? GROUP BY status",
        (sid,), "all")}
    completed = counts.get("completed", 0)
    remaining = counts.get("pending", 0) + counts.get("in_progress", 0)

    lv = run("SELECT COUNT(*) AS total, "
             "SUM(CASE WHEN status='Pending' THEN 1 ELSE 0 END) AS pending "
             "FROM LeaveRequest WHERE student_id=?", (sid,), "one")

    att = today_attendance(sid)
    if not att:
        att_status, att_sub, cin, cout, dur = "Not Started", "No clock-in yet", "--:--:--", "--:--:--", "00:00:00"
    elif att.clock_out_time is None:
        att_status = "In Progress"
        att_sub = f"Started at {fmt_time(att.clock_in_time)}"
        cin, cout, dur = fmt_time(att.clock_in_time), "--:--:--", "00:00:00"
    else:
        att_status = "Completed"
        att_sub = f"Worked {fmt_duration(att.clock_in_time, att.clock_out_time)}"
        cin, cout = fmt_time(att.clock_in_time), fmt_time(att.clock_out_time)
        dur = fmt_duration(att.clock_in_time, att.clock_out_time)

    holidays = [(h.name, h.holiday_date.strftime("%d %b %Y")) for h in run(
        "SELECT TOP 5 name, holiday_date FROM Holiday WHERE holiday_date>=? "
        "ORDER BY holiday_date", (now_ist().date(),), "all")]
    recent = run("SELECT TOP 5 title, due_date, status FROM Task WHERE student_id=? "
                 "ORDER BY created_at DESC", (sid,), "all")

    return render_template(
        "dashboard_student.html", username=session["name"],
        remaining_tasks=remaining, completed_tasks=completed,
        total_leaves=lv.total or 0, pending_leaves=lv.pending or 0,
        att_status=att_status, att_sub=att_sub, clock_in=cin, clock_out=cout,
        duration=dur, upcoming_holidays=holidays, recent_tasks=recent)


@app.route("/calendar")
@student
def calendar_page():
    rows = run("SELECT holiday_date, name FROM Holiday", fetch="all")
    return render_template("calendar.html",
                           holidays={r.holiday_date.isoformat(): r.name for r in rows})


@app.route("/leave")
@student
def leave_page():
    leaves = run("SELECT leave_type, start_date, end_date, status FROM LeaveRequest "
                 "WHERE student_id=? ORDER BY applied_on DESC", (session["student_id"],), "all")
    return render_template(
        "leave.html", leaves=leaves, total=len(leaves),
        pending=sum(1 for l in leaves if l.status == "Pending"),
        approved=sum(1 for l in leaves if l.status == "Approved"))


@app.route("/tasks")
@student
def tasks_page():
    tasks = run("SELECT task_id, title, due_date, status FROM Task WHERE student_id=? "
                "ORDER BY created_at DESC", (session["student_id"],), "all")
    return render_template("tasks.html", tasks=tasks)


def attendance_records(sid):
    rows = run("SELECT clock_in_time, clock_out_time FROM Attendance WHERE student_id=? "
               "ORDER BY clock_in_time DESC", (sid,), "all")
    return [{"date": r.clock_in_time, "clock_in_time": r.clock_in_time,
             "clock_out_time": r.clock_out_time,
             "working_hours": fmt_duration(r.clock_in_time, r.clock_out_time)} for r in rows]


@app.route("/attendance")
@student
def attendance_page():
    records = attendance_records(session["student_id"])
    total_secs = sum((r["clock_out_time"] - r["clock_in_time"]).total_seconds()
                     for r in records if r["clock_out_time"])
    today = now_ist().date()
    today_rec = next((r for r in records if r["date"].date() == today), None)
    return render_template(
        "attendance.html", records=records,
        days_recorded=len({r["date"].date() for r in records}),
        total_hours=f"{int(total_secs // 3600)}h {int(total_secs % 3600 // 60)}m",
        today_duration=today_rec["working_hours"] if today_rec else "00:00:00")


@app.route("/attendance/export")
@student
def attendance_export():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date", "Clock In (IST)", "Clock Out (IST)", "Duration"])
    for r in attendance_records(session["student_id"]):
        w.writerow([r["date"].strftime("%Y-%m-%d"), fmt_time(r["clock_in_time"]),
                    fmt_time(r["clock_out_time"]), r["working_hours"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=attendance.csv"})


# ---------------------------------------------------------------- student APIs
@app.route("/api/clock_in", methods=["POST"])
@student
def api_clock_in():
    sid = session["student_id"]
    if today_attendance(sid):
        return jsonify(success=False, message="You have already clocked in today.")
    now = now_ist()
    run("INSERT INTO Attendance (student_id, clock_in_time) VALUES (?, ?)", (sid, now))
    return jsonify(success=True, time=fmt_time(now))


@app.route("/api/clock_out", methods=["POST"])
@student
def api_clock_out():
    sid = session["student_id"]
    att = today_attendance(sid)
    if not att:
        return jsonify(success=False, message="Clock in first.")
    if att.clock_out_time:
        return jsonify(success=False, message="You have already clocked out today.")
    now = now_ist()
    run("UPDATE Attendance SET clock_out_time=? WHERE student_id=? AND clock_in_time=?",
        (now, sid, att.clock_in_time))
    return jsonify(success=True, time=fmt_time(now),
                   duration=fmt_duration(att.clock_in_time, now))


@app.route("/api/add_task", methods=["POST"])
@student
def api_add_task():
    title = ((request.get_json(silent=True) or {}).get("title") or "").strip()
    if not title:
        return jsonify(success=False, message="Task title is required.")
    if len(title) > 255:
        return jsonify(success=False, message="Title is too long (max 255).")
    due = now_ist().date()
    tid = run_insert("INSERT INTO Task (student_id, title, due_date) "
                     "OUTPUT INSERTED.task_id VALUES (?, ?, ?)",
                     (session["student_id"], title, due))
    return jsonify(success=True, task_id=tid, due_date=due.isoformat())


@app.route("/api/update_task", methods=["POST"])
@student
def api_update_task():
    d = request.get_json(silent=True) or {}
    if d.get("status") not in ("pending", "in_progress", "completed"):
        return jsonify(success=False, message="Invalid status.")
    n = run("UPDATE Task SET status=?, updated_at=SYSDATETIME() "
            "WHERE task_id=? AND student_id=?",
            (d["status"], d.get("task_id"), session["student_id"]))
    if not n:
        return jsonify(success=False, message="Task not found.")
    return jsonify(success=True)


@app.route("/api/add_leave", methods=["POST"])
@student
def api_add_leave():
    d = request.get_json(silent=True) or {}
    if d.get("leave_type") not in LEAVE_TYPES:
        return jsonify(success=False, message="Choose a valid leave type."), 400
    try:
        start = date.fromisoformat(d.get("start_date", ""))
        end = date.fromisoformat(d.get("end_date", ""))
    except ValueError:
        return jsonify(success=False, message="Enter valid dates."), 400
    if end < start:
        return jsonify(success=False, message="End date cannot be before start date."), 400
    if start < now_ist().date():
        return jsonify(success=False, message="Start date cannot be in the past."), 400
    run("INSERT INTO LeaveRequest (student_id, start_date, end_date, leave_type, reason) "
        "VALUES (?, ?, ?, ?, ?)",
        (session["student_id"], start, end, d["leave_type"], (d.get("reason") or "").strip()))
    return jsonify(success=True)


# ---------------------------------------------------------------- admin
@app.route("/dashboard_admin")
@admin
def dashboard_admin():
    return render_template("dashboard_admin.html")


@app.route("/api/admin/summary")
@admin
def admin_summary():
    r = run("SELECT "
            "(SELECT COUNT(*) FROM Student) AS students, "
            "(SELECT COUNT(DISTINCT student_id) FROM Attendance "
            " WHERE CAST(clock_in_time AS DATE)=?) AS present, "
            "(SELECT COUNT(*) FROM LeaveRequest WHERE status='Pending') AS leaves, "
            "(SELECT COUNT(*) FROM Task WHERE status<>'completed') AS tasks",
            (now_ist().date(),), "one")
    return jsonify(students=r.students, present=r.present, leaves=r.leaves, tasks=r.tasks)


@app.route("/api/admin/students")
@admin
def admin_students():
    rows = run("SELECT student_id, firstname + ' ' + lastname AS name FROM Student "
               "ORDER BY firstname", fetch="all")
    return jsonify([{"id": r.student_id, "name": r.name} for r in rows])


@app.route("/api/admin/leaves")
@admin
def admin_leaves():
    rows = run("SELECT l.leave_id, s.firstname + ' ' + s.lastname AS name, l.leave_type, "
               "l.start_date, l.end_date, l.reason, l.status FROM LeaveRequest l "
               "JOIN Student s ON s.student_id=l.student_id ORDER BY l.applied_on DESC",
               fetch="all")
    return jsonify([{"id": r.leave_id, "student": r.name, "type": r.leave_type,
                     "start": r.start_date.isoformat(), "end": r.end_date.isoformat(),
                     "reason": r.reason or "", "status": r.status} for r in rows])


@app.route("/api/admin/leaves/<int:leave_id>", methods=["POST"])
@admin
def admin_decide_leave(leave_id):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("Approved", "Rejected"):
        return jsonify(success=False, message="Invalid status."), 400
    run("UPDATE LeaveRequest SET status=? WHERE leave_id=?", (status, leave_id))
    return jsonify(success=True)


@app.route("/api/admin/attendance", methods=["GET", "POST"])
@admin
def admin_attendance():
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        try:
            day = date.fromisoformat(d.get("date", ""))
            sid = int(d.get("student_id"))
        except (ValueError, TypeError):
            return jsonify(success=False, message="Invalid data."), 400
        status = d.get("status")
        if not status:
            run("DELETE FROM AttendanceStatus WHERE student_id=? AND attendance_date=?", (sid, day))
        elif status in ATT_STATUSES:
            n = run("UPDATE AttendanceStatus SET status=? WHERE student_id=? AND attendance_date=?",
                    (status, sid, day))
            if not n:
                run("INSERT INTO AttendanceStatus (student_id, attendance_date, status) "
                    "VALUES (?, ?, ?)", (sid, day, status))
        else:
            return jsonify(success=False, message="Invalid status."), 400
        return jsonify(success=True)

    month = request.args.get("month") or now_ist().strftime("%Y-%m")
    try:
        y, m = map(int, month.split("-"))
        days = cal.monthrange(y, m)[1]
    except ValueError:
        return jsonify(success=False, message="Invalid month."), 400
    rows = run("SELECT student_id, attendance_date, status FROM AttendanceStatus "
               "WHERE attendance_date BETWEEN ? AND ?",
               (date(y, m, 1), date(y, m, days)), "all")
    records = {}
    for r in rows:
        records.setdefault(str(r.student_id), {})[str(r.attendance_date.day)] = r.status
    return jsonify(days=days, year=y, month=m, records=records)


@app.route("/api/admin/tasks", methods=["GET", "POST"])
@admin
def admin_tasks():
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        title = (d.get("title") or "").strip()
        try:
            due = date.fromisoformat(d.get("due_date", ""))
            sid = int(d.get("student_id"))
        except (ValueError, TypeError):
            return jsonify(success=False, message="Choose a student and a valid due date."), 400
        if not title or len(title) > 255:
            return jsonify(success=False, message="Enter a title (max 255 characters)."), 400
        run("INSERT INTO Task (student_id, title, description, due_date) VALUES (?, ?, ?, ?)",
            (sid, title, (d.get("description") or "").strip() or None, due))
        return jsonify(success=True)
    rows = run("SELECT t.task_id, t.title, t.due_date, t.status, "
               "s.firstname + ' ' + s.lastname AS name FROM Task t "
               "JOIN Student s ON s.student_id=t.student_id ORDER BY t.due_date DESC",
               fetch="all")
    return jsonify([{"id": r.task_id, "title": r.title, "student": r.name,
                     "due": r.due_date.isoformat(), "status": r.status} for r in rows])


@app.route("/api/admin/tasks/<int:task_id>/delete", methods=["POST"])
@admin
def admin_delete_task(task_id):
    run("DELETE FROM Task WHERE task_id=?", (task_id,))
    return jsonify(success=True)


@app.route("/api/admin/holidays", methods=["GET", "POST", "DELETE"])
@admin
def admin_holidays():
    if request.method == "GET":
        rows = run("SELECT holiday_date, name FROM Holiday", fetch="all")
        return jsonify({r.holiday_date.isoformat(): r.name for r in rows})
    d = request.get_json(silent=True) or {}
    try:
        day = date.fromisoformat(d.get("date", ""))
    except ValueError:
        return jsonify(success=False, message="Invalid date."), 400
    if request.method == "DELETE":
        run("DELETE FROM Holiday WHERE holiday_date=?", (day,))
    else:
        name = (d.get("name") or "").strip()
        if not name or len(name) > 100:
            return jsonify(success=False, message="Enter a holiday name (max 100)."), 400
        if not run("UPDATE Holiday SET name=? WHERE holiday_date=?", (name, day)):
            run("INSERT INTO Holiday (holiday_date, name) VALUES (?, ?)", (day, name))
    return jsonify(success=True)


# ================================================================ SECURITY
def hash_pw(p):
    return generate_password_hash(p, method="pbkdf2:sha256").encode("utf-8")


def verify_pw(stored, p):
    """Returns (ok, needs_upgrade). Legacy plain-text rows are accepted once, then re-hashed."""
    s = bytes(stored)
    if s.startswith((b"pbkdf2:", b"scrypt:")):
        return check_password_hash(s.decode("utf-8"), p), False
    ok = hmac.compare_digest(s, p.encode("utf-8"))
    return ok, ok


def password_problem(p):
    if len(p) < 8:
        return "Password must be at least 8 characters."
    if len(p) > 128:
        return "Password is too long (max 128)."
    return None


def any_user(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("role"):
            return jsonify(success=False, message="Please sign in again."), 401
        return fn(*a, **kw)
    return wrapper


def run_tx(fn):
    """Run fn(cursor) in one transaction (commit on success, rollback on error)."""
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("Database is unavailable. Please try again later.")
    try:
        result = fn(conn.cursor())
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.route("/api/change_password", methods=["POST"])
@any_user
def api_change_password():
    d = request.get_json(silent=True) or {}
    current = d.get("current_password") or ""
    new = d.get("new_password") or ""
    row = run("SELECT password_hash FROM users WHERE user_id=?", (session["user_id"],), "one")
    if not row or not verify_pw(row.password_hash, current)[0]:
        return jsonify(success=False, message="Current password is incorrect."), 400
    if new != (d.get("confirm_password") or ""):
        return jsonify(success=False, message="New passwords do not match."), 400
    if new == current:
        return jsonify(success=False, message="New password must be different."), 400
    problem = password_problem(new)
    if problem:
        return jsonify(success=False, message=problem), 400
    run("UPDATE users SET password_hash=? WHERE user_id=?", (hash_pw(new), session["user_id"]))
    return jsonify(success=True)


@app.route("/security")
@student
def security_page():
    return render_template("security.html")


# ================================================================ PERFORMANCE
def grade_for(score):
    for cutoff, g in ((90, "A"), (75, "B"), (60, "C"), (40, "D")):
        if score >= cutoff:
            return g
    return "F"


def compute_performance(sid):
    """Last-30-day attendance (weekdays, minus holidays and approved leave) + task completion."""
    today = now_ist().date()
    start = today - timedelta(days=29)
    logins = run("SELECT clock_in_time FROM Attendance WHERE student_id=? "
                 "AND CAST(clock_in_time AS DATE) BETWEEN ? AND ?", (sid, start, today), "all")
    att_dates = {r.clock_in_time.date() for r in logins}
    holidays = {h.holiday_date for h in run(
        "SELECT holiday_date FROM Holiday WHERE holiday_date BETWEEN ? AND ?", (start, today), "all")}
    leave_rows = run("SELECT start_date, end_date FROM LeaveRequest WHERE student_id=? "
                     "AND status='Approved'", (sid,), "all")
    leave_days = set()
    for l in leave_rows:
        d = l.start_date
        while d <= l.end_date:
            leave_days.add(d)
            d += timedelta(days=1)

    expected = []
    for i in range(30):
        d = start + timedelta(days=i)
        if d.weekday() >= 5 or d in holidays or d in leave_days:
            continue
        if d == today and d not in att_dates:      # today isn't over yet
            continue
        expected.append(d)
    attended = sum(1 for d in expected if d in att_dates)
    att_pct = round(attended / len(expected) * 100, 2) if expected else 100.0
    absent = len(expected) - attended

    counts = {r.status: r.n for r in run(
        "SELECT status, COUNT(*) AS n FROM Task WHERE student_id=? GROUP BY status", (sid,), "all")}
    done = counts.get("completed", 0)
    total_tasks = sum(counts.values())
    remaining = total_tasks - done
    task_pct = round(done / total_tasks * 100, 2) if total_tasks else None
    overall = att_pct if task_pct is None else round(0.6 * att_pct + 0.4 * task_pct, 2)
    grade = grade_for(overall)

    avg_login = None
    if logins:
        secs = sum(r.clock_in_time.hour * 3600 + r.clock_in_time.minute * 60 + r.clock_in_time.second
                   for r in logins) // len(logins)
        avg_login = dtime(secs // 3600, secs % 3600 // 60, secs % 60)
    total_leaves = len(leave_rows)

    vals = (overall, grade, att_pct, avg_login, done, remaining, total_leaves, absent)
    n = run("UPDATE Performance SET overall_percentage=?, grade=?, total_attendance_percentage=?, "
            "avg_login_time=?, total_tasks_completed=?, remaining_tasks=?, total_leaves=?, "
            "absent_without_leave=? WHERE student_id=?", vals + (sid,))
    if not n:
        run("INSERT INTO Performance (overall_percentage, grade, total_attendance_percentage, "
            "avg_login_time, total_tasks_completed, remaining_tasks, total_leaves, "
            "absent_without_leave, student_id) VALUES (?,?,?,?,?,?,?,?,?)", vals + (sid,))
    return {"overall": overall, "grade": grade, "attendance_pct": att_pct, "task_pct": task_pct,
            "completed": done, "remaining": remaining, "leaves": total_leaves, "absent": absent,
            "expected": len(expected), "attended": attended,
            "avg_login": avg_login.strftime("%I:%M %p").lower() if avg_login else "—"}


@app.route("/performance")
@student
def performance_page():
    return render_template("performance.html", p=compute_performance(session["student_id"]))


# ================================================================ TIMETABLE
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@app.route("/timetable")
@student
def timetable_page():
    rows = run("SELECT timetable_id, day_of_week, time_slots FROM TimeTable "
               "WHERE student_id=? ORDER BY time_slots", (session["student_id"],), "all")
    grouped = [(d, [r for r in rows if r.day_of_week == d]) for d in DAYS]
    return render_template("timetable.html", grouped=grouped, days=DAYS,
                           today=now_ist().strftime("%A"))


@app.route("/api/timetable/add", methods=["POST"])
@student
def api_timetable_add():
    d = request.get_json(silent=True) or {}
    slot = (d.get("time_slots") or "").strip()
    if d.get("day_of_week") not in DAYS:
        return jsonify(success=False, message="Choose a valid day."), 400
    if not slot or len(slot) > 255:
        return jsonify(success=False, message="Enter a time slot (max 255 characters)."), 400
    run("INSERT INTO TimeTable (student_id, day_of_week, time_slots) VALUES (?, ?, ?)",
        (session["student_id"], d["day_of_week"], slot))
    return jsonify(success=True)


@app.route("/api/timetable/delete", methods=["POST"])
@student
def api_timetable_delete():
    tid = (request.get_json(silent=True) or {}).get("timetable_id")
    n = run("DELETE FROM TimeTable WHERE timetable_id=? AND student_id=?",
            (tid, session["student_id"]))
    if not n:
        return jsonify(success=False, message="Entry not found."), 404
    return jsonify(success=True)


# ================================================================ ADMIN: STUDENTS
def clean_student(d, creating):
    """Validate student form data. Returns (values_dict, error_message)."""
    v = {k: (d.get(k) or "").strip() for k in
         ("username", "firstname", "lastname", "email", "mobile_no", "gender", "dob", "city")}
    password = d.get("password") or ""
    if creating and not (v["username"] and 3 <= len(v["username"]) <= 100):
        return None, "Username must be 3-100 characters."
    for k, label, mx in (("firstname", "First name", 50), ("lastname", "Last name", 50),
                         ("city", "City", 50)):
        if not v[k] or len(v[k]) > mx:
            return None, f"{label} is required (max {mx} characters)."
    if "@" not in v["email"] or len(v["email"]) > 100:
        return None, "Enter a valid email address."
    if v["mobile_no"] and not (v["mobile_no"].isdigit() and 7 <= len(v["mobile_no"]) <= 15):
        return None, "Mobile number must be 7-15 digits."
    if v["gender"] not in ("", "Male", "Female", "Other"):
        return None, "Invalid gender."
    if v["dob"]:
        try:
            v["dob"] = date.fromisoformat(v["dob"])
        except ValueError:
            return None, "Invalid date of birth."
    else:
        v["dob"] = None
    if creating or password:
        problem = password_problem(password)
        if problem:
            return None, problem
    v["password"] = password
    return v, None


@app.route("/api/admin/student-list")
@admin
def admin_student_list():
    rows = run("SELECT s.student_id, u.username, s.firstname, s.lastname, s.email, s.mobile_no, "
               "s.gender, s.dob, s.city FROM Student s JOIN users u ON u.user_id=s.user_id "
               "ORDER BY s.firstname, s.lastname", fetch="all")
    return jsonify([{"id": r.student_id, "username": r.username, "firstname": r.firstname,
                     "lastname": r.lastname, "email": r.email, "mobile_no": r.mobile_no or "",
                     "gender": r.gender or "", "dob": r.dob.isoformat() if r.dob else "",
                     "city": r.city} for r in rows])


@app.route("/api/admin/student-list", methods=["POST"])
@admin
def admin_student_create():
    v, err = clean_student(request.get_json(silent=True) or {}, creating=True)
    if err:
        return jsonify(success=False, message=err), 400

    def work(cur):
        cur.execute("INSERT INTO users (username, password_hash, role) "
                    "OUTPUT INSERTED.user_id VALUES (?, ?, 'Student')",
                    (v["username"], hash_pw(v["password"])))
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO Student (user_id, firstname, lastname, email, mobile_no, gender, dob, city) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (uid, v["firstname"], v["lastname"], v["email"], v["mobile_no"] or None,
                     v["gender"] or None, v["dob"], v["city"]))
    try:
        run_tx(work)
    except pyodbc.IntegrityError:
        return jsonify(success=False, message="That username or email already exists."), 400
    return jsonify(success=True)

@app.route("/student_profile")
@student
def student_profile():
    # Fetch the student's details using your custom run() helper
    student = run("""
        SELECT s.student_id, s.firstname, s.lastname, s.email, s.mobile_no, 
               s.gender, s.dob, s.city, u.username
        FROM Student s 
        INNER JOIN users u ON s.user_id = u.user_id 
        WHERE s.student_id = ?
    """, (session["student_id"],), "one")
    
    if not student:
        return "Profile not found", 404
        
    return render_template("student_profile.html", student=student, username=session["name"])


@app.route("/api/admin/student-list/<int:sid>", methods=["PUT"])
@admin
def admin_student_update(sid):
    v, err = clean_student(request.get_json(silent=True) or {}, creating=False)
    if err:
        return jsonify(success=False, message=err), 400

    def work(cur):
        cur.execute("UPDATE Student SET firstname=?, lastname=?, email=?, mobile_no=?, gender=?, "
                    "dob=?, city=? WHERE student_id=?",
                    (v["firstname"], v["lastname"], v["email"], v["mobile_no"] or None,
                     v["gender"] or None, v["dob"], v["city"], sid))
        if cur.rowcount == 0:
            return False
        if v["password"]:
            cur.execute("UPDATE users SET password_hash=? WHERE user_id="
                        "(SELECT user_id FROM Student WHERE student_id=?)",
                        (hash_pw(v["password"]), sid))
        return True
    try:
        found = run_tx(work)
    except pyodbc.IntegrityError:
        return jsonify(success=False, message="That email already exists."), 400
    if not found:
        return jsonify(success=False, message="Student not found."), 404
    return jsonify(success=True)


@app.route("/api/admin/student-list/<int:sid>", methods=["DELETE"])
@admin
def admin_student_delete(sid):
    # Deleting the login row cascades to the student and all of their records.
    n = run("DELETE FROM users WHERE user_id=(SELECT user_id FROM Student WHERE student_id=?)", (sid,))
    if not n:
        return jsonify(success=False, message="Student not found."), 404
    return jsonify(success=True)


if __name__ == "__main__":
    app.run(debug=True)