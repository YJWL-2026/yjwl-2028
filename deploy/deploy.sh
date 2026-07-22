#!/bin/bash
# ============================================================
# 应急决策教学系统 - 一键部署脚本
# 在云服务器上执行: bash deploy.sh
# 前提: 已将项目代码上传到 /opt/emergency-decision
# ============================================================

set -e

PROJECT_DIR="/opt/emergency-decision"
PYTHON_VERSION="python3"

echo "=========================================="
echo "  应急决策教学系统 - 一键部署"
echo "=========================================="

# 1. 检查是否以root运行
if [ "$EUID" -ne 0 ]; then
  echo "❌ 请使用root用户或sudo运行此脚本"
  exit 1
fi

# 2. 安装系统依赖
echo ""
echo "[1/7] 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx 2>/dev/null

# 3. 创建项目目录（如果代码已存在则跳过）
echo "[2/7] 检查项目目录..."
if [ ! -d "$PROJECT_DIR" ]; then
  echo "❌ 项目目录 $PROJECT_DIR 不存在"
  echo "   请先将项目代码上传到 $PROJECT_DIR"
  echo "   例如: scp -r ./emergency-decision root@服务器IP:/opt/"
  exit 1
fi

# 4. 创建虚拟环境并安装Python依赖
echo "[3/7] 创建Python虚拟环境..."
cd $PROJECT_DIR
if [ ! -d "venv" ]; then
  $PYTHON_VERSION -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "   Python依赖安装完成"

# 5. 创建日志目录
echo "[4/7] 创建日志目录..."
mkdir -p /var/log/emergency-decision
chown www-data:www-data /var/log/emergency-decision

# 6. 配置Gunicorn服务
echo "[5/7] 配置Systemd服务..."
cp $PROJECT_DIR/deploy/emergency-decision.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable emergency-decision
systemctl restart emergency-decision
echo "   Flask服务已启动"

# 7. 配置Nginx
echo "[6/7] 配置Nginx..."
cp $PROJECT_DIR/deploy/nginx.conf /etc/nginx/sites-available/emergency-decision
ln -sf /etc/nginx/sites-available/emergency-decision /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t 2>/dev/null
systemctl restart nginx
echo "   Nginx已配置完成"

# 8. 检查状态
echo "[7/7] 检查服务状态..."
sleep 2
if systemctl is-active --quiet emergency-decision; then
  echo "   ✅ Flask服务运行中"
else
  echo "   ❌ Flask服务启动失败，请检查日志:"
  echo "   journalctl -u emergency-decision -n 20"
fi

if systemctl is-active --quiet nginx; then
  echo "   ✅ Nginx运行中"
else
  echo "   ❌ Nginx启动失败"
fi

# 获取服务器公网IP
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "服务器IP")

echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
echo ""
echo "  访问地址:  http://$PUBLIC_IP"
echo "  手机访问:  用手机浏览器打开上面的地址"
echo ""
echo "  管理命令:"
echo "    查看状态:  systemctl status emergency-decision"
echo "    重启服务:  systemctl restart emergency-decision"
echo "    查看日志:  journalctl -u emergency-decision -f"
echo "    重启Nginx: systemctl restart nginx"
echo ""
echo "  虚拟账号:"
echo "    教师: teacher01 / teach123"
echo "    学生: student01 / stud123"
echo ""
