import json
import base64
from datetime import datetime, timedelta, time
from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import generate_password_hash
from config import Config
from .database import close_db, get_db, init_db
from .security import current_user


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["SECRET_KEY"] = Config.secret_key()
    if test_config:
        app.config.update(test_config)
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()
        seed_if_empty()
        if not app.config.get("TESTING"):
            seed_demo_expansion()

    @app.before_request
    def csrf_guard():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.endpoint != "api.login":
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or supplied != session.get("csrf_token"):
                return jsonify(error="Phiên làm việc hết hạn. Vui lòng tải lại trang."), 400

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Không tìm thấy dữ liệu hoặc địa chỉ yêu cầu."), 404
        return render_template("index.html", csrf_token=session.get("csrf_token", "")), 404

    @app.errorhandler(500)
    def internal_error(_error):
        app.logger.exception("Unhandled application error")
        if request.path.startswith("/api/"):
            return jsonify(error="Máy chủ đang gặp sự cố. Vui lòng thử lại sau."), 500
        return "Máy chủ đang gặp sự cố. Vui lòng thử lại sau.", 500

    @app.get("/")
    def index():
        if not session.get("csrf_token"):
            import secrets
            session["csrf_token"] = secrets.token_urlsafe(24)
        return render_template("index.html", csrf_token=session["csrf_token"])

    @app.get("/api/csrf")
    def csrf_token():
        if not session.get("csrf_token"):
            import secrets
            session["csrf_token"] = secrets.token_urlsafe(24)
        return jsonify(token=session["csrf_token"])

    from .routes import api
    app.register_blueprint(api, url_prefix="/api")
    return app


def seed_if_empty():
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    demos = [
        ("admin", "admin@demo.edu.vn", "admin123", "Quản trị viên", "admin"),
        ("giangvien", "giangvien@demo.edu.vn", "gv123456", "Nguyễn Minh Anh", "lecturer"),
        ("sinhvien", "sinhvien@demo.edu.vn", "sv123456", "Trần Gia Hân", "student"),
        ("sinhvien2", "sinhvien2@demo.edu.vn", "sv123456", "Lê Hoàng Nam", "student"),
    ]
    ids = {}
    for username, email, password, name, role in demos:
        cur = db.execute("INSERT INTO users(username,email,password_hash,full_name,role) VALUES(?,?,?,?,?)",
                         (username,email,generate_password_hash(password),name,role))
        ids[username] = cur.lastrowid
    db.execute("INSERT INTO lecturers(user_id,lecturer_code,department,phone,position) VALUES(?,?,?,?,?)",
               (ids["giangvien"],"GV001","Công tác sinh viên","0901000001","Giảng viên"))
    db.execute("INSERT INTO students(user_id,student_code,class_name,faculty,phone) VALUES(?,?,?,?,?)",
               (ids["sinhvien"],"SV001","CNTT-K21","Công nghệ thông tin","0902000001"))
    db.execute("INSERT INTO students(user_id,student_code,class_name,faculty,phone) VALUES(?,?,?,?,?)",
               (ids["sinhvien2"],"SV002","CNTT-K21","Công nghệ thông tin","0902000002"))
    db.execute("INSERT INTO activities(title,description,category,organizer,location,start_time,end_time,registration_deadline,max_participants,activity_points,status,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               ("Ngày hội Chào tân sinh viên","Gặp gỡ, kết nối và khám phá các câu lạc bộ trong trường.","Cộng đồng","Đoàn trường","Sân trung tâm","2026-11-15T08:00","2026-11-15T11:30","2026-11-12T23:59",180,5,"open",ids["giangvien"]))
    db.execute("INSERT INTO activities(title,description,category,organizer,location,start_time,end_time,registration_deadline,max_participants,activity_points,status,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               ("Workshop AI ứng dụng","Chia sẻ kiến thức và thực hành cùng khách mời.","Học thuật","Khoa CNTT","Hội trường A","2026-11-20T13:30","2026-11-20T16:00","2026-11-18T23:59",80,8,"open",ids["giangvien"]))
    db.execute("INSERT INTO system_settings(setting_key,setting_value) VALUES('theme_defaults',?)",
               (json.dumps({"primary":"#286aa8","accent":"#b9714f","mode":"light","radius":12,"glass":False,"shadow":True,"animation":True,"three":True}),))


def _demo_avatar(seed):
    backgrounds = ["#E9DDC4", "#D7E3D9", "#EAD6C9", "#D7DFE8", "#EFE0B7", "#D9D2E5"]
    skins = ["#F1C8A6", "#DCA987", "#BC8063", "#E8B994", "#D49B78"]
    hairs = ["#302A27", "#47372E", "#685345", "#262C35", "#7C5738"]
    bg, skin, hair = backgrounds[seed % len(backgrounds)], skins[seed % len(skins)], hairs[(seed * 3) % len(hairs)]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
           f'<rect width="120" height="120" rx="60" fill="{bg}"/>'
           f'<path d="M17 120c3-25 18-38 43-38s40 13 43 38" fill="{["#315C52", "#8C513D", "#394A61", "#A46B3D"][seed % 4]}"/>'
           f'<path d="M34 48c0-22 12-34 27-34 18 0 29 14 27 37l-4 17H37z" fill="{hair}"/>'
           f'<ellipse cx="60" cy="53" rx="23" ry="29" fill="{skin}"/>'
           f'<path d="M37 48c1-24 12-34 27-34 16 0 25 11 26 28-8-3-15-9-19-16-8 10-19 16-34 18z" fill="{hair}"/>'
           '<circle cx="51" cy="54" r="1.8" fill="#3D332E"/><circle cx="69" cy="54" r="1.8" fill="#3D332E"/>'
           '<path d="M54 67c4 3 8 3 12 0" fill="none" stroke="#9E5E52" stroke-width="2" stroke-linecap="round"/>'
           '<path d="M44 44c4-3 8-3 12-1m9 0c4-2 8-2 12 1" fill="none" stroke="#46382F" stroke-width="2" stroke-linecap="round"/>'
           '</svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def _save_seed_avatar(db, user_id, seed):
    db.execute("INSERT OR IGNORE INTO user_settings(user_id,setting_key,setting_value) VALUES(?,?,?)",
               (user_id, "avatar_data", _demo_avatar(seed)))


def seed_demo_expansion():
    """Add a local demonstration community without resetting existing records."""
    db = get_db()
    now = datetime.now().replace(second=0, microsecond=0)
    student_names = [
        "Nguyễn Minh Châu", "Phạm Hoàng Long", "Đỗ Ngọc Mai", "Vũ Đức Anh", "Bùi Khánh Linh",
        "Lê Quang Huy", "Trần Hải Yến", "Đặng Nhật Minh", "Phan Thu Hà", "Hoàng Gia Bảo",
        "Nguyễn Thùy Dương", "Đinh Công Thành", "Lương Bảo Ngọc", "Trịnh Minh Khang", "Mai Phương Anh",
        "Đào Tuấn Kiệt", "Võ Diệu Linh", "Ngô Đức Mạnh", "Cao Hà My", "Tạ Quang Vinh",
        "Dương Thanh Tâm", "Chu Hải Đăng", "Hà Ngọc Ánh", "Lý Minh Quân", "Tô Khánh Vy",
        "Nguyễn Phúc An", "Phạm Ngọc Hân", "Đỗ Thành Đạt", "Vũ Thu Trang", "Bùi Quốc Bảo",
        "Lê Hương Giang", "Trần Gia Khánh", "Đặng Thảo Nhi", "Phan Anh Tuấn", "Hoàng Bích Ngọc",
        "Nguyễn Duy Khánh", "Đinh Thanh Thảo", "Lương Minh Đức", "Trịnh Hải Anh", "Mai Quốc Việt",
        "Đào Ngọc Diệp", "Võ Thành Công", "Ngô Phương Thảo", "Cao Minh Nhật", "Tạ Bảo Trân",
        "Dương Đức Huy", "Chu Ngọc Lan", "Hà Anh Khoa", "Lý Thu Uyên", "Tô Quang Minh",
    ]
    lecturer_names = [
        "Nguyễn Minh Anh", "Trần Quốc Bảo", "Lê Thu Hương", "Phạm Đức Thành", "Vũ Ngọc Lan",
        "Đỗ Quang Huy", "Hoàng Thanh Hà", "Bùi Văn Nam", "Đặng Thị Mai", "Phan Tuấn Dũng",
        "Ngô Hải Yến", "Cao Minh Đức", "Lương Thu Trang", "Tạ Hoàng Sơn", "Dương Bảo Châu",
        "Chu Thành Long", "Hà Phương Linh", "Lý Đức Tâm", "Tô Ngọc Mai", "Đào Quang Vinh",
        "Võ Thu Hiền", "Trịnh Hải Nam", "Mai Minh Khoa", "Nguyễn Bích Ngọc", "Phạm Anh Tuấn",
        "Lê Khánh Ly", "Đinh Quốc Hưng", "Hoàng Thùy Dung", "Bùi Gia Khánh", "Đặng Minh Tâm",
    ]
    faculties = ["Công nghệ thông tin", "Kinh tế và Quản trị kinh doanh", "Du lịch", "Ngoại ngữ", "Công nghệ và Kỹ thuật"]
    departments = ["Công tác sinh viên", "Công nghệ thông tin", "Công nghệ và Kỹ thuật", "Du lịch", "Kinh tế"]

    try:
        db.execute("BEGIN IMMEDIATE")
        new_theme = json.dumps({"primary":"#286aa8","accent":"#b9714f","mode":"light","radius":12,"glass":False,"shadow":True,"animation":True,"three":True})
        db.execute("INSERT INTO system_settings(setting_key,setting_value) VALUES('theme_defaults',?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value", (new_theme,))
        db.execute("UPDATE user_settings SET setting_value='\"#286aa8\"' WHERE setting_key='primary' AND setting_value='\"#6558d3\"'")
        db.execute("UPDATE user_settings SET setting_value='\"#b9714f\"' WHERE setting_key='accent' AND setting_value='\"#39a994\"'")
        db.execute("UPDATE user_settings SET setting_value='12' WHERE setting_key='radius' AND setting_value='18'")
        db.execute("UPDATE user_settings SET setting_value='false' WHERE setting_key='glass' AND setting_value='true'")
        active_students = db.execute("SELECT COUNT(*) FROM students s JOIN users u ON u.id=s.user_id WHERE u.status='active'").fetchone()[0]
        used_student_codes = {r[0] for r in db.execute("SELECT student_code FROM students")}
        used_usernames = {r[0] for r in db.execute("SELECT username FROM users")}
        serial = 1
        while active_students < 50:
            code = f"SV{serial:03d}"
            username = f"sv{serial:03d}"
            serial += 1
            if code in used_student_codes or username in used_usernames:
                continue
            idx = (serial - 2) % len(student_names)
            email = f"{username}@hpu.edu.vn"
            cur = db.execute("INSERT INTO users(username,email,password_hash,full_name,role) VALUES(?,?,?,?,?)",
                             (username, email, generate_password_hash("sv123456"), student_names[idx], "student"))
            user_id = cur.lastrowid
            db.execute("INSERT INTO students(user_id,student_code,class_name,faculty,phone) VALUES(?,?,?,?,?)",
                       (user_id, code, f"TNV-K27-{idx % 4 + 1:02d}", faculties[idx % len(faculties)], f"09{20000000 + serial:08d}"))
            _save_seed_avatar(db, user_id, serial)
            used_student_codes.add(code); used_usernames.add(username); active_students += 1

        active_lecturers = db.execute("SELECT COUNT(*) FROM lecturers l JOIN users u ON u.id=l.user_id WHERE u.status='active'").fetchone()[0]
        used_lecturer_codes = {r[0] for r in db.execute("SELECT lecturer_code FROM lecturers")}
        serial = 1
        while active_lecturers < 30:
            code = f"GV{serial:03d}"
            username = f"gv{serial:03d}"
            serial += 1
            if code in used_lecturer_codes or username in used_usernames:
                continue
            idx = (serial - 2) % len(lecturer_names)
            email = f"{username}@hpu.edu.vn"
            cur = db.execute("INSERT INTO users(username,email,password_hash,full_name,role) VALUES(?,?,?,?,?)",
                             (username, email, generate_password_hash("gv123456"), lecturer_names[idx], "lecturer"))
            user_id = cur.lastrowid
            db.execute("INSERT INTO lecturers(user_id,lecturer_code,department,phone,position) VALUES(?,?,?,?,?)",
                       (user_id, code, departments[idx % len(departments)], f"09{10000000 + serial:08d}", "Giảng viên phụ trách tình nguyện"))
            _save_seed_avatar(db, user_id, 100 + serial)
            used_lecturer_codes.add(code); used_usernames.add(username); active_lecturers += 1

        for row in db.execute("SELECT id,role FROM users WHERE role IN ('admin','student','lecturer')"):
            _save_seed_avatar(db, row["id"], row["id"] + (100 if row["role"] == "lecturer" else 0))

        seed_marker = db.execute("SELECT setting_value FROM system_settings WHERE setting_key='volunteer_demo_seed_v1'").fetchone()
        if not seed_marker:
            activity_specs = [
                ("Bếp ấm cuối tuần", "Chuẩn bị và trao suất ăn sáng cho người lao động khó khăn.", "Cộng đồng", "Nhà văn hóa phường Dư Hàng Kênh"),
                ("Chủ nhật xanh bên hồ Tam Bạc", "Thu gom rác, phân loại chai nhựa và làm sạch lối đi bộ.", "Môi trường", "Khu vực hồ Tam Bạc"),
                ("Tiếp sức học sinh đến trường", "Tặng sách vở và hướng dẫn kỹ năng học tập cho thiếu nhi.", "Giáo dục", "Nhà văn hóa thiếu nhi Hải Phòng"),
                ("Tủ sách sẻ chia", "Phân loại sách cũ và xây dựng tủ sách cộng đồng.", "Giáo dục", "Trường Đại học Hải Phòng"),
                ("Hiến máu tình nguyện HPU", "Hỗ trợ đăng ký, hướng dẫn quy trình và chăm sóc người hiến máu.", "Sức khỏe", "Nhà A, Trường Đại học Hải Phòng"),
                ("Áo ấm đến vùng cao", "Phân loại áo ấm, đồ dùng học tập và chuẩn bị chuyến trao tặng.", "Thiện nguyện", "Trung tâm công tác sinh viên HPU"),
                ("Góc phố sạch, hàng cây xanh", "Quét dọn, chăm sóc bồn cây và nhắc nhở phân loại rác.", "Môi trường", "Phường Lạch Tray"),
                ("Đồng hành cùng em đọc sách", "Đọc sách cùng trẻ em và tổ chức trò chơi học từ mới.", "Giáo dục", "Thư viện cộng đồng Lê Chân"),
                ("Bữa cơm sẻ chia", "Nấu và đóng gói bữa trưa hỗ trợ người bệnh và thân nhân.", "Cộng đồng", "Bệnh viện Kiến An"),
                ("Ngày hội đổi rác lấy cây", "Hướng dẫn tái chế và trao cây xanh cho người tham gia.", "Môi trường", "Sân trường Đại học Hải Phòng"),
                ("Hỗ trợ người cao tuổi dùng điện thoại", "Hướng dẫn thao tác cơ bản, gọi video và nhận biết tin nhắn lừa đảo.", "Cộng đồng", "Nhà văn hóa quận Ngô Quyền"),
                ("Đội hình hỗ trợ mùa thi", "Hướng dẫn thí sinh tìm phòng thi và điểm hỗ trợ nước uống.", "Giáo dục", "Cổng Trường Đại học Hải Phòng"),
                ("Thăm hỏi gia đình chính sách", "Gửi lời thăm hỏi và hỗ trợ dọn dẹp khuôn viên gia đình.", "Thiện nguyện", "Phường An Biên"),
                ("Trồng cây tại sân trường", "Trồng bổ sung cây bóng mát và ghi nhận vị trí chăm sóc định kỳ.", "Môi trường", "Khuôn viên HPU"),
                ("Ngày hội kỹ năng sơ cứu", "Trải nghiệm sơ cứu cơ bản cùng hướng dẫn viên và nhân viên y tế.", "Sức khỏe", "Nhà đa năng HPU"),
                ("Gói quà Trung thu cho em", "Chuẩn bị quà và tổ chức hoạt động đọc sách, vẽ tranh.", "Thiện nguyện", "Phường Trại Cau"),
                ("Hỗ trợ phân luồng sự kiện cộng đồng", "Đón tiếp, hướng dẫn lối đi và hỗ trợ người lớn tuổi.", "Cộng đồng", "Cung Văn hóa Lao động Hữu nghị Việt Tiệp"),
                ("Dạy tin học căn bản", "Hướng dẫn học sinh tạo tài liệu và sử dụng Internet an toàn.", "Giáo dục", "Trường THCS Trần Phú"),
                ("Làm sạch bãi biển Đồ Sơn", "Nhặt rác theo khu vực, cân và ghi nhận lượng rác tái chế.", "Môi trường", "Bãi biển Đồ Sơn"),
                ("Gian hàng 0 đồng", "Sắp xếp nhu yếu phẩm và hỗ trợ người dân lựa chọn đồ dùng.", "Cộng đồng", "Nhà văn hóa phường Cầu Đất"),
                ("Ngày hội vận động vì sức khỏe", "Hướng dẫn đăng ký, đo chỉ số cơ bản và điều phối trạm nước.", "Sức khỏe", "Công viên Nguyễn Trãi"),
                ("Tặng sách và đồ dùng học tập", "Kiểm kê, đóng gói và trao tặng dụng cụ học tập.", "Giáo dục", "Trung tâm công tác xã hội Hải Phòng"),
                ("Hỗ trợ người dân làm thủ tục trực tuyến", "Hướng dẫn tra cứu dịch vụ công và thao tác trên điện thoại.", "Cộng đồng", "Bộ phận một cửa phường Lạch Tray"),
                ("Chăm sóc vườn cây cộng đồng", "Tưới cây, làm cỏ và bổ sung bảng hướng dẫn chăm sóc.", "Môi trường", "Vườn hoa Nguyễn Du"),
                ("Gói bánh sẻ chia", "Chuẩn bị thực phẩm, đóng gói và chuyển quà tới mái ấm địa phương.", "Thiện nguyện", "Trung tâm công tác sinh viên HPU"),
                ("Tập huấn an toàn giao thông học đường", "Hỗ trợ trò chơi tình huống và hướng dẫn đội mũ bảo hiểm đúng cách.", "Giáo dục", "Trường Tiểu học Lê Hồng Phong"),
                ("Phiên chợ xanh sinh viên", "Thu gom giấy, pin đã qua sử dụng và giới thiệu điểm tái chế.", "Môi trường", "Sân trung tâm HPU"),
                ("Đồng hành cùng bệnh nhi", "Đọc truyện, vẽ tranh và chuẩn bị góc sinh hoạt nhẹ nhàng.", "Cộng đồng", "Bệnh viện Trẻ em Hải Phòng"),
                ("Ngày hội sẻ chia dịp cuối năm", "Tổng hợp đồ quyên góp và trao tặng theo danh sách đăng ký.", "Thiện nguyện", "Trung tâm công tác sinh viên HPU"),
                ("Tổng kết mùa tình nguyện", "Ghi nhận số giờ, chia sẻ kinh nghiệm và đề xuất hoạt động mới.", "Cộng đồng", "Hội trường A, Trường Đại học Hải Phòng"),
            ]
            date_offsets = [-42,-38,-34,-30,-27,-24,-21,-18,-15,-12,-9,-6,-3,1,3,5,7,10,13,16,19,22,25,28,31,34,37,40,44,48]
            times = [(8,0),(8,30),(9,0),(13,30),(8,0),(14,0)]
            lecturer_rows = db.execute("SELECT l.id,l.user_id FROM lecturers l JOIN users u ON u.id=l.user_id WHERE u.status='active' ORDER BY l.id").fetchall()
            student_rows = db.execute("SELECT s.id FROM students s JOIN users u ON u.id=s.user_id WHERE u.status='active' ORDER BY s.id").fetchall()
            seed_activity_ids = []
            for idx, spec in enumerate(activity_specs):
                title, description, category, location = spec
                offset = date_offsets[idx]
                day = now.date() + timedelta(days=offset)
                hour, minute = times[idx % len(times)]
                start = datetime.combine(day, time(hour, minute))
                end = start + timedelta(hours=2 if hour >= 13 else 2.5)
                deadline = start - timedelta(days=3)
                status = "completed" if start < now else "open"
                owner = lecturer_rows[idx % len(lecturer_rows)]["user_id"]
                cur = db.execute("INSERT INTO activities(title,description,category,organizer,location,start_time,end_time,registration_deadline,max_participants,activity_points,status,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (title, description, category, "Đoàn Thanh niên - Hội Sinh viên HPU", location,
                                  start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"), deadline.isoformat(timespec="minutes"),
                                  24 + (idx % 5) * 4, 3 + (idx % 4), status, owner, owner))
                activity_id = cur.lastrowid
                seed_activity_ids.append(activity_id)
                for student_idx, student in enumerate(student_rows):
                    if (student_idx * 7 + idx * 11) % 17 >= 6:
                        continue
                    registration_state = "approved" if status == "completed" or (student_idx + idx) % 3 else "pending"
                    registered_at = start - timedelta(days=8)
                    db.execute("INSERT OR IGNORE INTO registrations(activity_id,student_id,status,registered_at,reviewed_by,reviewed_at) VALUES(?,?,?,?,?,?)",
                               (activity_id, student["id"], registration_state, registered_at.isoformat(sep=" "), owner if registration_state == "approved" else None,
                                min(now, start - timedelta(days=2)).isoformat(sep=" ") if registration_state == "approved" else None))
                    if status == "completed" and registration_state == "approved":
                        registration = db.execute("SELECT id FROM registrations WHERE activity_id=? AND student_id=?", (activity_id, student["id"])).fetchone()
                        attendance_status = "late" if (student_idx + idx) % 9 == 0 else "present"
                        check_in = (start + timedelta(minutes=10 if attendance_status == "late" else 2)).isoformat(sep=" ")
                        db.execute("INSERT OR IGNORE INTO attendance(registration_id,status,check_in_time,note,marked_by) VALUES(?,?,?,?,?)",
                                   (registration["id"], attendance_status, check_in, "Dữ liệu minh họa cho hoạt động tình nguyện.", owner))
                        points = round((3 + (idx % 4)) * (0.7 + (student_idx % 4) * 0.07), 1)
                        db.execute("INSERT OR IGNORE INTO activity_scores(registration_id,score,note,created_by) VALUES(?,?,?,?)",
                                   (registration["id"], points, "Hoàn thành nhiệm vụ tình nguyện.", owner))
            admin_id = db.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()[0]
            notices = [
                ("Mở đăng ký hoạt động tình nguyện", "Các hoạt động cộng đồng và môi trường đã có lịch mới. Hãy chọn ca phù hợp trước hạn đăng ký.", "activity"),
                ("Cảm ơn đội hình Chủ nhật xanh", "Cảm ơn các bạn đã cùng làm sạch khu vực hồ Tam Bạc và phân loại rác tái chế.", "general"),
                ("Hướng dẫn ghi nhận giờ tham gia", "Giờ tình nguyện được ghi nhận sau khi người phụ trách điểm danh hoàn tất.", "general"),
                ("Cập nhật lịch hiến máu HPU", "Vui lòng xem thời gian tập trung và địa điểm trong chi tiết hoạt động trước khi đăng ký.", "activity"),
                ("Nhắc nhở trước ngày hoạt động", "Có mặt trước giờ bắt đầu khoảng 10 phút để nhận nhiệm vụ và hướng dẫn an toàn.", "activity"),
                ("Chia sẻ câu chuyện tình nguyện", "Trang cá nhân của bạn sẽ lưu hoạt động đã tham gia, điểm đóng góp và ảnh đại diện.", "general"),
            ]
            for idx, (title, content, kind) in enumerate(notices):
                db.execute("INSERT INTO notifications(title,content,type,created_by,related_activity_id) VALUES(?,?,?,?,?)",
                           (title, content, kind, admin_id, seed_activity_ids[idx]))
            db.execute("INSERT INTO system_settings(setting_key,setting_value) VALUES('volunteer_demo_seed_v1','done')")
        db.commit()
    except Exception:
        db.rollback()
        raise

