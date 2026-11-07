import csv
import base64
import io
import json
import re
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Blueprint, current_app, g, jsonify, request, session, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from .database import audit, get_db
from .security import login_required, roles_required

api = Blueprint("api", __name__)
ROLES = {"admin", "lecturer", "student"}
THEME_DEFAULTS = {"primary":"#286aa8","accent":"#b9714f","mode":"light","radius":12,"glass":False,"shadow":True,"animation":True,"three":True}


def body():
    return request.get_json(silent=True) or {}


def fail(message, status=400):
    return jsonify(error=message), status


def valid_datetime(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def activity_owner(activity_id):
    return get_db().execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()


def can_manage(activity):
    return activity and (g.user["role"] == "admin" or activity["created_by"] == g.user["id"])


@api.post("/login")
def login():
    data = body()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    user = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not user or user["status"] != "active" or not check_password_hash(user["password_hash"], password):
        return fail("Tên đăng nhập hoặc mật khẩu chưa đúng.", 401)
    session.clear()
    session["user_id"] = user["id"]
    session["csrf_token"] = secrets.token_urlsafe(24)
    get_db().execute("UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", (user["id"],))
    avatar = get_db().execute("SELECT setting_value FROM user_settings WHERE user_id=? AND setting_key='avatar_data'", (user["id"],)).fetchone()
    return jsonify(user={"id":user["id"],"username":user["username"],"email":user["email"],"full_name":user["full_name"],"role":user["role"],"avatar_data":avatar["setting_value"] if avatar else None}, csrf_token=session["csrf_token"])


@api.post("/register")
def register_student():
    data = body()
    if str(data.get("password", "")) != str(data.get("confirm_password", "")):
        return fail("Mật khẩu xác nhận chưa khớp.", 422)
    payload = {
        "username": data.get("username"), "email": data.get("email"),
        "password": data.get("password"), "full_name": data.get("full_name"),
        "code": data.get("student_code"), "class_name": data.get("class_name", ""),
        "faculty": data.get("faculty", ""),
    }
    user_id, error = create_person("student", payload)
    if error:
        return fail(error, 409 if "tồn tại" in error else 422)
    audit(user_id, "self_register", "student", user_id)
    return jsonify(ok=True, message="Đăng ký thành công. Bạn có thể đăng nhập ngay."), 201


@api.post("/logout")
@login_required
def logout():
    session.clear()
    session["csrf_token"] = secrets.token_urlsafe(24)
    return jsonify(ok=True, csrf_token=session["csrf_token"])


@api.get("/me")
@login_required
def me():
    user = dict(g.user)
    avatar = get_db().execute("SELECT setting_value FROM user_settings WHERE user_id=? AND setting_key='avatar_data'", (g.user["id"],)).fetchone()
    user["avatar_data"] = avatar["setting_value"] if avatar else None
    return jsonify(user=user, csrf_token=session.get("csrf_token"))


@api.post("/change-password")
@login_required
def change_password():
    data = body()
    old, new = str(data.get("old_password", "")), str(data.get("new_password", ""))
    row = get_db().execute("SELECT password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], old):
        return fail("Mật khẩu hiện tại chưa đúng.", 422)
    if len(new) < 8:
        return fail("Mật khẩu mới cần có ít nhất 8 ký tự.", 422)
    get_db().execute("UPDATE users SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (generate_password_hash(new),g.user["id"]))
    audit(g.user["id"],"change_password","user",g.user["id"])
    return jsonify(ok=True,message="Đã cập nhật mật khẩu.")


@api.get("/profile")
@login_required
def profile():
    db = get_db()
    data = dict(g.user)
    avatar = db.execute("SELECT setting_value FROM user_settings WHERE user_id=? AND setting_key='avatar_data'", (g.user["id"],)).fetchone()
    data["avatar_data"] = avatar["setting_value"] if avatar else None
    if g.user["role"] == "student":
        row = db.execute("SELECT student_code,class_name,faculty,phone,date_of_birth,gender,address FROM students WHERE user_id=?",(g.user["id"],)).fetchone()
    elif g.user["role"] == "lecturer":
        row = db.execute("SELECT lecturer_code AS code,department,phone,position FROM lecturers WHERE user_id=?",(g.user["id"],)).fetchone()
    else:
        row = None
    data["details"] = dict(row) if row else {}
    return jsonify(profile=data)


@api.put("/profile/avatar")
@login_required
def update_avatar():
    data_uri = str(body().get("avatar_data", ""))
    db = get_db()
    if not data_uri:
        db.execute("DELETE FROM user_settings WHERE user_id=? AND setting_key='avatar_data'", (g.user["id"],))
        return jsonify(ok=True, avatar_data=None)
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})", data_uri)
    if not match:
        return fail("Ảnh cần ở định dạng PNG, JPEG hoặc WEBP.", 422)
    try:
        image_bytes = base64.b64decode(match.group(2), validate=True)
    except (ValueError, base64.binascii.Error):
        return fail("Ảnh tải lên chưa hợp lệ.", 422)
    mime = match.group(1)
    signatures = {
        "png": image_bytes.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpeg": image_bytes.startswith(b"\xff\xd8\xff"),
        "webp": len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP",
    }
    if len(image_bytes) > 1200 * 1024 or not image_bytes or not signatures[mime]:
        return fail("Ảnh không đúng định dạng hoặc lớn hơn 1,2 MB.", 422)
    db.execute("INSERT INTO user_settings(user_id,setting_key,setting_value,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id,setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP",
               (g.user["id"], "avatar_data", data_uri))
    audit(g.user["id"], "update_avatar", "user", g.user["id"])
    return jsonify(ok=True, avatar_data=data_uri)


@api.get("/people")
@login_required
def people_directory():
    query = str(request.args.get("q", ""))[:80]
    role = request.args.get("role", "")
    where = ["u.status='active'", "u.role IN ('student','lecturer')"]
    params = []
    if role in {"student", "lecturer"}:
        where.append("u.role=?"); params.append(role)
    if query:
        where.append("(u.full_name LIKE ? OR u.username LIKE ? OR s.student_code LIKE ? OR l.lecturer_code LIKE ? OR s.faculty LIKE ? OR l.department LIKE ?)")
        params.extend([f"%{query}%"] * 6)
    rows = get_db().execute(f"SELECT u.id,u.username,u.full_name,u.role,s.student_code,l.lecturer_code,COALESCE(s.faculty,l.department,'') AS unit,COALESCE(s.class_name,'') AS class_name,(SELECT setting_value FROM user_settings us WHERE us.user_id=u.id AND us.setting_key='avatar_data') AS avatar_data FROM users u LEFT JOIN students s ON s.user_id=u.id LEFT JOIN lecturers l ON l.user_id=u.id WHERE {' AND '.join(where)} ORDER BY u.role,u.full_name LIMIT 300", params).fetchall()
    return jsonify(items=[dict(row) for row in rows])


@api.get("/people/<int:user_id>")
@login_required
def public_person(user_id):
    row = get_db().execute("SELECT u.id,u.username,u.full_name,u.role,u.status,s.student_code,s.class_name,s.faculty,l.lecturer_code,l.department,l.position,(SELECT setting_value FROM user_settings us WHERE us.user_id=u.id AND us.setting_key='avatar_data') AS avatar_data FROM users u LEFT JOIN students s ON s.user_id=u.id LEFT JOIN lecturers l ON l.user_id=u.id WHERE u.id=? AND u.status='active' AND u.role IN ('student','lecturer')", (user_id,)).fetchone()
    if not row:
        return fail("Không tìm thấy hồ sơ công khai.", 404)
    person = dict(row)
    if person["role"] == "student":
        stats = get_db().execute("SELECT COUNT(DISTINCT a.id) AS activities,COALESCE(SUM(CASE WHEN at.status IN ('present','late') THEN (julianday(a.end_time)-julianday(a.start_time))*24 ELSE 0 END),0) AS hours,COALESCE(SUM(sc.score),0) AS points FROM students s LEFT JOIN registrations r ON r.student_id=s.id AND r.status IN ('approved','cancelled') LEFT JOIN activities a ON a.id=r.activity_id LEFT JOIN attendance at ON at.registration_id=r.id LEFT JOIN activity_scores sc ON sc.registration_id=r.id WHERE s.user_id=?", (user_id,)).fetchone()
    else:
        stats = get_db().execute("SELECT COUNT(DISTINCT a.id) AS activities,COUNT(DISTINCT CASE WHEN at.status IN ('present','late') THEN at.id END) AS volunteers,COALESCE(SUM(CASE WHEN at.status IN ('present','late') THEN (julianday(a.end_time)-julianday(a.start_time))*24 ELSE 0 END),0) AS hours FROM activities a LEFT JOIN registrations r ON r.activity_id=a.id AND r.status='approved' LEFT JOIN attendance at ON at.registration_id=r.id WHERE a.created_by=?", (user_id,)).fetchone()
    person["stats"] = {key: round(value or 0, 1) if key == "hours" else (value or 0) for key, value in dict(stats).items()}
    return jsonify(person=person)


@api.get("/impact")
@login_required
def volunteer_impact():
    db = get_db()
    stats = {
        "students": db.execute("SELECT COUNT(*) FROM students s JOIN users u ON u.id=s.user_id WHERE u.status='active'").fetchone()[0],
        "lecturers": db.execute("SELECT COUNT(*) FROM lecturers l JOIN users u ON u.id=l.user_id WHERE u.status='active'").fetchone()[0],
        "activities": db.execute("SELECT COUNT(*) FROM activities WHERE status!='cancelled'").fetchone()[0],
        "volunteers": db.execute("SELECT COUNT(*) FROM attendance WHERE status IN ('present','late')").fetchone()[0],
        "hours": db.execute("SELECT COALESCE(SUM((julianday(a.end_time)-julianday(a.start_time))*24),0) FROM attendance at JOIN registrations r ON r.id=at.registration_id JOIN activities a ON a.id=r.activity_id WHERE at.status IN ('present','late')").fetchone()[0],
    }
    monthly = db.execute("SELECT strftime('%Y-%m',a.start_time) AS month,COUNT(DISTINCT a.id) AS activities,COUNT(DISTINCT CASE WHEN at.status IN ('present','late') THEN at.id END) AS volunteers,ROUND(COALESCE(SUM(CASE WHEN at.status IN ('present','late') THEN (julianday(a.end_time)-julianday(a.start_time))*24 ELSE 0 END),0),1) AS hours FROM activities a LEFT JOIN registrations r ON r.activity_id=a.id AND r.status='approved' LEFT JOIN attendance at ON at.registration_id=r.id WHERE a.start_time>=date('now','-5 months') GROUP BY strftime('%Y-%m',a.start_time) ORDER BY month").fetchall()
    status_counts = db.execute("SELECT status,COUNT(*) AS total FROM activities WHERE status!='cancelled' GROUP BY status").fetchall()
    top_activities = db.execute("SELECT a.id,a.title,a.start_time,a.location,COUNT(r.id) AS registered FROM activities a LEFT JOIN registrations r ON r.activity_id=a.id AND r.status IN ('pending','approved') WHERE a.status!='cancelled' GROUP BY a.id ORDER BY registered DESC,a.start_time LIMIT 5").fetchall()
    upcoming = db.execute("SELECT a.id,a.title,a.category,a.location,a.start_time,a.end_time,a.max_participants,(SELECT COUNT(*) FROM registrations r WHERE r.activity_id=a.id AND r.status IN ('pending','approved')) AS registered FROM activities a WHERE a.status='open' AND a.start_time>=datetime('now') ORDER BY a.start_time LIMIT 6").fetchall()
    stats["hours"] = round(stats["hours"] or 0, 1)
    return jsonify(stats=stats, monthly=[dict(row) for row in monthly], status_counts=[dict(row) for row in status_counts], top_activities=[dict(row) for row in top_activities], upcoming=[dict(row) for row in upcoming])


@api.put("/profile")
@login_required
def update_profile():
    data = body(); db=get_db()
    full_name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    if not full_name or len(full_name)>120 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):
        return fail("Vui lòng nhập họ tên và email hợp lệ.",422)
    try:
        db.execute("UPDATE users SET full_name=?,email=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(full_name,email,g.user["id"]))
    except sqlite3.IntegrityError:
        return fail("Email này đã được sử dụng.",409)
    if g.user["role"] == "student":
        db.execute("UPDATE students SET phone=?,address=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",(str(data.get("phone",""))[:30],str(data.get("address",""))[:300],g.user["id"]))
    elif g.user["role"] == "lecturer":
        db.execute("UPDATE lecturers SET phone=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",(str(data.get("phone",""))[:30],g.user["id"]))
    return jsonify(ok=True)


@api.get("/dashboard")
@login_required
def dashboard():
    db=get_db(); role=g.user["role"]; uid=g.user["id"]
    if role == "admin":
        stats={"students":db.execute("SELECT COUNT(*) FROM students s JOIN users u ON u.id=s.user_id WHERE u.status='active'").fetchone()[0],
               "lecturers":db.execute("SELECT COUNT(*) FROM lecturers").fetchone()[0],
               "activities":db.execute("SELECT COUNT(*) FROM activities WHERE status!='cancelled'").fetchone()[0],
               "open":db.execute("SELECT COUNT(*) FROM activities WHERE status='open'").fetchone()[0],
               "registrations":db.execute("SELECT COUNT(*) FROM registrations WHERE status IN ('pending','approved')").fetchone()[0],
               "participants":db.execute("SELECT COUNT(*) FROM attendance WHERE status IN ('present','late')").fetchone()[0]}
        recent=db.execute("SELECT a.*,u.full_name AS owner,(SELECT COUNT(*) FROM registrations r WHERE r.activity_id=a.id AND r.status IN ('pending','approved')) AS registered FROM activities a JOIN users u ON u.id=a.created_by WHERE a.status!='cancelled' ORDER BY CASE WHEN a.start_time>=datetime('now') THEN 0 ELSE 1 END,a.start_time LIMIT 6").fetchall()
        monthly=db.execute("SELECT strftime('%Y-%m',a.start_time) AS month,COUNT(DISTINCT a.id) AS total,COUNT(DISTINCT r.id) AS registrations,COUNT(DISTINCT CASE WHEN at.status IN ('present','late') THEN at.id END) AS participants,ROUND(COALESCE(SUM(CASE WHEN at.status IN ('present','late') THEN (julianday(a.end_time)-julianday(a.start_time))*24 ELSE 0 END),0),1) AS hours FROM activities a LEFT JOIN registrations r ON r.activity_id=a.id AND r.status='approved' LEFT JOIN attendance at ON at.registration_id=r.id WHERE a.start_time>=date('now','-5 months') GROUP BY strftime('%Y-%m',a.start_time) ORDER BY month").fetchall()
        status_counts=db.execute("SELECT status,COUNT(*) AS total FROM activities WHERE status!='cancelled' GROUP BY status").fetchall()
        top_activities=db.execute("SELECT a.id,a.title,a.start_time,a.location,COUNT(r.id) AS registered FROM activities a LEFT JOIN registrations r ON r.activity_id=a.id AND r.status IN ('pending','approved') WHERE a.status!='cancelled' GROUP BY a.id ORDER BY registered DESC,a.start_time LIMIT 5").fetchall()
        return jsonify(role=role,stats=stats,recent=[dict(x) for x in recent],monthly=[dict(x) for x in monthly],status_counts=[dict(x) for x in status_counts],top_activities=[dict(x) for x in top_activities])
    if role == "lecturer":
        recent=db.execute("SELECT a.*,(SELECT COUNT(*) FROM registrations r WHERE r.activity_id=a.id AND r.status='pending') AS pending,(SELECT COUNT(*) FROM registrations r WHERE r.activity_id=a.id AND r.status IN ('pending','approved')) AS registered FROM activities a WHERE a.created_by=? AND a.status!='cancelled' ORDER BY a.start_time LIMIT 6",(uid,)).fetchall()
        stats={"activities":db.execute("SELECT COUNT(*) FROM activities WHERE created_by=? AND status!='cancelled'",(uid,)).fetchone()[0],"pending":db.execute("SELECT COUNT(*) FROM registrations r JOIN activities a ON a.id=r.activity_id WHERE a.created_by=? AND r.status='pending'",(uid,)).fetchone()[0],"registrations":db.execute("SELECT COUNT(*) FROM registrations r JOIN activities a ON a.id=r.activity_id WHERE a.created_by=? AND r.status IN ('pending','approved')",(uid,)).fetchone()[0],"upcoming":db.execute("SELECT COUNT(*) FROM activities WHERE created_by=? AND start_time>=datetime('now')",(uid,)).fetchone()[0]}
        return jsonify(role=role,stats=stats,recent=[dict(x) for x in recent])
    student=db.execute("SELECT id FROM students WHERE user_id=?",(uid,)).fetchone()
    sid=student["id"] if student else 0
    stats={"registered":db.execute("SELECT COUNT(*) FROM registrations WHERE student_id=? AND status IN ('pending','approved')",(sid,)).fetchone()[0],"pending":db.execute("SELECT COUNT(*) FROM registrations WHERE student_id=? AND status='pending'",(sid,)).fetchone()[0],"attended":db.execute("SELECT COUNT(*) FROM attendance at JOIN registrations r ON r.id=at.registration_id WHERE r.student_id=? AND at.status IN ('present','late')",(sid,)).fetchone()[0],"points":db.execute("SELECT COALESCE(SUM(sc.score),0) FROM activity_scores sc JOIN registrations r ON r.id=sc.registration_id WHERE r.student_id=?",(sid,)).fetchone()[0]}
    recent=db.execute("SELECT a.*,r.status AS registration_status FROM activities a LEFT JOIN registrations r ON r.activity_id=a.id AND r.student_id=? WHERE a.status='open' ORDER BY a.start_time LIMIT 6",(sid,)).fetchall()
    return jsonify(role=role,stats=stats,recent=[dict(x) for x in recent])


@api.get("/activities")
@login_required
def activities():
    db=get_db(); q=str(request.args.get("q",""))[:100]; status=request.args.get("status",""); category=request.args.get("category","")
    page=max(1,int(request.args.get("page",1) or 1)); size=min(50,max(1,int(request.args.get("size",20) or 20)))
    where=["a.status!='cancelled'"]; params=[]
    if g.user["role"]=="lecturer": where.append("(a.created_by=? OR a.status='open')"); params.append(g.user["id"])
    if g.user["role"]=="student": where.append("a.status IN ('open','closed','completed')")
    if q: where.append("(a.title LIKE ? OR a.location LIKE ? OR a.organizer LIKE ?)"); params.extend([f"%{q}%"]*3)
    if status: where.append("a.status=?"); params.append(status)
    if category: where.append("a.category=?"); params.append(category)
    condition=" AND ".join(where)
    total=db.execute(f"SELECT COUNT(*) FROM activities a WHERE {condition}",params).fetchone()[0]
    student_row=db.execute("SELECT id FROM students WHERE user_id=?",(g.user["id"],)).fetchone() if g.user["role"]=="student" else None
    select_extra=",(SELECT r.status FROM registrations r WHERE r.activity_id=a.id AND r.student_id=?) AS my_registration_status" if student_row else ""
    if student_row: params=[student_row["id"]]+params
    rows=db.execute(f"SELECT a.*,u.full_name AS owner,(SELECT COUNT(*) FROM registrations r WHERE r.activity_id=a.id AND r.status IN ('pending','approved')) AS registered{select_extra} FROM activities a JOIN users u ON u.id=a.created_by WHERE {condition} ORDER BY a.start_time LIMIT ? OFFSET ?",params+[size,(page-1)*size]).fetchall()
    return jsonify(items=[dict(r) for r in rows],total=total,page=page,size=size)


def validate_activity(data, creating=False):
    required=["title","start_time","end_time","registration_deadline"]
    if any(not str(data.get(k,"" )).strip() for k in required): return "Vui lòng điền tên hoạt động và các mốc thời gian."
    start,end,deadline=map(valid_datetime,[data.get("start_time"),data.get("end_time"),data.get("registration_deadline")])
    if not start or not end or not deadline or end<=start or deadline>start: return "Thời gian hoạt động hoặc hạn đăng ký chưa hợp lệ."
    try:
        cap=int(data.get("max_participants",0)); points=float(data.get("activity_points",0))
        if cap<1 or cap>100000 or points<0 or points>1000: raise ValueError
    except (TypeError,ValueError): return "Số lượng cần lớn hơn 0 và điểm nằm trong khoảng 0–1000."
    if data.get("status","open") not in {"draft","open","closed","completed"}: return "Trạng thái hoạt động không hợp lệ."
    return None


@api.post("/activities")
@roles_required("admin","lecturer")
def create_activity():
    data=body(); error=validate_activity(data)
    if error:return fail(error,422)
    db=get_db()
    cur=db.execute("INSERT INTO activities(title,description,category,organizer,location,start_time,end_time,registration_deadline,max_participants,activity_points,status,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (str(data["title"]).strip()[:180],str(data.get("description",""))[:3000],str(data.get("category","Khác"))[:80],str(data.get("organizer",""))[:120],str(data.get("location",""))[:180],data["start_time"],data["end_time"],data["registration_deadline"],int(data["max_participants"]),float(data.get("activity_points",0)),data.get("status","open"),g.user["id"],g.user["id"]))
    audit(g.user["id"],"create","activity",cur.lastrowid)
    return jsonify(id=cur.lastrowid,message="Đã tạo hoạt động."),201


@api.get("/activities/<int:activity_id>")
@login_required
def activity_detail(activity_id):
    row=activity_owner(activity_id)
    if not row:return fail("Không tìm thấy hoạt động.",404)
    if g.user["role"]=="lecturer" and not can_manage(row) and row["status"]!="open":return fail("Bạn không có quyền xem hoạt động này.",403)
    result=dict(row)
    result["registered"]=get_db().execute("SELECT COUNT(*) FROM registrations WHERE activity_id=? AND status IN ('pending','approved')",(activity_id,)).fetchone()[0]
    if g.user["role"]=="student":
        student=get_db().execute("SELECT id FROM students WHERE user_id=?",(g.user["id"],)).fetchone()
        result["my_registration"]=get_db().execute("SELECT id,status FROM registrations WHERE activity_id=? AND student_id=?",(activity_id,student["id"] if student else 0)).fetchone()
        result["my_registration"]=dict(result["my_registration"]) if result["my_registration"] else None
    return jsonify(activity=result)


@api.put("/activities/<int:activity_id>")
@roles_required("admin","lecturer")
def update_activity(activity_id):
    db=get_db(); old=activity_owner(activity_id)
    if not old:return fail("Không tìm thấy hoạt động.",404)
    if not can_manage(old):return fail("Bạn chỉ có thể sửa hoạt động do mình phụ trách.",403)
    data=body(); merged={**dict(old),**data}; error=validate_activity(merged)
    if error:return fail(error,422)
    db.execute("UPDATE activities SET title=?,description=?,category=?,organizer=?,location=?,start_time=?,end_time=?,registration_deadline=?,max_participants=?,activity_points=?,status=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
       (str(merged["title"]).strip()[:180],str(merged.get("description",""))[:3000],str(merged.get("category","Khác"))[:80],str(merged.get("organizer",""))[:120],str(merged.get("location",""))[:180],merged["start_time"],merged["end_time"],merged["registration_deadline"],int(merged["max_participants"]),float(merged.get("activity_points",0)),merged.get("status","open"),g.user["id"],activity_id))
    audit(g.user["id"],"update","activity",activity_id)
    return jsonify(ok=True)


@api.delete("/activities/<int:activity_id>")
@roles_required("admin","lecturer")
def cancel_activity(activity_id):
    row=activity_owner(activity_id)
    if not row:return fail("Không tìm thấy hoạt động.",404)
    if not can_manage(row):return fail("Bạn chỉ có thể hủy hoạt động do mình phụ trách.",403)
    get_db().execute("UPDATE activities SET status='cancelled',updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(g.user["id"],activity_id))
    audit(g.user["id"],"cancel","activity",activity_id)
    return jsonify(ok=True)


@api.get("/registrations")
@login_required
def registrations():
    db=get_db(); where=[]; params=[]
    if g.user["role"]=="student":where.append("s.user_id=?");params.append(g.user["id"])
    elif g.user["role"]=="lecturer":where.append("a.created_by=?");params.append(g.user["id"])
    if request.args.get("activity_id"):where.append("a.id=?");params.append(request.args["activity_id"])
    if request.args.get("status"):where.append("r.status=?");params.append(request.args["status"])
    clause=("WHERE "+" AND ".join(where)) if where else ""
    rows=db.execute(f"SELECT r.*,s.student_code,s.class_name,u.full_name AS student_name,u.email,a.title AS activity_title,a.start_time,a.activity_points FROM registrations r JOIN activities a ON a.id=r.activity_id JOIN students s ON s.id=r.student_id JOIN users u ON u.id=s.user_id {clause} ORDER BY r.registered_at DESC LIMIT 300",params).fetchall()
    return jsonify(items=[dict(x) for x in rows])


@api.post("/registrations")
@roles_required("student")
def register_activity():
    data=body(); db=get_db(); aid=data.get("activity_id")
    student=db.execute("SELECT id FROM students WHERE user_id=?",(g.user["id"],)).fetchone()
    if not student:return fail("Tài khoản chưa có hồ sơ sinh viên.",422)
    try:
        db.execute("BEGIN IMMEDIATE")
        act=db.execute("SELECT * FROM activities WHERE id=?",(aid,)).fetchone()
        now=datetime.now().isoformat(timespec="minutes")
        if not act or act["status"]!="open" or valid_datetime(act["registration_deadline"])<datetime.now():
            db.rollback();return fail("Hoạt động không còn nhận đăng ký.",422)
        existing=db.execute("SELECT id,status FROM registrations WHERE activity_id=? AND student_id=?",(aid,student["id"])).fetchone()
        if existing:
            db.rollback();return fail("Bạn đã đăng ký hoạt động này trước đó.",409)
        occupied=db.execute("SELECT COUNT(*) FROM registrations WHERE activity_id=? AND status IN ('pending','approved')",(aid,)).fetchone()[0]
        if occupied>=act["max_participants"]:
            db.rollback();return fail("Hoạt động đã đủ số lượng tham gia.",422)
        cur=db.execute("INSERT INTO registrations(activity_id,student_id,status) VALUES(?,?,'pending')",(aid,student["id"]))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback();return fail("Bạn đã đăng ký hoạt động này trước đó.",409)
    audit(g.user["id"],"register","activity",aid)
    return jsonify(id=cur.lastrowid,message="Đã gửi đăng ký chờ duyệt."),201


def review_registration(registration_id, status):
    db=get_db(); row=db.execute("SELECT r.*,a.created_by FROM registrations r JOIN activities a ON a.id=r.activity_id WHERE r.id=?",(registration_id,)).fetchone()
    if not row:return fail("Không tìm thấy đăng ký.",404)
    if g.user["role"]!="admin" and row["created_by"]!=g.user["id"]:return fail("Bạn không có quyền xử lý đăng ký này.",403)
    if row["status"]!="pending":return fail("Chỉ có thể xử lý đăng ký đang chờ.",422)
    if status=="approved":
        seats=db.execute("SELECT COUNT(*) FROM registrations WHERE activity_id=? AND status IN ('pending','approved')",(row["activity_id"],)).fetchone()[0]
        cap=db.execute("SELECT max_participants FROM activities WHERE id=?",(row["activity_id"],)).fetchone()[0]
        if seats>cap:return fail("Hoạt động đã hết chỗ.",422)
    db.execute("UPDATE registrations SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP,status_note=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,g.user["id"],str(body().get("note",""))[:300],registration_id))
    audit(g.user["id"],status,"registration",registration_id)
    student_uid=db.execute("SELECT user_id FROM students WHERE id=?",(row["student_id"],)).fetchone()[0]
    activity_title=db.execute("SELECT title FROM activities WHERE id=?",(row["activity_id"],)).fetchone()[0]
    db.execute("INSERT INTO notifications(title,content,type,recipient_user_id,created_by,related_activity_id) VALUES(?,?,?,?,?,?)",("Cập nhật đăng ký",f"Đăng ký hoạt động ‘{activity_title}’ đã được {('duyệt' if status=='approved' else 'từ chối')}.","registration",student_uid,g.user["id"],row["activity_id"]))
    return jsonify(ok=True)


@api.put("/registrations/<int:registration_id>/approve")
@roles_required("admin","lecturer")
def approve_registration(registration_id): return review_registration(registration_id,"approved")


@api.put("/registrations/<int:registration_id>/reject")
@roles_required("admin","lecturer")
def reject_registration(registration_id): return review_registration(registration_id,"rejected")


@api.delete("/registrations/<int:registration_id>")
@login_required
def cancel_registration(registration_id):
    db=get_db(); row=db.execute("SELECT r.*,s.user_id FROM registrations r JOIN students s ON s.id=r.student_id WHERE r.id=?",(registration_id,)).fetchone()
    if not row:return fail("Không tìm thấy đăng ký.",404)
    if g.user["role"]!="admin" and row["user_id"]!=g.user["id"]:return fail("Bạn không có quyền hủy đăng ký này.",403)
    if row["status"] not in ("pending","approved"):return fail("Đăng ký này không thể hủy.",422)
    activity=get_db().execute("SELECT start_time FROM activities WHERE id=?",(row["activity_id"],)).fetchone()
    start=valid_datetime(activity["start_time"])
    if start and start<=datetime.now():return fail("Không thể hủy đăng ký sau khi hoạt động đã bắt đầu.",422)
    db.execute("UPDATE registrations SET status='cancelled',cancelled_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(registration_id,))
    return jsonify(ok=True)


@api.get("/attendance")
@roles_required("admin","lecturer")
def attendance_list():
    aid=request.args.get("activity_id"); db=get_db(); params=[]; where=""
    if aid:where="WHERE a.id=?";params=[aid]
    if g.user["role"]=="lecturer":where+=(" AND " if where else "WHERE ")+"a.created_by=?";params.append(g.user["id"])
    rows=db.execute(f"SELECT r.id AS registration_id,r.status AS registration_status,s.student_code,u.full_name,r.activity_id,a.title AS activity_title,at.id AS attendance_id,at.status AS attendance_status,at.note,at.check_in_time FROM registrations r JOIN students s ON s.id=r.student_id JOIN users u ON u.id=s.user_id JOIN activities a ON a.id=r.activity_id LEFT JOIN attendance at ON at.registration_id=r.id {where} AND r.status='approved' ORDER BY a.start_time,u.full_name" if where else "SELECT r.id AS registration_id,r.status AS registration_status,s.student_code,u.full_name,r.activity_id,a.title AS activity_title,at.id AS attendance_id,at.status AS attendance_status,at.note,at.check_in_time FROM registrations r JOIN students s ON s.id=r.student_id JOIN users u ON u.id=s.user_id JOIN activities a ON a.id=r.activity_id LEFT JOIN attendance at ON at.registration_id=r.id WHERE r.status='approved' ORDER BY a.start_time,u.full_name",params).fetchall()
    return jsonify(items=[dict(x) for x in rows])


@api.post("/attendance")
@api.put("/attendance/<int:attendance_id>")
@roles_required("admin","lecturer")
def save_attendance(attendance_id=None):
    data=body(); db=get_db(); rid=data.get("registration_id")
    if attendance_id:
        row=db.execute("SELECT registration_id FROM attendance WHERE id=?",(attendance_id,)).fetchone()
        if not row:return fail("Không tìm thấy điểm danh.",404)
        rid=row["registration_id"]
    reg=db.execute("SELECT r.id,a.created_by FROM registrations r JOIN activities a ON a.id=r.activity_id WHERE r.id=? AND r.status='approved'",(rid,)).fetchone()
    if not reg:return fail("Đăng ký hợp lệ không tồn tại.",422)
    if g.user["role"]=="lecturer" and reg["created_by"]!=g.user["id"]:return fail("Bạn không có quyền điểm danh hoạt động này.",403)
    status=data.get("status")
    if status not in {"present","absent","late"}:return fail("Trạng thái điểm danh chưa hợp lệ.",422)
    db.execute("INSERT INTO attendance(registration_id,status,check_in_time,note,marked_by) VALUES(?,?,?,?,?) ON CONFLICT(registration_id) DO UPDATE SET status=excluded.status,check_in_time=excluded.check_in_time,note=excluded.note,marked_by=excluded.marked_by,updated_at=CURRENT_TIMESTAMP",(rid,status,datetime.now().isoformat(timespec="minutes") if status in {"present","late"} else None,str(data.get("note",""))[:300],g.user["id"]))
    audit(g.user["id"],"attendance","registration",rid,status)
    return jsonify(ok=True)


@api.get("/scores")
@login_required
def scores_list():
    db=get_db(); where="";params=[]
    if g.user["role"]=="student":where="WHERE s.user_id=?";params=[g.user["id"]]
    elif g.user["role"]=="lecturer":where="WHERE a.created_by=?";params=[g.user["id"]]
    rows=db.execute(f"SELECT sc.id,sc.registration_id,sc.score,sc.note,sc.updated_at,r.status AS registration_status,s.student_code,u.full_name AS student_name,a.title AS activity_title,a.activity_points FROM activity_scores sc JOIN registrations r ON r.id=sc.registration_id JOIN students s ON s.id=r.student_id JOIN users u ON u.id=s.user_id JOIN activities a ON a.id=r.activity_id {where} ORDER BY sc.updated_at DESC",params).fetchall()
    return jsonify(items=[dict(x) for x in rows])


@api.post("/scores")
@api.put("/scores/<int:score_id>")
@roles_required("admin","lecturer")
def save_score(score_id=None):
    data=body(); db=get_db(); rid=data.get("registration_id")
    if score_id:
        found=db.execute("SELECT registration_id FROM activity_scores WHERE id=?",(score_id,)).fetchone()
        if not found:return fail("Không tìm thấy kết quả điểm.",404)
        rid=found["registration_id"]
    row=db.execute("SELECT r.id,a.activity_points,a.created_by FROM registrations r JOIN activities a ON a.id=r.activity_id WHERE r.id=? AND r.status IN ('approved','cancelled')",(rid,)).fetchone()
    if not row:return fail("Lượt đăng ký chưa đủ điều kiện chấm điểm.",422)
    if g.user["role"]=="lecturer" and row["created_by"]!=g.user["id"]:return fail("Bạn không có quyền chấm hoạt động này.",403)
    try:score=float(data.get("score"))
    except (TypeError,ValueError):return fail("Điểm cần là một số hợp lệ.",422)
    if score<0 or score>row["activity_points"]:return fail("Điểm phải nằm trong giới hạn của hoạt động.",422)
    db.execute("INSERT INTO activity_scores(registration_id,score,note,created_by) VALUES(?,?,?,?) ON CONFLICT(registration_id) DO UPDATE SET score=excluded.score,note=excluded.note,created_by=excluded.created_by,updated_at=CURRENT_TIMESTAMP",(rid,score,str(data.get("note",""))[:300],g.user["id"]))
    audit(g.user["id"],"score","registration",rid,str(score))
    return jsonify(ok=True)


@api.get("/notifications")
@login_required
def notifications():
    rows=get_db().execute("SELECT n.*,COALESCE(nr.read_at IS NOT NULL,0) AS is_read FROM notifications n LEFT JOIN notification_reads nr ON nr.notification_id=n.id AND nr.user_id=? WHERE n.recipient_user_id=? OR n.recipient_user_id IS NULL ORDER BY n.created_at DESC LIMIT 100",(g.user["id"],g.user["id"])).fetchall()
    return jsonify(items=[dict(x) for x in rows])


@api.post("/notifications")
@roles_required("admin","lecturer")
def create_notification():
    data=body(); title=str(data.get("title"," ")).strip(); content=str(data.get("content"," ")).strip()
    if not title or not content:return fail("Vui lòng nhập tiêu đề và nội dung thông báo.",422)
    target=data.get("recipient_user_id"); db=get_db()
    if target and g.user["role"]=="lecturer":return fail("Giảng viên chỉ có thể gửi thông báo chung.",403)
    cur=db.execute("INSERT INTO notifications(title,content,type,recipient_user_id,created_by,related_activity_id) VALUES(?,?,?,?,?,?)",(title[:180],content[:3000],"general",target,g.user["id"],data.get("related_activity_id")))
    if not target:
        db.execute("INSERT INTO notification_reads(notification_id,user_id) SELECT ?,id FROM users WHERE status='active'",(cur.lastrowid,))
    audit(g.user["id"],"create","notification",cur.lastrowid)
    return jsonify(id=cur.lastrowid),201


@api.put("/notifications/<int:notification_id>/read")
@login_required
def mark_notification_read(notification_id):
    db=get_db(); item=db.execute("SELECT recipient_user_id FROM notifications WHERE id=?",(notification_id,)).fetchone()
    if not item:return fail("Không tìm thấy thông báo.",404)
    if item["recipient_user_id"] not in (None,g.user["id"]):return fail("Bạn không có quyền xem thông báo này.",403)
    db.execute("INSERT INTO notification_reads(notification_id,user_id,read_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(notification_id,user_id) DO UPDATE SET read_at=CURRENT_TIMESTAMP",(notification_id,g.user["id"]))
    return jsonify(ok=True)


@api.get("/settings/theme")
@login_required
def get_theme():
    db=get_db(); stored=db.execute("SELECT setting_value FROM system_settings WHERE setting_key='theme_defaults'").fetchone()
    theme=json.loads(stored[0]) if stored else dict(THEME_DEFAULTS)
    personal=db.execute("SELECT setting_key,setting_value FROM user_settings WHERE user_id=?",(g.user["id"],)).fetchall()
    for row in personal:
        try:theme[row["setting_key"]]=json.loads(row["setting_value"])
        except ValueError:pass
    return jsonify(theme=theme)


@api.put("/settings/theme")
@login_required
def save_theme():
    data=body(); allowed={"primary","accent","mode","radius","glass","shadow","animation","three"}; theme={k:data[k] for k in allowed if k in data}
    for key in ("primary","accent"):
        if key in theme and not re.fullmatch(r"#[0-9a-fA-F]{6}",str(theme[key])):return fail("Mã màu cần theo định dạng #RRGGBB.",422)
    if "mode" in theme and theme["mode"] not in ("light","dark"):return fail("Chế độ giao diện không hợp lệ.",422)
    if "radius" in theme and (not isinstance(theme["radius"],(int,float)) or not 6<=theme["radius"]<=32):return fail("Bo góc cần nằm trong khoảng 6–32.",422)
    for key,value in theme.items():
        get_db().execute("INSERT INTO user_settings(user_id,setting_key,setting_value) VALUES(?,?,?) ON CONFLICT(user_id,setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP",(g.user["id"],key,json.dumps(value)))
    return jsonify(ok=True)


@api.post("/settings/theme/reset")
@login_required
def reset_theme():
    get_db().execute("DELETE FROM user_settings WHERE user_id=?",(g.user["id"],))
    return jsonify(theme=THEME_DEFAULTS)


def create_person(kind, data):
    db=get_db(); role="student" if kind=="student" else "lecturer"
    username=str(data.get("username"," ")).strip(); full_name=str(data.get("full_name"," ")).strip(); email=str(data.get("email"," ")).strip().lower(); password=str(data.get("password",""))
    code=str(data.get("code"," ")).strip().upper()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}",username) or not full_name or len(full_name)>120 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email) or len(password)<8 or not code or len(code)>40:
        return None,"Cần nhập đầy đủ tên, tài khoản, email, mã hồ sơ và mật khẩu từ 8 ký tự."
    try:
        db.execute("BEGIN IMMEDIATE")
        cur=db.execute("INSERT INTO users(username,email,password_hash,full_name,role) VALUES(?,?,?,?,?)",(username,email,generate_password_hash(password),full_name,role)); uid=cur.lastrowid
        if kind=="student":db.execute("INSERT INTO students(user_id,student_code,class_name,faculty,phone) VALUES(?,?,?,?,?)",(uid,code,str(data.get("class_name",""))[:80],str(data.get("faculty",""))[:120],str(data.get("phone",""))[:30]))
        else:db.execute("INSERT INTO lecturers(user_id,lecturer_code,department,phone,position) VALUES(?,?,?,?,?)",(uid,code,str(data.get("department",""))[:120],str(data.get("phone",""))[:30],str(data.get("position",""))[:100]))
        db.commit();return uid,None
    except sqlite3.IntegrityError:
        db.rollback();return None,"Tên đăng nhập, email hoặc mã hồ sơ đã tồn tại."


@api.get("/students")
@roles_required("admin")
def students():
    q=str(request.args.get("q",""))[:80]
    rows=get_db().execute("SELECT s.*,u.username,u.email,u.full_name,u.status FROM students s JOIN users u ON u.id=s.user_id WHERE u.full_name LIKE ? OR s.student_code LIKE ? OR s.class_name LIKE ? ORDER BY u.full_name LIMIT 300",(f"%{q}%",)*3).fetchall()
    return jsonify(items=[dict(x) for x in rows])


@api.post("/students")
@roles_required("admin")
def add_student():
    uid,error=create_person("student",body())
    if error:return fail(error,409 if "tồn tại" in error else 422)
    audit(g.user["id"],"create","student",uid);return jsonify(id=uid),201


@api.get("/students/<int:student_id>")
@roles_required("admin")
def student_detail(student_id):
    row=get_db().execute("SELECT s.*,u.username,u.email,u.full_name,u.status FROM students s JOIN users u ON u.id=s.user_id WHERE s.id=?",(student_id,)).fetchone()
    return (jsonify(student=dict(row)),200) if row else fail("Không tìm thấy sinh viên.",404)


@api.put("/students/<int:student_id>")
@roles_required("admin")
def update_student(student_id):
    data=body(); db=get_db()
    row=db.execute("SELECT s.user_id FROM students s WHERE s.id=?",(student_id,)).fetchone()
    if not row:return fail("Không tìm thấy sinh viên.",404)
    full_name=str(data.get("full_name"," ")).strip(); email=str(data.get("email"," ")).strip().lower(); code=str(data.get("student_code"," ")).strip().upper()
    if not full_name or not code or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):return fail("Họ tên, mã sinh viên và email là bắt buộc.",422)
    try:
        db.execute("UPDATE users SET full_name=?,email=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(full_name,email,row["user_id"]))
        db.execute("UPDATE students SET student_code=?,class_name=?,faculty=?,phone=?,date_of_birth=?,gender=?,address=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(code,str(data.get("class_name",""))[:80],str(data.get("faculty",""))[:120],str(data.get("phone",""))[:30],str(data.get("date_of_birth",""))[:20],str(data.get("gender",""))[:30],str(data.get("address",""))[:300],student_id))
    except sqlite3.IntegrityError:return fail("Email hoặc mã sinh viên đã được sử dụng.",409)
    audit(g.user["id"],"update","student",student_id);return jsonify(ok=True)


@api.delete("/students/<int:user_id>")
@roles_required("admin")
def disable_student(user_id):
    result=get_db().execute("UPDATE users SET status='inactive',updated_at=CURRENT_TIMESTAMP WHERE id=? AND role='student'",(user_id,))
    if not result.rowcount:return fail("Không tìm thấy sinh viên.",404)
    return jsonify(ok=True)


@api.get("/lecturers")
@roles_required("admin")
def lecturers():
    q=str(request.args.get("q",""))[:80]
    rows=get_db().execute("SELECT l.*,u.username,u.email,u.full_name,u.status FROM lecturers l JOIN users u ON u.id=l.user_id WHERE u.full_name LIKE ? OR l.lecturer_code LIKE ? OR l.department LIKE ? ORDER BY u.full_name LIMIT 300",(f"%{q}%",)*3).fetchall()
    return jsonify(items=[dict(x) for x in rows])


@api.post("/lecturers")
@roles_required("admin")
def add_lecturer():
    uid,error=create_person("lecturer",body())
    if error:return fail(error,409 if "tồn tại" in error else 422)
    audit(g.user["id"],"create","lecturer",uid);return jsonify(id=uid),201


@api.get("/lecturers/<int:lecturer_id>")
@roles_required("admin")
def lecturer_detail(lecturer_id):
    row=get_db().execute("SELECT l.*,u.username,u.email,u.full_name,u.status FROM lecturers l JOIN users u ON u.id=l.user_id WHERE l.id=?",(lecturer_id,)).fetchone()
    return (jsonify(lecturer=dict(row)),200) if row else fail("Không tìm thấy giảng viên.",404)


@api.put("/lecturers/<int:lecturer_id>")
@roles_required("admin")
def update_lecturer(lecturer_id):
    data=body(); db=get_db()
    row=db.execute("SELECT user_id FROM lecturers WHERE id=?",(lecturer_id,)).fetchone()
    if not row:return fail("Không tìm thấy giảng viên.",404)
    full_name=str(data.get("full_name"," ")).strip();email=str(data.get("email"," ")).strip().lower();code=str(data.get("lecturer_code"," ")).strip().upper()
    if not full_name or not code or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):return fail("Họ tên, mã giảng viên và email là bắt buộc.",422)
    try:
        db.execute("UPDATE users SET full_name=?,email=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(full_name,email,row["user_id"]))
        db.execute("UPDATE lecturers SET lecturer_code=?,department=?,phone=?,position=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(code,str(data.get("department",""))[:120],str(data.get("phone",""))[:30],str(data.get("position",""))[:100],lecturer_id))
    except sqlite3.IntegrityError:return fail("Email hoặc mã giảng viên đã được sử dụng.",409)
    audit(g.user["id"],"update","lecturer",lecturer_id);return jsonify(ok=True)


@api.delete("/lecturers/<int:user_id>")
@roles_required("admin")
def disable_lecturer(user_id):
    result=get_db().execute("UPDATE users SET status='inactive',updated_at=CURRENT_TIMESTAMP WHERE id=? AND role='lecturer'",(user_id,))
    if not result.rowcount:return fail("Không tìm thấy giảng viên.",404)
    return jsonify(ok=True)


@api.get("/accounts")
@roles_required("admin")
def accounts():
    rows=get_db().execute("SELECT id,username,email,full_name,role,status,last_login_at,created_at FROM users ORDER BY role,full_name").fetchall()
    return jsonify(items=[dict(x) for x in rows])


@api.put("/accounts/<int:user_id>/status")
@roles_required("admin")
def account_status(user_id):
    status=body().get("status")
    if status not in {"active","inactive","locked"}:return fail("Trạng thái tài khoản chưa hợp lệ.",422)
    if user_id==g.user["id"] and status!="active":return fail("Bạn không thể khóa tài khoản đang sử dụng.",422)
    cur=get_db().execute("UPDATE users SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,user_id))
    if not cur.rowcount:return fail("Không tìm thấy tài khoản.",404)
    audit(g.user["id"],"account_status","user",user_id,status)
    return jsonify(ok=True)


@api.put("/accounts/<int:user_id>")
@roles_required("admin")
def update_account(user_id):
    data = body()
    username = str(data.get("username", "")).strip()
    full_name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", username):
        return fail("Tên đăng nhập cần dài từ 3 đến 50 ký tự; chỉ dùng chữ, số, dấu chấm, gạch dưới hoặc gạch ngang.", 422)
    if not full_name or len(full_name) > 120 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return fail("Họ tên và email chưa hợp lệ.", 422)
    if password and len(password) < 8:
        return fail("Mật khẩu mới cần có ít nhất 8 ký tự.", 422)
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
        return fail("Không tìm thấy tài khoản.", 404)
    try:
        if password:
            db.execute("UPDATE users SET username=?,full_name=?,email=?,password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (username, full_name, email, generate_password_hash(password), user_id))
        else:
            db.execute("UPDATE users SET username=?,full_name=?,email=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (username, full_name, email, user_id))
    except sqlite3.IntegrityError:
        return fail("Tên đăng nhập hoặc email đã được sử dụng.", 409)
    audit(g.user["id"], "update_account", "user", user_id,
          "profile and password reset" if password else "profile")
    return jsonify(ok=True)


@api.get("/export/<kind>.csv")
@roles_required("admin","lecturer")
def export_csv(kind):
    db=get_db(); specs={
      "students":("SELECT s.student_code,u.full_name,u.email,s.class_name,s.faculty,s.phone,u.status FROM students s JOIN users u ON u.id=s.user_id ORDER BY u.full_name",[]),
      "activities":("SELECT title,category,organizer,location,start_time,end_time,status,max_participants,activity_points FROM activities WHERE status!='cancelled' ORDER BY start_time",[]),
      "registrations":("SELECT a.title,u.full_name,s.student_code,r.status,r.registered_at FROM registrations r JOIN activities a ON a.id=r.activity_id JOIN students s ON s.id=r.student_id JOIN users u ON u.id=s.user_id ORDER BY r.registered_at DESC",[]),
      "attendance":("SELECT a.title,u.full_name,s.student_code,at.status,at.check_in_time,at.note FROM attendance at JOIN registrations r ON r.id=at.registration_id JOIN activities a ON a.id=r.activity_id JOIN students s ON s.id=r.student_id JOIN users u ON u.id=s.user_id ORDER BY a.start_time",[]),
      "scores":("SELECT a.title,u.full_name,s.student_code,sc.score,a.activity_points,sc.note FROM activity_scores sc JOIN registrations r ON r.id=sc.registration_id JOIN activities a ON a.id=r.activity_id JOIN students s ON s.id=r.student_id JOIN users u ON u.id=s.user_id ORDER BY a.title,u.full_name",[])}
    if kind not in specs:return fail("Loại báo cáo chưa được hỗ trợ.",404)
    sql,params=specs[kind]
    if g.user["role"]=="lecturer" and kind!="students":
        clause=" AND a.created_by=? ORDER BY" if " WHERE " in sql else " WHERE a.created_by=? ORDER BY"
        sql=sql.replace(" ORDER BY",clause,1);params=[g.user["id"]]
    elif g.user["role"]=="lecturer" and kind=="students":return fail("Bạn không có quyền xuất danh sách toàn trường.",403)
    rows=db.execute(sql,params).fetchall(); output=io.StringIO(); output.write("\ufeff"); writer=csv.writer(output)
    if rows:writer.writerow(rows[0].keys());writer.writerows([tuple(row) for row in rows])
    return current_app.response_class(output.getvalue(),mimetype="text/csv; charset=utf-8",headers={"Content-Disposition":f"attachment; filename={kind}.csv"})


@api.get("/backup")
@roles_required("admin")
def backup():
    folder=Path(current_app.instance_path)/"backups";folder.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S");dest=sqlite3.connect(folder/f"app_{stamp}.db")
    try:get_db().backup(dest)
    finally:dest.close()
    audit(g.user["id"],"backup","database",stamp)
    return send_file(folder/f"app_{stamp}.db",as_attachment=True,download_name=f"app_{stamp}.db",mimetype="application/vnd.sqlite3")


@api.post("/restore")
@roles_required("admin")
def restore():
    uploaded=request.files.get("database")
    if not uploaded:return fail("Vui lòng chọn tệp sao lưu SQLite.",422)
    folder=Path(current_app.instance_path)/"backups";folder.mkdir(parents=True,exist_ok=True)
    temp=folder/"restore_upload.tmp"
    uploaded.save(temp)
    try:
        source=sqlite3.connect(f"file:{temp}?mode=ro",uri=True)
        integrity=source.execute("PRAGMA integrity_check").fetchone()[0]
        names={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if integrity!="ok" or not {"users","activities","registrations"}.issubset(names):
            source.close();temp.unlink(missing_ok=True);return fail("Tệp sao lưu không hợp lệ hoặc thiếu bảng dữ liệu.",422)
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S");dest=sqlite3.connect(folder/f"app_{stamp}.db")
        get_db().backup(dest);dest.close()
        source.backup(get_db());source.close()
        temp.unlink(missing_ok=True);audit(g.user["id"],"restore","database",stamp)
        return jsonify(ok=True,message="Đã khôi phục dữ liệu và lưu bản dự phòng trước đó.")
    except sqlite3.DatabaseError:
        temp.unlink(missing_ok=True);return fail("Không thể đọc tệp sao lưu SQLite.",422)

