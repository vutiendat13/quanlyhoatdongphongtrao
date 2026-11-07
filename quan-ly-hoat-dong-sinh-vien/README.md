# Tình nguyện HPU — Quản lý hoạt động phong trào tình nguyện

Ứng dụng Flask chạy trên Windows, dùng SQLite lưu dữ liệu tại `instance/app.db`. Giao diện lấy bố cục dashboard quản lý làm tham khảo, dùng màu xanh HPU, nền sáng và tập trung vào hoạt động tình nguyện của sinh viên, giảng viên Trường Đại học Hải Phòng.

## Chạy trên Windows

1. Cài Python 3.10 trở lên và bật tùy chọn **Add Python to PATH** khi cài.
2. Nhấp đúp `run.bat`. Lần đầu ứng dụng tạo môi trường `.venv` và cài Flask.
3. Mở [http://127.0.0.1:5000](http://127.0.0.1:5000).
4. Giữ cửa sổ chạy ứng dụng mở trong lúc sử dụng; nhấn `Ctrl+C` để dừng.

Có thể khởi động thủ công từ thư mục dự án:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Ứng dụng lưu khóa session riêng trong `instance/.secret_key` ở lần chạy đầu. Có thể đặt biến `FLASK_SECRET_KEY` trước khi chạy nếu muốn tự quản lý khóa. Không đưa khóa này hoặc database thật lên kho mã nguồn.

## Tài khoản demo

| Vai trò | Tên đăng nhập | Mật khẩu |
|---|---|---|
| Quản trị viên | `admin` | `admin123` |
| Giảng viên | `giangvien` | `gv123456` |
| Sinh viên | `sinhvien` | `sv123456` |
| Sinh viên thứ hai | `sinhvien2` | `sv123456` |
| Sinh viên mẫu | `sv003` đến `sv050` | `sv123456` |
| Giảng viên mẫu | `gv002` đến `gv030` | `gv123456` |

Sinh viên có thể tự đăng ký bằng nút **Tạo tài khoản sinh viên** ở màn hình đăng nhập; tài khoản mới luôn nhận vai trò sinh viên. Khi khởi động, ứng dụng bổ sung dữ liệu mẫu để có tối thiểu 50 sinh viên và 30 giảng viên đang hoạt động, cùng 30 hoạt động tình nguyện và các lượt đăng ký/điểm danh minh họa. Dữ liệu hiện có được giữ nguyên; bộ mẫu chỉ được thêm một lần. Đổi mật khẩu demo trước khi dùng trên mạng thật.

Dữ liệu thật của ứng dụng được lưu trong SQLite tại `instance/app.db`. Các thay đổi qua giao diện được ghi ngay vào cơ sở dữ liệu và còn sau khi đóng/mở lại ứng dụng. Quản trị viên có thể sửa mọi hoạt động, hồ sơ sinh viên/giảng viên, điểm danh, điểm, thông báo, trạng thái tài khoản; trang **Tài khoản** cho phép sửa tên đăng nhập, họ tên, email và đặt lại mật khẩu. Vai trò tài khoản được giữ nguyên để bảo toàn hồ sơ và lịch sử tham gia.

## Chức năng đã triển khai

- Đăng nhập/đăng xuất, tự đăng ký sinh viên, đổi mật khẩu, hồ sơ cá nhân, kiểm tra CSRF, hash mật khẩu và phân quyền API.
- Danh bạ cộng đồng HPU và trang cá nhân công khai an toàn cho sinh viên/giảng viên; email, số điện thoại và địa chỉ không bị lộ trong danh bạ.
- Tải ảnh đại diện PNG/JPEG/WEBP; ảnh được nén và lưu trong `user_settings` của SQLite, nên vẫn còn sau khi khởi động lại.
- Dashboard theo vai trò với thẻ số liệu, thông báo, thao tác nhanh, biểu đồ tháng, tình trạng hoạt động và danh sách sự kiện gần nhất.
- Trang thống kê 3D dùng Three.js để hiển thị giờ tình nguyện được tổng hợp từ ngày giờ hoạt động và điểm danh; có biểu đồ dự phòng nếu WebGL/CDN không sẵn sàng.
- Tạo, xem, sửa, tìm kiếm, lọc, hủy hoạt động; giảng viên chỉ sửa hoạt động do mình phụ trách.
- Quản lý hồ sơ sinh viên và giảng viên; tạo tài khoản kèm hồ sơ, chỉnh sửa, tìm kiếm và khóa tài khoản. Quản trị viên có thể sửa thông tin đăng nhập và đặt lại mật khẩu từ trang **Tài khoản**.
- Sinh viên đăng ký/hủy; giảng viên hoặc quản trị viên duyệt/từ chối. Kiểm tra chỗ trong transaction và chặn đăng ký trùng.
- Điểm danh hiện diện/vắng/đi muộn, chấm điểm theo lượt tham gia và kiểm tra điểm tối đa.
- Thông báo cá nhân/toàn trường; trạng thái đã đọc riêng theo từng tài khoản.
- Cài đặt theme sáng/tối, màu, bo góc và hiệu ứng; cấu hình cá nhân lưu trong SQLite.
- Hiệu ứng Three.js ở trang đăng nhập và trang thống kê 3D có fallback khi WebGL hoặc CDN không khả dụng.
- Xuất CSV hoạt động, sinh viên, đăng ký, điểm danh và điểm; backup SQLite, kiểm tra file và khôi phục có bản dự phòng trước.
- Bảng hoạt động, lịch theo ngày, trạng thái tải/lỗi/trống, xác nhận thao tác quan trọng và giao diện di động.

## Cơ sở dữ liệu và backup

- Database chính: `instance/app.db` (được tạo tự động, không bị xóa khi khởi động).
- Bản sao lưu: `instance/backups/`.
- Mỗi kết nối bật foreign keys và busy timeout. Các thao tác dùng truy vấn tham số hóa.
- Database có bảng `schema_version`; phiên bản schema hiện tại là 1. Mở rộng cấu trúc ở bản sau cần thêm migration tăng phiên bản, không xóa dữ liệu cũ.
- Backup tải một bản SQLite xuống máy. Khôi phục chỉ nhận file SQLite có kiểm tra integrity và các bảng cốt lõi; ứng dụng sao lưu database hiện hành trước khi thay thế.

## Bảng SQLite

`schema_version`, `users`, `students`, `lecturers`, `activities`, `registrations`, `attendance`, `activity_scores`, `notifications`, `notification_reads`, `system_settings`, `user_settings`, `audit_logs`.

## API chính

- Tài khoản: `POST /api/login`, `POST /api/register`, `POST /api/logout`, `GET /api/me`, `GET/PUT /api/profile`, `PUT /api/profile/avatar`, `POST /api/change-password`.
- Cộng đồng: `GET /api/people`, `GET /api/people/<user_id>`, `GET /api/impact`.
- Dashboard: `GET /api/dashboard`.
- Sinh viên/giảng viên/tài khoản: `GET/POST /api/students`, `GET/PUT/DELETE /api/students/<id>`, các endpoint tương ứng dưới `/api/lecturers`, và `GET /api/accounts`, `PUT /api/accounts/<id>`, `PUT /api/accounts/<id>/status`.
- Hoạt động: `GET/POST /api/activities`, `GET/PUT/DELETE /api/activities/<id>`.
- Đăng ký: `GET/POST /api/registrations`, duyệt/từ chối qua `PUT /api/registrations/<id>/approve|reject`, hủy qua `DELETE /api/registrations/<id>`.
- Điểm danh: `GET/POST /api/attendance`, `PUT /api/attendance/<id>`.
- Điểm: `GET/POST /api/scores`, `PUT /api/scores/<id>`.
- Thông báo: `GET/POST /api/notifications`, `PUT /api/notifications/<id>/read`.
- Giao diện: `GET/PUT /api/settings/theme`, `POST /api/settings/theme/reset`.
- Báo cáo: `GET /api/export/<students|activities|registrations|attendance|scores>.csv`.
- Backup/restore: `GET /api/backup`, `POST /api/restore`.

API thay đổi dữ liệu yêu cầu session và CSRF token trong header `X-CSRF-Token`. Frontend đọc token từ thẻ meta sau khi mở trang/đăng nhập.

## Kiểm thử

Các bài test dùng database tạm riêng, không ghi vào `instance/app.db`:

```powershell
python -m unittest discover -v
```

Test hiện có bao phủ session, phân quyền, tạo hoạt động và persistence, đăng ký trùng, duyệt/điểm danh/chấm điểm, trạng thái đọc thông báo cá nhân, theme và backup/restore.

## Cấu trúc

```text
app.py
config.py
requirements.txt
run.bat
app/
  __init__.py       # app factory và seed chỉ khi database mới
  database.py       # kết nối SQLite, schema và audit log
  security.py       # session và decorator phân quyền
  routes.py         # API và nghiệp vụ
  templates/index.html
  static/style.css
  static/app.js
tests/test_app.py
instance/           # database, khóa session và backup khi chạy
```

## Dùng ảnh giao diện trong báo cáo

Chạy ứng dụng, đăng nhập lần lượt theo từng vai trò, mở dashboard và các trang hoạt động/đăng ký/điểm danh. Trên Windows dùng `Win + Shift + S` để chụp vùng trang; có thể thu nhỏ cửa sổ trình duyệt xuống khoảng 1440×900 hoặc 390×844 để chụp bản desktop và mobile. Không đưa mật khẩu hoặc dữ liệu cá nhân thật vào ảnh báo cáo.

## Giới hạn hiện tại

- Three.js và phông chữ web tải từ CDN; khi không có mạng giao diện vẫn hoạt động với font hệ thống và nền CSS.
- Bản này chưa có phân quyền giao hoạt động cho nhiều giảng viên, nhập hàng loạt CSV, hoặc trình soạn báo cáo PDF/Excel.
- Lịch hiện trình bày danh sách theo ngày; chưa có kéo-thả hoặc đồng bộ lịch ngoài.
- Triển khai hiện nhắm tới máy cá nhân/đồ án chạy cục bộ. Nếu đưa lên máy chủ cần cấu hình HTTPS, secret riêng, WSGI server và chính sách backup vận hành.
