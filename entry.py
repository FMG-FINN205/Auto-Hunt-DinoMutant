# entry.py — Entry point cho PyInstaller
# File này là điểm khởi động duy nhất khi đóng gói .exe
# Không cần import gì thêm, chỉ gọi run_app() từ ui.py

import sys
import os

# Đảm bảo thư mục chứa .exe là working directory
# để các file ngoài (ADB/, templates/, setting.json) tìm được đúng vị trí
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

from ui import run_app

if __name__ == "__main__":
    run_app()