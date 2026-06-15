# HexaCall - Hệ Thống Video Conferencing Đa Luồng
```
Dự án lập trình mạng UDP/TCP hỗ trợ 6 clients.
HexaCall/
│
├── .gitignore               # Chặn đưa các file rác lên GitHub
├── requirements.txt         # Nơi G3 sẽ định nghĩa các thư viện cần thiết
├── README.md                # Thông tin dự án, hướng dẫn cài đặt
│
├── server/                  # Không gian làm việc của Group 1
│   ├── __init__.py
│   ├── main_server.py       # File chạy server chính (TCP/UDP)
│   └── room_manager.py      # File trống chờ xử lý logic quản lý 6 client
│
├── client/                  # Không gian làm việc chung (G1, G2, G3)
│   ├── __init__.py
│   ├── main_client.py       # File chạy app phía client
│   │
│   ├── network/             # G1: Xử lý nhận/gửi TCP và UDP
│   │   ├── __init__.py
│   │   └── connection.py    # Placeholder cho class Socket
│   │
│   ├── gui/                 # G2: Thiết kế giao diện PyQt6
│   │   ├── __init__.py
│   │   └── main_window.py   # Placeholder cho Grid 6 ô
│   │
│   └── media/               # G3: Xử lý OpenCV, nén JPEG
│       ├── __init__.py
│       └── frame_processor.py # Placeholder cho logic nén/giải nén ảnh
│
└── docs/                    # G3: Lưu trữ tài liệu, template Word/Slides
    └── .gitkeep             # File rỗng để Git giữ lại thư mục này
```
## Cài đặt môi trường
1. Tạo môi trường ảo: python -m venv .venv
2. Kích hoạt (Windows): .venv\Scripts\activate
3. Cài thư viện: pip install -r requirements.txt