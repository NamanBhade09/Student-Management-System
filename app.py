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


# ---------------------------------------------------------------- helpers
def now_ist():
    return datetime.now(IST).replace(tzinfo=None)


def run(sql, params=(), fetch=None):
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
        "SELECT TOP 1 attendance_id, clock_in_time, clock_out_time FROM Attendance "
        "WHERE student_id=? AND CAST(clock_in_time AS DATE)=? "
        "ORDER BY clock_in_time DESC",
        (student_id, now_ist().date()), "one")


def ensure_attendance_schedule_table():
    run("""
        IF OBJECT_ID(N'dbo.StudentAttendanceSchedule', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.StudentAttendanceSchedule (
                student_id INT NOT NULL PRIMARY KEY,
                start_time TIME(0) NOT NULL,
                end_time TIME(0) NOT NULL,
                CONSTRAINT FK_StudentAttendanceSchedule_Student
                    FOREIGN KEY (student_id) REFERENCES dbo.Student(student_id)
                    ON DELETE CASCADE
            )
        END
    """)


def active_attendance_for_day(day):
    rows = run("""
        SELECT s.student_id, s.firstname + ' ' + s.lastname AS name, a.clock_in_time
        FROM Attendance a
        JOIN Student s ON s.student_id=a.student_id
        WHERE CAST(a.clock_in_time AS DATE)=? AND a.clock_out_time IS NULL
        ORDER BY a.clock_in_time
    """, (day,), "all")
    return [{
        "id": row.student_id,
        "name": row.name,
        "clockIn": fmt_time(row.clock_in_time),
    } for row in rows]


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
    if upgrade:
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
    today_date = now_ist().date()
    
    counts = {r.status: r.n for r in run(
        "SELECT status, COUNT(*) AS n FROM Task WHERE student_id=? GROUP BY status",
        (sid,), "all")}
    completed = counts.get("completed", 0)
    remaining = counts.get("pending", 0) + counts.get("in_progress", 0) + counts.get("pending_approval", 0)
    
    overdue_row = run("SELECT COUNT(*) AS n FROM Task WHERE student_id=? AND status NOT IN ('completed', 'pending_approval') AND due_date < ?", 
                      (sid, today_date), "one")
    overdue = overdue_row.n if overdue_row else 0

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

    start_of_week = today_date - timedelta(days=today_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    
    week_att = run(
        "SELECT clock_in_time, clock_out_time FROM Attendance WHERE student_id=? AND CAST(clock_in_time AS DATE) BETWEEN ? AND ?",
        (sid, start_of_week, end_of_week), "all"
    )
    
    weekly_totals = [0] * 7
    total_week_secs = 0
    for r in week_att:
        if r.clock_in_time and r.clock_out_time:
            day_idx = r.clock_in_time.weekday()
            secs = (r.clock_out_time - r.clock_in_time).total_seconds()
            weekly_totals[day_idx] += secs
            total_week_secs += secs
            
    week_h = int(total_week_secs // 3600)
    week_m = int((total_week_secs % 3600) // 60)
    week_duration_str = f"{week_h}h {week_m:02d}m"
    week_progress_pct = min(100, int((total_week_secs / 144000) * 100))

    month_start = today_date.replace(day=1)
    present_days = run("SELECT COUNT(DISTINCT CAST(clock_in_time AS DATE)) AS n FROM Attendance WHERE student_id=? AND CAST(clock_in_time AS DATE) >= ?", (sid, month_start), "one").n
    holidays = run("SELECT TOP 3 name, holiday_date FROM Holiday WHERE holiday_date>=? ORDER BY holiday_date", (today_date,), "all")
    recent = run("SELECT TOP 5 title, due_date, status FROM Task WHERE student_id=? ORDER BY created_at DESC", (sid,), "all")

    return render_template(
        "dashboard_student.html", username=session["name"], student_id=sid,
        remaining_tasks=remaining, completed_tasks=completed, overdue_tasks=overdue,
        total_leaves=lv.total or 0, pending_leaves=lv.pending or 0,
        att_status=att_status, att_sub=att_sub, clock_in=cin, clock_out=cout,
        duration=dur, upcoming_holidays=holidays, recent_tasks=recent,
        present_days=present_days,
        weekly_totals=weekly_totals, week_duration_str=week_duration_str, 
        week_progress_pct=week_progress_pct, today_weekday=today_date.weekday(),
        today_date=today_date
    )


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
    return render_template("tasks.html")


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


@app.route("/student_profile")
@student
def student_profile():
    student = run("""
        SELECT s.student_id, s.firstname, s.lastname, s.email, s.mobile_no,
               s.gender, s.dob, s.city, u.username
        FROM Student s
        INNER JOIN users u ON s.user_id = u.user_id
        WHERE s.student_id = ?
    """, (session["student_id"],), "one")

    if not student:
        return "Profile not found", 404

    p = compute_performance(session["student_id"])

    return render_template("student_profile.html",
                           student=student, p=p, username=session["name"])


# ---------------------------------------------------------------- student APIs
@app.route("/api/clock_in", methods=["POST"])
@student
def api_clock_in():
    sid = session["student_id"]
    if today_attendance(sid):
        return jsonify(success=False, message="You have already clocked in today.")
    now = now_ist()
    ensure_attendance_schedule_table()
    schedule = run(
        "SELECT start_time FROM StudentAttendanceSchedule WHERE student_id=?",
        (sid,), "one")
    if schedule and now.time() < schedule.start_time:
        return jsonify(
            success=False,
            message=f"Clock-in opens at {schedule.start_time.strftime('%I:%M %p').lower()}.")
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
    run("UPDATE Attendance SET clock_out_time=? WHERE attendance_id=?", (now, att.attendance_id))
    return jsonify(success=True, time=fmt_time(now),
                   duration=fmt_duration(att.clock_in_time, now))


@app.route("/api/attendance_status", methods=["GET"])
@student
def api_attendance_status():
    att = today_attendance(session["student_id"])
    if not att:
        return jsonify(status="Not Started", clock_in="--:--:--", duration="00:00:00")
    if not att.clock_out_time:
        return jsonify(status="In Progress", clock_in=fmt_time(att.clock_in_time), duration="00:00:00")
    return jsonify(
        status="Completed", 
        clock_in=fmt_time(att.clock_in_time), 
        duration=fmt_duration(att.clock_in_time, att.clock_out_time)
    )


@app.route("/api/update_profile", methods=["POST"])
@student
def api_update_profile():
    d = request.get_json(silent=True) or {}
    sid = session["student_id"]

    firstname = (d.get("firstname") or "").strip()
    lastname = (d.get("lastname") or "").strip()
    email = (d.get("email") or "").strip()
    mobile_no = (d.get("mobile_no") or "").strip()
    gender = (d.get("gender") or "").strip()
    dob_str = (d.get("dob") or "").strip()
    city = (d.get("city") or "").strip()

    if not firstname or not lastname or not email or not city:
        return jsonify(success=False, message="Name, email, and city are required."), 400

    if "@" not in email:
        return jsonify(success=False, message="Invalid email address."), 400

    try:
        dob = date.fromisoformat(dob_str) if dob_str else None
    except ValueError:
        return jsonify(success=False, message="Invalid date of birth."), 400

    try:
        existing = run("SELECT student_id FROM Student WHERE email=? AND student_id<>?", (email, sid), "one")
        if existing:
            return jsonify(success=False, message="That email address is already in use by another account."), 400
            
        run("""
            UPDATE Student 
            SET firstname=?, lastname=?, email=?, mobile_no=?, gender=?, dob=?, city=?
            WHERE student_id=?
        """, (firstname, lastname, email, mobile_no or None, gender or None, dob, city, sid))
        
        run("UPDATE users SET username=? WHERE user_id=(SELECT user_id FROM Student WHERE student_id=?)", (email, sid))
        
        session["name"] = firstname
        return jsonify(success=True)
    except pyodbc.IntegrityError:
        return jsonify(success=False, message="Database error updating profile."), 400


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


# ================================================================ TASKS API
@app.route("/api/students", methods=["GET"])
@student
def api_students_list():
    rows = run(
        "SELECT firstname + ' ' + lastname AS name FROM Student ORDER BY firstname, lastname",
        fetch="all")
    return jsonify([{"name": r.name} for r in rows])


@app.route("/api/tasks", methods=["GET"])
@student
def api_tasks_list():
    sid = session["student_id"]
    rows = run("""
        SELECT task_id, title, status, due_date, created_at, updated_at, 
               assigned_to, estimated_hours, hours_logged 
        FROM Task WHERE student_id=? ORDER BY created_at DESC
    """, (sid,), "all")
    
    result = []
    for r in rows:
        result.append({
            "id": r.task_id,
            "code": f"TASK-{r.task_id:03d}",
            "title": r.title,
            "status": r.status,
            "due": r.due_date.isoformat() if r.due_date else "",
            "start": r.created_at.strftime("%Y-%m-%d") if r.created_at else "",
            "completedOn": r.updated_at.strftime("%Y-%m-%d") if r.status == 'completed' and r.updated_at else "",
            "assignee": r.assigned_to or "",
            "estimate": float(r.estimated_hours) if r.estimated_hours else 0,
            "hoursLogged": float(r.hours_logged) if r.hours_logged else 0
        })
    return jsonify(result)


@app.route("/api/tasks", methods=["POST"])
@student
def api_tasks_create():
    d = request.get_json(silent=True) or {}
    title = (d.get("title") or "").strip()
    if not title:
        return jsonify(success=False, message="Task title is required."), 400

    sid = session["student_id"]
    run("""
        INSERT INTO Task (student_id, title, due_date, status, assigned_to) 
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        sid, 
        title, 
        d.get("due") or now_ist().date(), 
        d.get("assignee")
    ))
    return jsonify(success=True)


@app.route("/api/tasks/<int:tid>", methods=["PUT"])
@student
def api_tasks_update(tid):
    d = request.get_json(silent=True) or {}
    sid = session["student_id"]

    n = run("""
        UPDATE Task 
        SET title=?, due_date=?, assigned_to=?
        WHERE task_id=? AND student_id=?
    """, (
        d.get("title"), d.get("due"), d.get("assignee"), tid, sid
    ))
    
    if not n:
        return jsonify(success=False, message="Task not found."), 404
    return jsonify(success=True)


@app.route("/api/tasks/<int:tid>/log_time", methods=["POST"])
@student
def api_tasks_log_time(tid):
    d = request.get_json(silent=True) or {}
    hours = float(d.get("hours", 0))
    if hours <= 0:
        return jsonify(success=False, message="Invalid hours."), 400

    # Log time AND change status to pending_approval
    n = run("""
        UPDATE Task 
        SET hours_logged = ISNULL(hours_logged, 0) + ?, 
            status = 'pending_approval',
            updated_at = GETDATE()
        WHERE task_id=? AND student_id=?
    """, (hours, tid, session["student_id"]))
    
    if not n:
        return jsonify(success=False, message="Task not found."), 404
    return jsonify(success=True)


# ---------------------------------------------------------------- admin
@app.route("/dashboard_admin")
@admin
def dashboard_admin():
    return render_template("dashboard_admin.html")


@app.route("/api/admin/summary")
@admin
def admin_summary():
    today = now_ist().date()
    r = run("SELECT "
            "(SELECT COUNT(*) FROM Student) AS students, "
            "(SELECT COUNT(DISTINCT student_id) FROM Attendance "
            " WHERE CAST(clock_in_time AS DATE)=?) AS present, "
            "(SELECT COUNT(*) FROM LeaveRequest WHERE status='Pending') AS leaves, "
            "(SELECT COUNT(*) FROM Task WHERE status NOT IN ('completed', 'pending_approval')) AS tasks",
            (today,), "one")
    return jsonify(students=r.students, present=r.present, leaves=r.leaves,
                   tasks=r.tasks, activeStudents=active_attendance_for_day(today))


@app.route("/api/admin/active-attendance")
@admin
def admin_active_attendance():
    return jsonify(activeStudents=active_attendance_for_day(now_ist().date()))


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


@app.route("/api/admin/attendance", methods=["GET"])
@admin
def admin_attendance():
    month = request.args.get("month") or now_ist().strftime("%Y-%m")
    try:
        y, m = map(int, month.split("-"))
        days = cal.monthrange(y, m)[1]
    except ValueError:
        return jsonify(success=False, message="Invalid month."), 400

    ensure_attendance_schedule_table()
    start_date, end_date = date(y, m, 1), date(y, m, days)
    status_rows = run(
        "SELECT student_id, attendance_date, status FROM AttendanceStatus "
        "WHERE attendance_date BETWEEN ? AND ?", (start_date, end_date), "all")
    records = {}
    for r in status_rows:
        records.setdefault(str(r.student_id), {})[str(r.attendance_date.day)] = r.status
    attendance_rows = run("""
        SELECT a.student_id, a.clock_in_time, a.clock_out_time,
               s.start_time, s.end_time
        FROM Attendance a
        LEFT JOIN StudentAttendanceSchedule s ON s.student_id=a.student_id
        WHERE CAST(a.clock_in_time AS DATE) BETWEEN ? AND ?
        ORDER BY a.clock_in_time DESC
    """, (start_date, end_date), "all")
    clock_times = {}
    for r in attendance_rows:
        attendance_day = r.clock_in_time.date()
        student_key = str(r.student_id)
        day_key = str(attendance_day.day)
        student_times = clock_times.setdefault(student_key, {})
        if day_key in student_times:
            continue

        clock_in = r.clock_in_time.time()
        if r.end_time and r.clock_out_time and r.clock_out_time.time() < r.end_time:
            automatic_status = "Half-day"
        elif r.start_time and clock_in > r.start_time:
            automatic_status = "Late"
        else:
            automatic_status = "Present"

        student_times[day_key] = {
            "clockIn": fmt_time(r.clock_in_time),
            "clockOut": fmt_time(r.clock_out_time) if r.clock_out_time else "",
        }
        records.setdefault(student_key, {}).setdefault(day_key, automatic_status)

    schedules = run(
        "SELECT student_id, start_time, end_time FROM StudentAttendanceSchedule",
        fetch="all")
    return jsonify(
        days=days, year=y, month=m, records=records, clockTimes=clock_times,
        schedules=[{
            "studentId": r.student_id,
            "startTime": r.start_time.strftime("%H:%M"),
            "endTime": r.end_time.strftime("%H:%M"),
        } for r in schedules])


@app.route("/api/admin/attendance/schedules", methods=["POST"])
@admin
def admin_attendance_schedule():
    d = request.get_json(silent=True) or {}
    try:
        sid = int(d.get("student_id"))
        start_time = dtime.fromisoformat(d.get("start_time", ""))
        end_time = dtime.fromisoformat(d.get("end_time", ""))
    except (ValueError, TypeError):
        return jsonify(success=False, message="Choose a student and valid schedule times."), 400
    if start_time >= end_time:
        return jsonify(success=False, message="End time must be after start time."), 400

    ensure_attendance_schedule_table()
    if not run("SELECT student_id FROM Student WHERE student_id=?", (sid,), "one"):
        return jsonify(success=False, message="Student not found."), 404

    updated = run(
        "UPDATE StudentAttendanceSchedule SET start_time=?, end_time=? WHERE student_id=?",
        (start_time, end_time, sid))
    if not updated:
        run(
            "INSERT INTO StudentAttendanceSchedule (student_id, start_time, end_time) "
            "VALUES (?, ?, ?)", (sid, start_time, end_time))
    return jsonify(success=True)


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


@app.route("/api/admin/tasks/<int:tid>/approve", methods=["POST"])
@admin
def admin_approve_task(tid):
    run("UPDATE Task SET status='completed', updated_at=GETDATE() WHERE task_id=?", (tid,))
    return jsonify(success=True)


@app.route("/api/admin/tasks/<int:tid>/reject", methods=["POST"])
@admin
def admin_reject_task(tid):
    run("UPDATE Task SET status='in_progress', updated_at=GETDATE() WHERE task_id=?", (tid,))
    return jsonify(success=True)


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
        if d == today and d not in att_dates:
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
    v = {k: (d.get(k) or "").strip() for k in
         ("firstname", "lastname", "email", "mobile_no", "gender", "dob", "city")}
    
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
        if creating:
            return None, "Date of birth is required to generate the password."
        v["dob"] = None
        
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

    # Auto-generate Username and Password
    v["username"] = v["email"]
    dob_str = v["dob"].strftime("%d%m%Y") if v["dob"] else "01012000"
    v["password"] = v["firstname"] + dob_str

    def work(cur):
        cur.execute("SELECT 1 FROM users WHERE username=?", (v["username"],))
        if cur.fetchone():
            raise pyodbc.IntegrityError("Username exists")

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
        return jsonify(success=False, message="That email address is already registered."), 400
    return jsonify(success=True)


@app.route("/api/admin/student-list/<int:sid>", methods=["PUT"])
@admin
def admin_student_update(sid):
    v, err = clean_student(request.get_json(silent=True) or {}, creating=False)
    if err:
        return jsonify(success=False, message=err), 400

    # Auto-update Username to match Email
    v["username"] = v["email"]

    def work(cur):
        cur.execute("UPDATE users SET username=? WHERE user_id=(SELECT user_id FROM Student WHERE student_id=?)",
                    (v["username"], sid))
        
        cur.execute("UPDATE Student SET firstname=?, lastname=?, email=?, mobile_no=?, gender=?, "
                    "dob=?, city=? WHERE student_id=?",
                    (v["firstname"], v["lastname"], v["email"], v["mobile_no"] or None,
                     v["gender"] or None, v["dob"], v["city"], sid))
        
        if cur.rowcount == 0:
            return False
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
    n = run("DELETE FROM users WHERE user_id=(SELECT user_id FROM Student WHERE student_id=?)", (sid,))
    if not n:
        return jsonify(success=False, message="Student not found."), 404
    return jsonify(success=True)


if __name__ == "__main__":
    app.run(debug=True)