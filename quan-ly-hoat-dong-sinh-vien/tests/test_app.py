import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from app import create_app


class ActivitySystemTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({"TESTING": True, "DATABASE": self.db_path, "SECRET_KEY": "unit-test-secret"})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self, username, password):
        response = self.client.post("/api/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.csrf = response.get_json()["csrf_token"]
        return {"X-CSRF-Token": self.csrf}

    def test_protected_dashboard_requires_session(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)

    def test_demo_login_and_role_are_read_from_database(self):
        self.login("sinhvien", "sv123456")
        response = self.client.get("/api/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["role"], "student")

    def test_student_cannot_create_activity(self):
        headers = self.login("sinhvien", "sv123456")
        response = self.client.post("/api/activities", json={"title":"Không được phép"}, headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_activity_creation_and_restart_persistence(self):
        headers = self.login("giangvien", "gv123456")
        payload = {"title":"Buổi sinh hoạt kỹ năng","category":"Cộng đồng","organizer":"Đoàn trường",
                   "location":"Hội trường B","start_time":"2026-12-10T09:00","end_time":"2026-12-10T11:00",
                   "registration_deadline":"2026-12-08T23:59","max_participants":40,"activity_points":4,"status":"open"}
        response = self.client.post("/api/activities", json=payload, headers=headers)
        self.assertEqual(response.status_code, 201, response.get_json())
        activity_id = response.get_json()["id"]
        second_app = create_app({"TESTING": True, "DATABASE": self.db_path, "SECRET_KEY": "unit-test-secret"})
        with second_app.test_client() as client:
            client.post("/api/login", json={"username":"giangvien","password":"gv123456"})
            result = client.get(f"/api/activities/{activity_id}")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.get_json()["activity"]["title"], payload["title"])

    def test_duplicate_registration_is_rejected(self):
        headers = self.login("sinhvien", "sv123456")
        activity = self.client.get("/api/activities").get_json()["items"][0]
        payload = {"activity_id": activity["id"]}
        first = self.client.post("/api/registrations", json=payload, headers=headers)
        self.assertEqual(first.status_code, 201, first.get_json())
        second = self.client.post("/api/registrations", json=payload, headers=headers)
        self.assertEqual(second.status_code, 409)

    def test_theme_rejects_invalid_colors_and_persists_valid_choice(self):
        headers = self.login("sinhvien", "sv123456")
        invalid = self.client.put("/api/settings/theme", json={"primary":"red"}, headers=headers)
        self.assertEqual(invalid.status_code, 422)
        valid = self.client.put("/api/settings/theme", json={"primary":"#1256AB","mode":"dark"}, headers=headers)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(self.client.get("/api/settings/theme").get_json()["theme"]["primary"], "#1256AB")

    def test_account_management_is_admin_only(self):
        headers = self.login("sinhvien", "sv123456")
        self.assertEqual(self.client.get("/api/accounts").status_code, 403)
        self.assertTrue(headers["X-CSRF-Token"])

    def test_admin_can_edit_account_and_reset_password_persistently(self):
        headers = self.login("admin", "admin123")
        account = next(x for x in self.client.get("/api/accounts").get_json()["items"] if x["username"] == "sinhvien")
        response = self.client.put(f"/api/accounts/{account['id']}", json={
            "username":"sinhvien_moi", "full_name":"Trần Gia Hân mới", "email":"han.moi@hpu.edu.vn",
            "password":"svmoi1234"
        }, headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        activity_id = self.client.get("/api/activities").get_json()["items"][0]["id"]
        changed_activity = self.client.put(f"/api/activities/{activity_id}", json={"title":"Admin đã cập nhật hoạt động"}, headers=headers)
        self.assertEqual(changed_activity.status_code, 200, changed_activity.get_json())

        second_app = create_app({"TESTING": True, "DATABASE": self.db_path, "SECRET_KEY": "unit-test-secret"})
        with second_app.test_client() as client:
            login = client.post("/api/login", json={"username":"sinhvien_moi", "password":"svmoi1234"})
            self.assertEqual(login.status_code, 200, login.get_json())
            self.assertEqual(login.get_json()["user"]["full_name"], "Trần Gia Hân mới")
            self.assertEqual(login.get_json()["user"]["email"], "han.moi@hpu.edu.vn")
            admin = client.post("/api/login", json={"username":"admin", "password":"admin123"})
            self.assertEqual(admin.status_code, 200)
            activity = client.get(f"/api/activities/{activity_id}")
            self.assertEqual(activity.status_code, 200)
            self.assertEqual(activity.get_json()["activity"]["title"], "Admin đã cập nhật hoạt động")

    def test_registration_approval_attendance_and_score(self):
        student_headers = self.login("sinhvien", "sv123456")
        activity_id = self.client.get("/api/activities").get_json()["items"][0]["id"]
        registered = self.client.post("/api/registrations", json={"activity_id":activity_id}, headers=student_headers)
        self.assertEqual(registered.status_code, 201)
        registration_id = registered.get_json()["id"]
        lecturer_headers = self.login("giangvien", "gv123456")
        self.assertEqual(self.client.put(f"/api/registrations/{registration_id}/approve", json={}, headers=lecturer_headers).status_code, 200)
        attendance = self.client.post("/api/attendance", json={"registration_id":registration_id,"status":"present"}, headers=lecturer_headers)
        self.assertEqual(attendance.status_code, 200, attendance.get_json())
        score = self.client.post("/api/scores", json={"registration_id":registration_id,"score":4,"note":"Tham gia tích cực"}, headers=lecturer_headers)
        self.assertEqual(score.status_code, 200, score.get_json())

    def test_broadcast_read_state_is_individual(self):
        admin_headers = self.login("admin", "admin123")
        created = self.client.post("/api/notifications", json={"title":"Lịch sinh hoạt","content":"Cập nhật lịch tuần này."}, headers=admin_headers)
        self.assertEqual(created.status_code, 201)
        notification_id = created.get_json()["id"]
        student_headers = self.login("sinhvien", "sv123456")
        self.assertFalse(self.client.get("/api/notifications").get_json()["items"][0]["is_read"])
        self.assertEqual(self.client.put(f"/api/notifications/{notification_id}/read", json={}, headers=student_headers).status_code, 200)
        self.assertTrue(self.client.get("/api/notifications").get_json()["items"][0]["is_read"])
        self.login("sinhvien2", "sv123456")
        other_items = self.client.get("/api/notifications").get_json()["items"]
        self.assertFalse(next(x for x in other_items if x["id"]==notification_id)["is_read"])

    def test_backup_and_restore_keep_a_recovery_copy(self):
        headers = self.login("admin", "admin123")
        snapshot = self.client.get("/api/backup")
        self.assertEqual(snapshot.status_code, 200)
        backup_bytes = snapshot.data
        snapshot.close()
        self.assertGreater(len(backup_bytes), 100)
        self.client.post("/api/activities", json={"title":"Temporary","category":"Khác","organizer":"Test",
                           "location":"Test","start_time":"2026-12-10T09:00","end_time":"2026-12-10T11:00",
                           "registration_deadline":"2026-12-08T23:59","max_participants":30,"activity_points":1,"status":"open"},headers=headers)
        restored = self.client.post("/api/restore", data={"database":(BytesIO(backup_bytes),"snapshot.db")},headers=headers,content_type="multipart/form-data")
        self.assertEqual(restored.status_code,200,restored.get_json())
        self.assertNotIn("Temporary",[x["title"] for x in self.client.get("/api/activities").get_json()["items"]])


if __name__ == "__main__":
    unittest.main()
