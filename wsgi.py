"""
生产级WSGI入口文件
用于Gunicorn/Nginx部署

启动命令:
    gunicorn -w 4 -b 127.0.0.1:5000 wsgi:app

参数说明:
    -w 4         4个worker进程（建议 CPU核心数 * 2 + 1）
    -b           绑定地址和端口
    --timeout 120  请求超时时间（秒）
    --access-logfile -  访问日志输出到终端
    --error-logfile -   错误日志输出到终端
"""

import sys
import os
from pathlib import Path

# 确保src目录在Python路径中
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# 设置场景目录环境变量
os.environ.setdefault("SCENARIOS_DIR", str(BASE_DIR / "scenarios"))

from emergency_decision.api.app import app

if __name__ == "__main__":
    # 本地直接运行
    app.run(host="0.0.0.0", port=5000, debug=True)
