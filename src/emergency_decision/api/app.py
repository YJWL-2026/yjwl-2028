"""
Flask API 服务器 - 应急决策教学系统后端

提供:
  - 场景管理 API (CRUD)
  - 决策引擎 API (求解/学生方案评估)
  - 行为埋点 API (采集)
  - 素养画像 API (查询)
  - 策略适配 API (策略二/三)
  - 教师后台 API (班级数据)
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect, url_for, g

# 确保src目录在path中
SRC_DIR = Path(__file__).resolve().parent.parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from emergency_decision.engine import EmergencyDecisionEngine
from emergency_decision.scenario_loader import (
    load_scenario_from_dict, load_scenario_from_file, save_scenario_to_file
)
from emergency_decision.student_evaluator import (
    StudentPlanEvaluator, StudentSubmission, StudentAction
)
from emergency_decision.models import ActionPlanType, StrategyMode
from emergency_decision.behavior_tracker import BehaviorTracker
from emergency_decision.profile_generator import ProfileGenerator, GrowthTracker
from emergency_decision.strategy_adaptations import StrategyController
from emergency_decision.realtime_data import (
    EarthquakeDataFetcher, TyphoonDataFetcher, WeatherAlertFetcher,
    earthquake_to_scenario_params, typhoon_to_scenario_params,
    weather_alert_to_scenario_params, fetch_latest_disasters,
    get_license_plate_prefix,
)

# ============================================================
# Flask 应用
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
# 支持环境变量覆盖场景目录（生产部署用）
_scenarios_env = os.environ.get("SCENARIOS_DIR")
SCENARIOS_DIR = Path(_scenarios_env) if _scenarios_env else BASE_DIR / "scenarios"
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = Flask(__name__,
            template_folder=str(WEB_DIR / "templates"),
            static_folder=str(WEB_DIR / "static"))
app.secret_key = "emergency_decision_teaching_2026"
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ============================================================
# 虚拟账号系统
# ============================================================

VIRTUAL_USERS = {
    # 教师账号
    "teacher01": {"password": "teach123", "role": "teacher", "name": "王老师", "avatar": "👨‍🏫"},
    "teacher02": {"password": "teach456", "role": "teacher", "name": "李老师", "avatar": "👩‍🏫"},
    # 学生账号（20人班级）- 密码统一 stud123
    "student01": {"password": "stud123", "role": "student", "name": "张伟", "avatar": "🧑‍🎓"},
    "student02": {"password": "stud123", "role": "student", "name": "刘思怡", "avatar": "👩‍🎓"},
    "student03": {"password": "stud123", "role": "student", "name": "陈浩宇", "avatar": "🧑‍🎓"},
    "student04": {"password": "stud123", "role": "student", "name": "杨雨桐", "avatar": "👩‍🎓"},
    "student05": {"password": "stud123", "role": "student", "name": "赵磊", "avatar": "🧑‍🎓"},
    "student06": {"password": "stud123", "role": "student", "name": "黄家俊", "avatar": "🧑‍🎓"},
    "student07": {"password": "stud123", "role": "student", "name": "周若琳", "avatar": "👩‍🎓"},
    "student08": {"password": "stud123", "role": "student", "name": "吴俊杰", "avatar": "🧑‍🎓"},
    "student09": {"password": "stud123", "role": "student", "name": "徐嘉乐", "avatar": "🧑‍🎓"},
    "student10": {"password": "stud123", "role": "student", "name": "孙悦", "avatar": "👩‍🎓"},
    "student11": {"password": "stud123", "role": "student", "name": "马志远", "avatar": "🧑‍🎓"},
    "student12": {"password": "stud123", "role": "student", "name": "胡瑞阳", "avatar": "🧑‍🎓"},
    "student13": {"password": "stud123", "role": "student", "name": "朱慧琳", "avatar": "👩‍🎓"},
    "student14": {"password": "stud123", "role": "student", "name": "林涛", "avatar": "🧑‍🎓"},
    "student15": {"password": "stud123", "role": "student", "name": "何诗涵", "avatar": "👩‍🎓"},
    "student16": {"password": "stud123", "role": "student", "name": "罗浩天", "avatar": "🧑‍🎓"},
    "student17": {"password": "stud123", "role": "student", "name": "梁梓轩", "avatar": "🧑‍🎓"},
    "student18": {"password": "stud123", "role": "student", "name": "宋佳怡", "avatar": "👩‍🎓"},
    "student19": {"password": "stud123", "role": "student", "name": "郑凯", "avatar": "🧑‍🎓"},
    "student20": {"password": "stud123", "role": "student", "name": "韩雨萱", "avatar": "👩‍🎓"},
}

# 各角色可访问的页面
ROLE_PAGES = {
    "teacher": ["/", "/editor", "/decision", "/profile", "/dashboard", "/disaster-query", "/logistics", "/company", "/mem", "/manage", "/research", "/knowledge"],
    "student": ["/", "/decision", "/profile", "/disaster-query", "/company", "/mem", "/manage", "/research", "/knowledge", "/scenarios", "/my-scores"],
}

# 不需要登录就能访问的页面
PUBLIC_PAGES = ["/login", "/api/login", "/api/logout", "/api/session", "/api/auth/token"]

# 全局状态 (教学系统运行时数据)
engine = EmergencyDecisionEngine()

# ============================================================
# Token 认证（小程序专用，与Session并存）
# ============================================================

# Token存储: token_string -> {username, role, name, avatar, created_at}
_TOKEN_STORE = {}
_TOKEN_EXPIRE_SECONDS = 7 * 24 * 3600  # Token有效期7天


def _generate_token(username: str) -> str:
    """生成随机Token"""
    raw = f"{username}:{time.time()}:{secrets.token_hex(16)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_user_from_token():
    """从请求头或URL参数获取Token并返回用户信息，失败返回None。
    支持两种传入方式:
    1. Authorization: Bearer <token> 请求头（小程序wx.request）
    2. ?token=xxx URL参数（web-view内嵌页面自动登录）
    """
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.args.get("token", "").strip()
    if not token:
        return None
    token_data = _TOKEN_STORE.get(token)
    if not token_data:
        return None
    # 检查过期
    if time.time() - token_data["created_at"] > _TOKEN_EXPIRE_SECONDS:
        _TOKEN_STORE.pop(token, None)
        return None
    return token_data, token


def _cleanup_expired_tokens():
    """清理过期Token"""
    now = time.time()
    expired = [t for t, d in _TOKEN_STORE.items() if now - d["created_at"] > _TOKEN_EXPIRE_SECONDS]
    for t in expired:
        _TOKEN_STORE.pop(t, None)


@app.context_processor
def inject_user():
    """将当前登录用户注入所有模板上下文，用于角色化渲染。
    同时支持Session(Cookie)和Token(小程序)两种认证方式。"""
    user = session.get("user")
    if not user:
        # 尝试从Token获取（小程序场景）
        token_result = _get_user_from_token()
        if token_result:
            token_data, _ = token_result
            user = {
                "username": token_data["username"],
                "role": token_data["role"],
                "name": token_data["name"],
                "avatar": token_data["avatar"],
            }
    return {"current_user": user}
evaluator = StudentPlanEvaluator()
behavior_tracker = BehaviorTracker()
profile_gen = ProfileGenerator()
growth_tracker = GrowthTracker()
strategy_ctrl = StrategyController()

# 存储运行时数据 (JSON文件持久化)
STATE_FILE = BASE_DIR / "_runtime_state.json"

_runtime_store = {
    "sessions": {},        # session_id -> {student_id, scenario_id, ...}
    "results": {},         # session_id -> engine result
    "profiles": {},        # student_id -> [profile dicts]
    "behavior_events": {}, # session_id -> [events]
    "group_tasks": {},     # gtask_id -> group task data
    "progress": {},        # student_id -> [progress entries]
}

def save_state():
    """将运行时数据持久化到JSON文件"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_runtime_store, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        print(f"[SAVE ERROR] {e}")

def load_state():
    """从JSON文件恢复运行时数据"""
    global _runtime_store
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            # 用 update 合并而非替换，避免丢失默认 key（classes/tasks 等）
            _runtime_store.update(loaded)
            print(f"[LOAD] 已从 {STATE_FILE} 恢复运行时数据")
        except Exception as e:
            print(f"[LOAD ERROR] {e}，使用初始数据")
    # 保证关键 key 始终存在
    for key in ("classes", "tasks", "progress", "group_tasks"):
        _runtime_store.setdefault(key, {})

# 启动时加载持久化数据
import json
load_state()

# 兜底：如果加载后 classes 为空（文件损坏或被误清空），自动重建默认班级
_DEFAULT_CLASS_ID = "CLS-202601"
if not _runtime_store.get("classes") or _DEFAULT_CLASS_ID not in _runtime_store["classes"]:
    _default_students = [
        {"student_id": f"student{i:02d}", "name": VIRTUAL_USERS[f"student{i:02d}"]["name"],
         "avatar": VIRTUAL_USERS[f"student{i:02d}"]["avatar"]}
        for i in range(1, 21)
    ]
    _runtime_store.setdefault("classes", {})
    _runtime_store["classes"][_DEFAULT_CLASS_ID] = {
        "name": "2026级物流管理1班",
        "teacher": "王老师",
        "teacher_id": "teacher01",
        "students": _default_students,
        "groups": [],
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    print(f"[AUTO] 默认班级已兜底重建: {_DEFAULT_CLASS_ID} (20名学生)")

@app.before_request
def auto_load_state():
    """每次请求前从文件同步状态（解决多worker容器的数据一致性问题）"""
    load_state()
    # 兜底：如果加载后 classes 为空，自动重建默认班级
    if not _runtime_store.get("classes"):
        _runtime_store.setdefault("classes", {})
        if _DEFAULT_CLASS_ID not in _runtime_store["classes"]:
            _default_students = [
                {"student_id": f"student{i:02d}", "name": VIRTUAL_USERS[f"student{i:02d}"]["name"],
                 "avatar": VIRTUAL_USERS[f"student{i:02d}"]["avatar"]}
                for i in range(1, 21)
            ]
            _runtime_store["classes"][_DEFAULT_CLASS_ID] = {
                "name": "2026级物流管理1班",
                "teacher": "王老师",
                "teacher_id": "teacher01",
                "students": _default_students,
                "groups": [],
                "created_at": time.strftime("%Y-%m-%d %H:%M"),
            }
            print(f"[AUTO] 请求前兜底重建默认班级: {_DEFAULT_CLASS_ID}")

@app.after_request
def auto_save_state(response):
    """修改操作后自动保存状态"""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        save_state()
    return response


# ============================================================
# 登录/鉴权
# ============================================================

@app.route("/login")
def login_page():
    """登录页面"""
    # 已登录则跳转首页
    if session.get("user"):
        return redirect("/")
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    """登录验证API"""
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "请输入账号和密码"}), 400

    user = VIRTUAL_USERS.get(username)
    if not user or user["password"] != password:
        return jsonify({"error": "账号或密码错误"}), 401

    # 写入session
    session["user"] = {
        "username": username,
        "role": user["role"],
        "name": user["name"],
        "avatar": user["avatar"],
    }

    # 登录后统一跳转到系统首页
    redirect_url = "/"
    return jsonify({
        "status": "ok",
        "user": session["user"],
        "redirect": redirect_url,
    })


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """退出登录"""
    session.pop("user", None)
    # 同时清除Token
    token_result = _get_user_from_token()
    if token_result:
        _, token = token_result
        _TOKEN_STORE.pop(token, None)
    return jsonify({"status": "ok"})


@app.route("/api/auth/token", methods=["POST"])
def api_auth_token():
    """Token认证登录（小程序专用）
    接收账号密码，返回Token，后续请求通过 Authorization: Bearer <token> 携带。
    """
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "请输入账号和密码"}), 400

    user = VIRTUAL_USERS.get(username)
    if not user or user["password"] != password:
        return jsonify({"error": "账号或密码错误"}), 401

    # 清理过期Token
    _cleanup_expired_tokens()

    # 生成Token
    token = _generate_token(username)
    token_data = {
        "username": username,
        "role": user["role"],
        "name": user["name"],
        "avatar": user["avatar"],
        "created_at": time.time(),
    }
    _TOKEN_STORE[token] = token_data

    return jsonify({
        "token": token,
        "user": {
            "username": username,
            "role": user["role"],
            "name": user["name"],
            "avatar": user["avatar"],
        },
        "expires_in": _TOKEN_EXPIRE_SECONDS,
    })


@app.route("/api/session")
def api_session():
    """获取当前登录状态（同时支持Session和Token）"""
    user = session.get("user")
    if user:
        return jsonify({"logged_in": True, "user": user})

    # 尝试Token认证
    token_result = _get_user_from_token()
    if token_result:
        token_data, _ = token_result
        return jsonify({
            "logged_in": True,
            "user": {
                "username": token_data["username"],
                "role": token_data["role"],
                "name": token_data["name"],
                "avatar": token_data["avatar"],
            }
        })
    return jsonify({"logged_in": False})


def _check_auth(path: str):
    """检查页面访问权限，返回 (passed, redirect_url)
    同时支持Session(Cookie)和Token(小程序Authorization头)两种认证方式。
    """
    user = session.get("user")
    if not user:
        # 尝试Token认证
        token_result = _get_user_from_token()
        if token_result:
            token_data, _ = token_result
            user = {
                "username": token_data["username"],
                "role": token_data["role"],
            }
        else:
            # 未登录 → 跳转登录页
            return False, "/login"
    role = user.get("role", "")
    allowed = ROLE_PAGES.get(role, [])
    if path not in allowed:
        # 无权限访问 → 跳转角色默认页
        default = "/dashboard" if role == "teacher" else "/decision"
        return False, default
    return True, None


# ============================================================
# 页面路由（带登录鉴权）
# ============================================================

@app.route("/")
def index():
    ok, redirect_url = _check_auth("/")
    if not ok:
        return redirect(redirect_url)
    return render_template("index.html", active_page="home")

@app.route("/editor")
def editor():
    ok, redirect_url = _check_auth("/editor")
    if not ok:
        return redirect(redirect_url)
    return render_template("editor.html")

@app.route("/decision")
def decision():
    ok, redirect_url = _check_auth("/decision")
    if not ok:
        return redirect(redirect_url)
    return render_template("decision.html")

@app.route("/profile")
def profile():
    ok, redirect_url = _check_auth("/profile")
    if not ok:
        return redirect(redirect_url)
    return render_template("profile.html")

@app.route("/dashboard")
def dashboard():
    ok, redirect_url = _check_auth("/dashboard")
    if not ok:
        return redirect(redirect_url)
    return render_template("dashboard.html")

@app.route("/disaster-query")
def disaster_query():
    ok, redirect_url = _check_auth("/disaster-query")
    if not ok:
        return redirect(redirect_url)
    return render_template("disaster_query.html")

@app.route("/logistics")
def logistics_page():
    ok, redirect_url = _check_auth("/logistics")
    if not ok:
        return redirect(redirect_url)
    return render_template("logistics.html", active_page="logistics")

@app.route("/company")
def company_page():
    ok, redirect_url = _check_auth("/company")
    if not ok:
        return redirect(redirect_url)
    return render_template("company_dashboard.html", active_page="company")


# ============================================================
# 七大模块 - 管·研·建 页面路由
# ============================================================

@app.route("/manage")
def manage_page():
    """管 - 课程管理：课堂分组、任务分发、进度监控"""
    ok, redirect_url = _check_auth("/manage")
    if not ok:
        return redirect(redirect_url)
    return render_template("manage.html", active_page="manage")


@app.route("/research")
def research_page():
    """研 - 案例生成：基于全省物流数据自动生成教学案例"""
    ok, redirect_url = _check_auth("/research")
    if not ok:
        return redirect(redirect_url)
    return render_template("research.html", active_page="research")


@app.route("/knowledge")
def knowledge_page():
    """建 - 知识库建设：持续接入新数据、更新知识图谱"""
    ok, redirect_url = _check_auth("/knowledge")
    if not ok:
        return redirect(redirect_url)
    return render_template("knowledge.html", active_page="knowledge")


@app.route("/scenarios")
def scenario_intro_page():
    """教（学生视角）- 场景简介：查看灾害类型与场景介绍"""
    ok, redirect_url = _check_auth("/scenarios")
    if not ok:
        return redirect(redirect_url)
    return render_template("scenario_intro.html", active_page="scenarios")


@app.route("/my-scores")
def my_scores_page():
    """评（学生视角）- 我的成绩：查看自己的评分记录"""
    ok, redirect_url = _check_auth("/my-scores")
    if not ok:
        return redirect(redirect_url)
    return render_template("my_scores.html", active_page="my-scores")


# ============================================================
# 管·研·建 API
# ============================================================

# --- 管：课程管理 ---
_runtime_store.setdefault("classes", {})       # class_id -> {name, teacher, students:[], groups:[], created_at}
_runtime_store.setdefault("tasks", {})          # task_id -> {class_id, scenario_id, title, assignee, status, deadline}
_runtime_store.setdefault("progress", {})      # student_id -> [{task_id, status, submit_time, score}]
_runtime_store.setdefault("group_tasks", {})    # gtask_id -> {class_id, group_ids, scenario_id, title, deadline, created_at, status}

@app.route("/api/manage/classes", methods=["GET"])
def api_get_classes():
    """获取班级列表"""
    classes = []
    for cid, c in _runtime_store["classes"].items():
        classes.append({
            "class_id": cid,
            "name": c.get("name", ""),
            "teacher": c.get("teacher", ""),
            "student_count": len(c.get("students", [])),
            "group_count": len(c.get("groups", [])),
            "created_at": c.get("created_at", ""),
        })
    return jsonify({"classes": classes})


@app.route("/api/manage/classes", methods=["POST"])
def api_create_class():
    """创建班级"""
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "请输入班级名称"}), 400
    class_id = f"CLS-{int(time.time())%1000000:06d}"
    user = session.get("user", {})
    _runtime_store["classes"][class_id] = {
        "name": name,
        "teacher": user.get("name", ""),
        "teacher_id": user.get("username", ""),
        "students": [],
        "groups": [],
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    return jsonify({"status": "ok", "class_id": class_id})


@app.route("/api/manage/classes/<class_id>/students", methods=["POST"])
def api_add_student(class_id):
    """添加学生到班级"""
    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404
    data = request.get_json()
    student = {
        "student_id": data.get("student_id", ""),
        "name": data.get("name", ""),
        "avatar": data.get("avatar", "👨‍🎓"),
    }
    cls["students"].append(student)
    return jsonify({"status": "ok"})


@app.route("/api/manage/classes/<class_id>/groups", methods=["POST"])
def api_create_group(class_id):
    """创建课堂分组"""
    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404
    data = request.get_json()
    group_name = data.get("name", "")
    member_ids = data.get("members", [])
    group = {
        "group_id": f"GRP-{len(cls['groups'])+1:03d}",
        "name": group_name,
        "members": member_ids,
        "leader": data.get("leader", ""),
    }
    cls["groups"].append(group)
    return jsonify({"status": "ok", "group": group})


@app.route("/api/manage/tasks", methods=["POST"])
def api_assign_task():
    """任务分发"""
    data = request.get_json()
    class_id = data.get("class_id", "")
    scenario_id = data.get("scenario_id", "")
    title = data.get("title", "")
    assignees = data.get("assignees", [])  # student_id 列表
    deadline = data.get("deadline", "")

    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404

    task_id = f"TASK-{int(time.time())%1000000:06d}"
    task = {
        "task_id": task_id,
        "class_id": class_id,
        "scenario_id": scenario_id,
        "title": title,
        "assignees": assignees,
        "status": "assigned",
        "deadline": deadline,
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    _runtime_store["tasks"][task_id] = task

    # 为每个学生创建进度记录
    for sid in assignees:
        if sid not in _runtime_store["progress"]:
            _runtime_store["progress"][sid] = []
        _runtime_store["progress"][sid].append({
            "task_id": task_id,
            "status": "pending",
            "submit_time": None,
            "score": None,
        })

    return jsonify({"status": "ok", "task_id": task_id})


@app.route("/api/manage/tasks/<class_id>", methods=["GET"])
def api_get_tasks(class_id):
    """获取班级任务列表"""
    tasks = []
    for tid, t in _runtime_store["tasks"].items():
        if t.get("class_id") == class_id:
            # 统计完成情况
            total = len(t.get("assignees", []))
            completed = sum(1 for sid in t.get("assignees", [])
                           for p in _runtime_store.get("progress", {}).get(sid, [])
                           if p.get("task_id") == tid and p.get("status") == "completed")
            tasks.append({
                **t,
                "total": total,
                "completed": completed,
                "progress_pct": round(completed / total * 100) if total else 0,
            })
    return jsonify({"tasks": tasks})


@app.route("/api/manage/progress/<class_id>", methods=["GET"])
def api_get_class_progress(class_id):
    """获取班级进度监控"""
    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404

    students_progress = []
    for s in cls.get("students", []):
        sid = s["student_id"]
        progress = _runtime_store.get("progress", {}).get(sid, [])
        total_tasks = len(progress)
        completed = sum(1 for p in progress if p.get("status") == "completed")
        avg_score = None
        scores = [p.get("score") for p in progress if p.get("score") is not None]
        if scores:
            avg_score = round(sum(scores) / len(scores), 1)
        students_progress.append({
            **s,
            "total_tasks": total_tasks,
            "completed": completed,
            "progress_pct": round(completed / total_tasks * 100) if total_tasks else 0,
            "avg_score": avg_score,
        })

    return jsonify({
        "class_name": cls.get("name", ""),
        "total_students": len(cls.get("students", [])),
        "total_groups": len(cls.get("groups", [])),
        "students_progress": students_progress,
        "groups": cls.get("groups", []),
    })


# ============================================================
# 管：增强功能 —— 分组管理 / 组任务 / 确认流程 / 未完成提醒
# ============================================================

def _get_student_name(sid):
    """根据student_id获取学生姓名"""
    u = VIRTUAL_USERS.get(sid, {})
    return u.get("name", sid)


def _get_student_avatar(sid):
    u = VIRTUAL_USERS.get(sid, {})
    return u.get("avatar", "🧑‍🎓")


def _student_in_group(cls, student_id):
    """返回学生所在的分组，没有则返回None"""
    for g in cls.get("groups", []):
        if student_id in g.get("members", []):
            return g
    return None


# --- 分组管理（自组队 + 教师调整） ---

@app.route("/api/manage/classes/<class_id>/groups", methods=["GET"])
def api_get_groups(class_id):
    """获取班级所有分组（含未分组学生）"""
    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404
    groups = []
    for g in cls.get("groups", []):
        members_info = []
        for mid in g.get("members", []):
            members_info.append({
                "student_id": mid,
                "name": _get_student_name(mid),
                "avatar": _get_student_avatar(mid),
            })
        groups.append({
            "group_id": g["group_id"],
            "name": g.get("name", ""),
            "leader": g.get("leader", ""),
            "leader_name": _get_student_name(g.get("leader", "")) if g.get("leader") else "",
            "members": members_info,
            "self_organized": g.get("self_organized", False),
            "created_at": g.get("created_at", ""),
        })
    # 未分组学生
    grouped_ids = set()
    for g in cls.get("groups", []):
        grouped_ids.update(g.get("members", []))
    ungrouped = []
    for s in cls.get("students", []):
        if s["student_id"] not in grouped_ids:
            ungrouped.append({
                "student_id": s["student_id"],
                "name": s.get("name", s["student_id"]),
                "avatar": s.get("avatar", "🧑‍🎓"),
            })
    return jsonify({"groups": groups, "ungrouped": ungrouped})


@app.route("/api/manage/groups/self-create", methods=["POST"])
def api_self_create_group():
    """学生自组队：创建小组并加入（可同时邀请组员）"""
    data = request.get_json()
    class_id = data.get("class_id", "")
    student_id = data.get("student_id", "")
    group_name = data.get("group_name", "")
    invitees = data.get("invitees", [])  # 可选：同时邀请的组员ID

    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404

    # 检查学生是否已在分组中
    existing = _student_in_group(cls, student_id)
    if existing:
        return jsonify({"error": f"你已在分组「{existing.get('name')}」中，请先退出"}), 400

    # 检查人数限制（4-5人）
    members = [student_id] + [s for s in invitees if s != student_id]
    if len(members) > 5:
        return jsonify({"error": "每组最多5人"}), 400

    group_id = f"GRP-{int(time.time())%1000000:04d}"
    group = {
        "group_id": group_id,
        "name": group_name or f"第{len(cls['groups'])+1}小组",
        "members": members,
        "leader": student_id,  # 创建者默认为组长
        "self_organized": True,
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    cls["groups"].append(group)
    return jsonify({"status": "ok", "group_id": group_id, "group": group})


@app.route("/api/manage/groups/<group_id>/join", methods=["POST"])
def api_join_group(group_id):
    """学生加入已有分组"""
    data = request.get_json()
    class_id = data.get("class_id", "")
    student_id = data.get("student_id", "")

    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404

    # 找到分组
    target_group = None
    for g in cls["groups"]:
        if g["group_id"] == group_id:
            target_group = g
            break
    if not target_group:
        return jsonify({"error": "分组不存在"}), 404

    # 检查是否已在其他分组
    existing = _student_in_group(cls, student_id)
    if existing and existing["group_id"] != group_id:
        return jsonify({"error": f"你已在「{existing.get('name')}」中，请先退出"}), 400

    if student_id in target_group["members"]:
        return jsonify({"error": "你已在该分组中"}), 400

    if len(target_group["members"]) >= 5:
        return jsonify({"error": "该分组已满（最多5人）"}), 400

    target_group["members"].append(student_id)
    return jsonify({"status": "ok"})


@app.route("/api/manage/groups/<group_id>/leave", methods=["POST"])
def api_leave_group(group_id):
    """学生退出分组"""
    data = request.get_json()
    class_id = data.get("class_id", "")
    student_id = data.get("student_id", "")

    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404

    for g in cls["groups"]:
        if g["group_id"] == group_id:
            if student_id in g["members"]:
                g["members"].remove(student_id)
                # 如果组长退出，自动指定第一个成员为新组长
                if g.get("leader") == student_id:
                    g["leader"] = g["members"][0] if g["members"] else ""
                # 如果分组空了，删除
                if not g["members"]:
                    cls["groups"].remove(g)
            break
    return jsonify({"status": "ok"})


@app.route("/api/manage/groups/<group_id>/adjust", methods=["POST"])
def api_adjust_group(group_id):
    """教师调整分组：移动学生 / 重命名 / 设置组长"""
    data = request.get_json()
    class_id = data.get("class_id", "")
    action = data.get("action", "")  # "move" | "rename" | "set_leader" | "remove_member"
    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404

    target_group = None
    for g in cls["groups"]:
        if g["group_id"] == group_id:
            target_group = g
            break
    if not target_group:
        return jsonify({"error": "分组不存在"}), 404

    if action == "rename":
        target_group["name"] = data.get("name", target_group["name"])
    elif action == "set_leader":
        new_leader = data.get("leader", "")
        if new_leader not in target_group["members"]:
            return jsonify({"error": "该学生不在本组"}), 400
        target_group["leader"] = new_leader
    elif action == "remove_member":
        sid = data.get("student_id", "")
        if sid in target_group["members"]:
            target_group["members"].remove(sid)
            if target_group.get("leader") == sid:
                target_group["leader"] = target_group["members"][0] if target_group["members"] else ""
            if not target_group["members"]:
                cls["groups"].remove(target_group)
    elif action == "add_member":
        sid = data.get("student_id", "")
        # 先从其他组移除
        for g in cls["groups"]:
            if sid in g.get("members", []):
                g["members"].remove(sid)
                if g.get("leader") == sid:
                    g["leader"] = g["members"][0] if g["members"] else ""
                if not g["members"]:
                    cls["groups"].remove(g)
                break
        if len(target_group["members"]) >= 5:
            return jsonify({"error": "该分组已满（最多5人）"}), 400
        target_group["members"].append(sid)
    else:
        return jsonify({"error": "未知操作"}), 400

    return jsonify({"status": "ok"})


@app.route("/api/manage/groups/auto", methods=["POST"])
def api_auto_group():
    """教师一键自动分组（4-5人一组）"""
    data = request.get_json()
    class_id = data.get("class_id", "")
    group_size = data.get("group_size", 4)
    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404

    all_students = [s["student_id"] for s in cls.get("students", [])]
    # 已分组的不参与
    grouped_ids = set()
    for g in cls.get("groups", []):
        grouped_ids.update(g.get("members", []))
    ungrouped_ids = [sid for sid in all_students if sid not in grouped_ids]

    import random
    random.shuffle(ungrouped_ids)
    new_groups = []
    idx = len(cls["groups"]) + 1
    while ungrouped_ids:
        chunk = ungrouped_ids[:group_size]
        ungrouped_ids = ungrouped_ids[group_size:]
        if len(chunk) < group_size and ungrouped_ids:
            # 把剩余的不足group_size的尽量匀到其他组
            while chunk and ungrouped_ids:
                chunk.append(ungrouped_ids.pop(0))
                if len(chunk) >= group_size:
                    break
        if not chunk:
            break
        group = {
            "group_id": f"GRP-{int(time.time())+idx:04d}",
            "name": f"第{idx}小组",
            "members": chunk,
            "leader": chunk[0],
            "self_organized": False,
            "created_at": time.strftime("%Y-%m-%d %H:%M"),
        }
        cls["groups"].append(group)
        new_groups.append(group)
        idx += 1

    return jsonify({"status": "ok", "new_groups": len(new_groups)})


# --- 组任务分发 + 确认流程 ---

@app.route("/api/manage/group-tasks", methods=["POST"])
def api_assign_group_task():
    """教师向小组分发任务（带截止时间）"""
    data = request.get_json()
    class_id = data.get("class_id", "")
    group_ids = data.get("group_ids", [])
    title = data.get("title", "")
    scenario_id = data.get("scenario_id", "")
    deadline = data.get("deadline", "")
    description = data.get("description", "")

    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404
    if not title:
        return jsonify({"error": "请输入任务标题"}), 400
    if not group_ids:
        return jsonify({"error": "请至少选择一个分组"}), 400

    gtask_id = f"GTASK-{int(time.time())%1000000:06d}"
    # 为每个选中的分组创建确认记录
    confirmations = {}
    for gid in group_ids:
        g = None
        for grp in cls["groups"]:
            if grp["group_id"] == gid:
                g = grp
                break
        if not g:
            continue
        member_confirms = {}
        leader_confirmed = False
        for mid in g.get("members", []):
            member_confirms[mid] = False
        confirmations[gid] = {
            "group_id": gid,
            "group_name": g.get("name", ""),
            "leader": g.get("leader", ""),
            "members": g.get("members", []),
            "leader_confirmed": leader_confirmed,
            "member_confirmations": member_confirms,
        }

    gtask = {
        "gtask_id": gtask_id,
        "class_id": class_id,
        "title": title,
        "scenario_id": scenario_id,
        "deadline": deadline,
        "description": description,
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
        "status": "published",  # published -> leader_accepted -> members_accepted -> in_progress -> completed
        "confirmations": confirmations,
    }
    _runtime_store["group_tasks"][gtask_id] = gtask
    return jsonify({"status": "ok", "gtask_id": gtask_id})


@app.route("/api/manage/group-tasks/<class_id>", methods=["GET"])
def api_get_group_tasks(class_id):
    """获取班级所有组任务（含决策完成进度）"""
    tasks = []
    for gtid, gt in _runtime_store["group_tasks"].items():
        if gt.get("class_id") != class_id:
            continue
        # 计算确认进度
        total_groups = len(gt.get("confirmations", {}))
        leader_done = sum(1 for c in gt.get("confirmations", {}).values() if c.get("leader_confirmed"))
        member_done = sum(1 for c in gt.get("confirmations", {}).values()
                         if c.get("member_confirmations") and all(c["member_confirmations"].values()))

        # 计算决策推演完成进度
        all_members = set()
        completed_members = set()
        for gid, conf in gt.get("confirmations", {}).items():
            for mid in conf.get("members", []):
                all_members.add(mid)
                mp = _runtime_store.get("progress", {}).get(mid, [])
                if any(p.get("task_id") == gtid and p.get("status") == "completed" for p in mp):
                    completed_members.add(mid)
        total_members = len(all_members)
        decision_completed = len(completed_members)

        tasks.append({
            "gtask_id": gtid,
            "title": gt.get("title", ""),
            "scenario_id": gt.get("scenario_id", ""),
            "deadline": gt.get("deadline", ""),
            "description": gt.get("description", ""),
            "created_at": gt.get("created_at", ""),
            "status": gt.get("status", ""),
            "total_groups": total_groups,
            "leader_confirmed_count": leader_done,
            "all_confirmed_count": member_done,
            "total_members": total_members,
            "decision_completed_count": decision_completed,
            "decision_pct": round(decision_completed / total_members * 100) if total_members else 0,
            "confirmations": gt.get("confirmations", {}),
        })
    return jsonify({"tasks": tasks})


@app.route("/api/manage/group-tasks/<gtask_id>/leader-confirm", methods=["POST"])
def api_leader_confirm(gtask_id):
    """组长确认接受任务"""
    data = request.get_json()
    group_id = data.get("group_id", "")
    student_id = data.get("student_id", "")

    gt = _runtime_store["group_tasks"].get(gtask_id)
    if not gt:
        return jsonify({"error": "任务不存在"}), 404

    conf = gt.get("confirmations", {}).get(group_id)
    if not conf:
        return jsonify({"error": "该分组未分配此任务"}), 400

    if conf.get("leader") != student_id:
        return jsonify({"error": "只有组长可以确认接受任务"}), 403

    conf["leader_confirmed"] = True
    # 更新整体状态
    all_leader = all(c.get("leader_confirmed") for c in gt.get("confirmations", {}).values())
    if all_leader:
        gt["status"] = "leader_accepted"
    return jsonify({"status": "ok", "leader_confirmed": True})


@app.route("/api/manage/group-tasks/<gtask_id>/member-confirm", methods=["POST"])
def api_member_confirm(gtask_id):
    """组员确认接受任务"""
    data = request.get_json()
    group_id = data.get("group_id", "")
    student_id = data.get("student_id", "")

    gt = _runtime_store["group_tasks"].get(gtask_id)
    if not gt:
        return jsonify({"error": "任务不存在"}), 404

    conf = gt.get("confirmations", {}).get(group_id)
    if not conf:
        return jsonify({"error": "该分组未分配此任务"}), 400

    if student_id not in conf.get("members", []):
        return jsonify({"error": "你不在该分组中"}), 403

    if not conf.get("leader_confirmed"):
        return jsonify({"error": "组长尚未确认接受任务，请等待组长确认"}), 400

    conf.setdefault("member_confirmations", {})[student_id] = True

    # 检查所有组的所有成员是否都已确认
    all_confirmed = True
    for c in gt.get("confirmations", {}).values():
        member_cfs = c.get("member_confirmations", {})
        if not all(member_cfs.values()) or len(member_cfs) < len(c.get("members", [])):
            all_confirmed = False
            break
    if all_confirmed:
        gt["status"] = "in_progress"
    return jsonify({"status": "ok", "member_confirmed": True})


@app.route("/api/manage/group-tasks/my/<student_id>", methods=["GET"])
def api_get_my_group_tasks(student_id):
    """获取学生所在组的任务（学生视角，含决策完成状态）"""
    tasks = []
    for gtid, gt in _runtime_store["group_tasks"].items():
        for gid, conf in gt.get("confirmations", {}).items():
            if student_id in conf.get("members", []):
                is_leader = conf.get("leader") == student_id
                member_cfs = conf.get("member_confirmations", {})

                # 构建成员列表，附上决策完成状态和成绩
                members_info = []
                for mid in conf.get("members", []):
                    # 检查该成员的决策推演完成状态
                    mp = _runtime_store.get("progress", {}).get(mid, [])
                    task_progress = next(
                        (p for p in mp if p.get("task_id") == gtid and p.get("status") == "completed"),
                        None
                    )
                    # 查询成绩
                    score_val = task_progress.get("score") if task_progress else None
                    members_info.append({
                        "student_id": mid,
                        "name": _get_student_name(mid),
                        "avatar": _get_student_avatar(mid),
                        "confirmed": member_cfs.get(mid, False),
                        "decision_completed": task_progress is not None,
                        "score": score_val,
                    })

                # 自身完成状态
                my_progress = _runtime_store.get("progress", {}).get(student_id, [])
                my_task_done = any(
                    p.get("task_id") == gtid and p.get("status") == "completed"
                    for p in my_progress
                )
                my_score = None
                if my_task_done:
                    done = next(
                        (p for p in my_progress if p.get("task_id") == gtid and p.get("status") == "completed"),
                        None
                    )
                    my_score = done.get("score") if done else None

                tasks.append({
                    "gtask_id": gtid,
                    "title": gt.get("title", ""),
                    "scenario_id": gt.get("scenario_id", ""),
                    "deadline": gt.get("deadline", ""),
                    "description": gt.get("description", ""),
                    "created_at": gt.get("created_at", ""),
                    "status": gt.get("status", ""),
                    "group_id": gid,
                    "group_name": conf.get("group_name", ""),
                    "is_leader": is_leader,
                    "leader_confirmed": conf.get("leader_confirmed", False),
                    "leader_name": _get_student_name(conf.get("leader", "")),
                    "members": members_info,
                    "my_confirmed": member_cfs.get(student_id, False),
                    "my_completed": my_task_done,
                    "my_score": my_score,
                })
                break
    return jsonify({"tasks": tasks})


@app.route("/api/manage/unfinished/<class_id>", methods=["GET"])
def api_get_unfinished(class_id):
    """获取未完成任务的学生名单"""
    cls = _runtime_store["classes"].get(class_id)
    if not cls:
        return jsonify({"error": "班级不存在"}), 404

    unfinished = []
    # 检查组任务
    for gtid, gt in _runtime_store["group_tasks"].items():
        if gt.get("class_id") != class_id:
            continue
        for gid, conf in gt.get("confirmations", {}).items():
            for mid in conf.get("members", []):
                member_cfs = conf.get("member_confirmations", {})
                # 1. 未确认接受任务
                if not member_cfs.get(mid, False):
                    unfinished.append({
                        "student_id": mid,
                        "name": _get_student_name(mid),
                        "avatar": _get_student_avatar(mid),
                        "task_title": gt.get("title", ""),
                        "task_id": gtid,
                        "reason": "未确认接受任务" if not conf.get("leader_confirmed") and conf.get("leader") == mid
                                  else ("组长未确认" if not conf.get("leader_confirmed") else "未确认接受"),
                        "group_name": conf.get("group_name", ""),
                        "is_leader": conf.get("leader") == mid,
                        "deadline": gt.get("deadline", ""),
                        "type": "confirm",
                    })
                else:
                    # 2. 已确认但未完成决策推演
                    mp = _runtime_store.get("progress", {}).get(mid, [])
                    task_done = any(
                        p.get("task_id") == gtid and p.get("status") == "completed"
                        for p in mp
                    )
                    if not task_done:
                        unfinished.append({
                            "student_id": mid,
                            "name": _get_student_name(mid),
                            "avatar": _get_student_avatar(mid),
                            "task_title": gt.get("title", ""),
                            "task_id": gtid,
                            "reason": "已确认任务，但尚未完成决策推演",
                            "group_name": conf.get("group_name", ""),
                            "is_leader": conf.get("leader") == mid,
                            "deadline": gt.get("deadline", ""),
                            "type": "decision",
                        })

    # 检查个人任务
    for tid, t in _runtime_store["tasks"].items():
        if t.get("class_id") != class_id:
            continue
        for sid in t.get("assignees", []):
            progress = _runtime_store.get("progress", {}).get(sid, [])
            p = next((p for p in progress if p.get("task_id") == tid), None)
            if not p or p.get("status") != "completed":
                unfinished.append({
                    "student_id": sid,
                    "name": _get_student_name(sid),
                    "avatar": _get_student_avatar(sid),
                    "task_title": t.get("title", ""),
                    "task_id": tid,
                    "reason": "未提交",
                    "deadline": t.get("deadline", ""),
                })

    return jsonify({"unfinished": unfinished, "total": len(unfinished)})


# --- 研：案例生成 ---
@app.route("/api/research/generate", methods=["POST"])
def api_generate_case():
    """基于全省物流数据自动生成教学案例"""
    data = request.get_json() or {}
    disaster_type = data.get("disaster_type", "earthquake")
    location = data.get("location", "")
    difficulty = data.get("difficulty", "medium")  # easy/medium/hard

    # 从物流数据获取仓库和路线信息
    try:
        logistics_data = PROVINCE_LOGISTICS
    except Exception:
        logistics_data = {}

    warehouses = logistics_data.get("warehouses", [])
    routes = logistics_data.get("roads", [])

    # 根据难度配置参数
    difficulty_config = {
        "easy": {"budget": 80000, "time_limit": 600, "cargo_count": 2},
        "medium": {"budget": 50000, "time_limit": 300, "cargo_count": 3},
        "hard": {"budget": 30000, "time_limit": 180, "cargo_count": 5},
    }
    config = difficulty_config.get(difficulty, difficulty_config["medium"])

    # 生成案例
    disaster_names = {
        "earthquake": "地震", "rainstorm": "暴雨", "typhoon": "台风",
        "flood": "洪水", "landslide": "山体滑坡", "mudslide": "泥石流"
    }

    case = {
        "case_id": f"CASE-{int(time.time())%1000000:06d}",
        "case_name": f"{location or '四川省'}{disaster_names.get(disaster_type, '自然灾害')}应急运输案例",
        "disaster_type": disaster_type,
        "location": location or "四川省",
        "difficulty": difficulty,
        "budget": config["budget"],
        "time_limit": config["time_limit"],
        "cargo_count": config["cargo_count"],
        "warehouse_count": len(warehouses) if warehouses else 5,
        "route_count": len(routes) if routes else 8,
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "description": f"在{location or '四川省'}发生{disaster_names.get(disaster_type, '自然灾害')}，"
                       f"需要紧急运输{config['cargo_count']}批救灾物资。"
                       f"预算{config['budget']}元，时限{config['time_limit']}秒。"
                       f"难度：{ {'easy':'初级','medium':'中级','hard':'高级'}[difficulty] }",
        "data_source": "全省物流信息库",
    }

    # 存储案例
    _runtime_store.setdefault("generated_cases", [])
    _runtime_store["generated_cases"].append(case)

    return jsonify({"status": "ok", "case": case})


@app.route("/api/research/cases", methods=["GET"])
def api_get_cases():
    """获取已生成的案例列表"""
    cases = _runtime_store.get("generated_cases", [])
    return jsonify({"cases": cases})


@app.route("/api/research/cases/<case_id>/import", methods=["POST"])
def api_import_case(case_id):
    """将生成的案例导入为教学场景"""
    cases = _runtime_store.get("generated_cases", [])
    case = next((c for c in cases if c.get("case_id") == case_id), None)
    if not case:
        return jsonify({"error": "案例不存在"}), 404

    # 转换为场景格式
    scenario = {
        "scenario_id": case["case_id"],
        "scenario_name": case["case_name"],
        "disaster": {
            "disaster_type": case["disaster_type"],
            "location": case["location"],
            "severity": case["difficulty"],
        },
        "budget": case["budget"],
        "time_limit": case["time_limit"],
        "strategy_mode": "time_pressure",
        "cargos": [
            {"id": f"C{i+1}", "name": f"救灾物资{i+1}", "weight": 500+i*200, "priority": "P1" if i == 0 else "P2"}
            for i in range(case["cargo_count"])
        ],
        "warehouses": [
            {"id": f"W{i+1}", "name": f"仓库{i+1}", "lat": 30.6+i*0.1, "lng": 104.0+i*0.05}
            for i in range(case["warehouse_count"])
        ],
        "vehicle_fleet": [
            {"type": "truck", "capacity": 2000, "cost_per_km": 8, "speed": 60, "count": 3},
            {"type": "van", "capacity": 800, "cost_per_km": 5, "speed": 80, "count": 2},
        ],
    }

    # 保存场景文件
    scenario_file = SCENARIOS_DIR / f"{scenario['scenario_id']}.json"
    with open(scenario_file, "w", encoding="utf-8") as f:
        json.dump(scenario, f, ensure_ascii=False, indent=2)

    return jsonify({"status": "ok", "scenario_id": scenario["scenario_id"]})


# --- 建：知识库建设 ---
_runtime_store.setdefault("knowledge_base", {
    "entities": [],       # 知识实体
    "relations": [],      # 关系
    "data_sources": [],   # 数据源
    "updates": [],        # 更新日志
})

@app.route("/api/knowledge/status", methods=["GET"])
def api_knowledge_status():
    """知识库状态概览"""
    kb = _runtime_store["knowledge_base"]
    return jsonify({
        "entity_count": len(kb.get("entities", [])),
        "relation_count": len(kb.get("relations", [])),
        "source_count": len(kb.get("data_sources", [])),
        "update_count": len(kb.get("updates", [])),
        "last_update": kb.get("updates", [{}])[-1].get("time", "") if kb.get("updates") else "",
        "categories": list(set(e.get("category", "其他") for e in kb.get("entities", []))),
    })


@app.route("/api/knowledge/entities", methods=["GET"])
def api_knowledge_entities():
    """知识实体列表"""
    kb = _runtime_store["knowledge_base"]
    category = request.args.get("category", "")
    entities = kb.get("entities", [])
    if category:
        entities = [e for e in entities if e.get("category") == category]
    return jsonify({"entities": entities})


@app.route("/api/knowledge/entities", methods=["POST"])
def api_add_entity():
    """新增知识实体"""
    data = request.get_json()
    entity = {
        "id": f"ENT-{int(time.time())%1000000:06d}",
        "name": data.get("name", ""),
        "category": data.get("category", "其他"),
        "description": data.get("description", ""),
        "properties": data.get("properties", {}),
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    _runtime_store["knowledge_base"]["entities"].append(entity)
    _runtime_store["knowledge_base"]["updates"].append({
        "type": "add_entity",
        "entity": entity["name"],
        "time": time.strftime("%Y-%m-%d %H:%M"),
    })
    return jsonify({"status": "ok", "entity": entity})


@app.route("/api/knowledge/sources", methods=["GET"])
def api_knowledge_sources():
    """数据源列表"""
    kb = _runtime_store["knowledge_base"]
    return jsonify({"sources": kb.get("data_sources", [])})


@app.route("/api/knowledge/sources", methods=["POST"])
def api_add_source():
    """接入新数据源"""
    data = request.get_json()
    source = {
        "id": f"SRC-{int(time.time())%1000000:06d}",
        "name": data.get("name", ""),
        "type": data.get("type", ""),  # api/database/file/manual
        "url": data.get("url", ""),
        "status": "connected",
        "record_count": data.get("record_count", 0),
        "added_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    _runtime_store["knowledge_base"]["data_sources"].append(source)
    _runtime_store["knowledge_base"]["updates"].append({
        "type": "add_source",
        "source": source["name"],
        "time": time.strftime("%Y-%m-%d %H:%M"),
    })
    return jsonify({"status": "ok", "source": source})


@app.route("/api/knowledge/graph", methods=["GET"])
def api_knowledge_graph():
    """知识图谱数据（节点+边）"""
    kb = _runtime_store["knowledge_base"]
    entities = kb.get("entities", [])
    relations = kb.get("relations", [])

    # 如果没有数据，返回预置的简化知识图谱
    if not entities:
        entities = [
            {"id": "ENT-001", "name": "地震", "category": "灾害", "description": "地壳振动引发的自然灾害"},
            {"id": "ENT-002", "name": "台风", "category": "灾害", "description": "热带气旋引发的强风暴雨"},
            {"id": "ENT-003", "name": "暴雨", "category": "灾害", "description": "短时间内大量降雨"},
            {"id": "ENT-004", "name": "洪涝灾害", "category": "灾害", "description": "暴雨导致河流泛滥成灾"},
            {"id": "ENT-005", "name": "泥石流", "category": "灾害", "description": "暴雨引发的山洪泥石流"},
            {"id": "ENT-006", "name": "森林火灾", "category": "灾害", "description": "失去控制的林火灾害"},
            {"id": "ENT-007", "name": "公路运输", "category": "运输方式", "description": "货车公路物资运输"},
            {"id": "ENT-008", "name": "无人机运输", "category": "运输方式", "description": "无人飞行器空投物资"},
            {"id": "ENT-009", "name": "铁路运输", "category": "运输方式", "description": "铁路网大宗物资运输"},
            {"id": "ENT-010", "name": "应急物资储备库", "category": "基础设施", "description": "存储救灾应急物资的仓库"},
            {"id": "ENT-011", "name": "应急避难场所", "category": "基础设施", "description": "安置受灾群众的场所"},
            {"id": "ENT-012", "name": "物资调度", "category": "决策", "description": "应急物资分配与调度决策"},
            {"id": "ENT-013", "name": "路径规划", "category": "决策", "description": "选择最优运输路径"},
            {"id": "ENT-014", "name": "风险评估", "category": "决策", "description": "灾害风险评估与控制"},
            {"id": "ENT-015", "name": "应急预案", "category": "决策", "description": "预先制定的应对方案"},
            {"id": "ENT-016", "name": "应急管理部", "category": "组织", "description": "国家应急管理主管部门"},
            {"id": "ENT-017", "name": "消防救援队伍", "category": "组织", "description": "抢险救援的专业力量"},
            {"id": "ENT-018", "name": "GIS地理信息系统", "category": "技术", "description": "灾害空间分析与管理"},
            {"id": "ENT-019", "name": "遥感监测", "category": "技术", "description": "卫星遥感灾害监测"},
            {"id": "ENT-020", "name": "AI智能决策", "category": "技术", "description": "AI辅助灾害应急决策"},
        ]
        relations = [
            {"source": "ENT-001", "target": "ENT-010", "relation": "破坏"},
            {"source": "ENT-001", "target": "ENT-012", "relation": "触发"},
            {"source": "ENT-002", "target": "ENT-003", "relation": "伴随"},
            {"source": "ENT-002", "target": "ENT-012", "relation": "触发"},
            {"source": "ENT-003", "target": "ENT-004", "relation": "引发"},
            {"source": "ENT-003", "target": "ENT-005", "relation": "引发"},
            {"source": "ENT-004", "target": "ENT-012", "relation": "触发"},
            {"source": "ENT-005", "target": "ENT-007", "relation": "阻断"},
            {"source": "ENT-006", "target": "ENT-017", "relation": "需应对"},
            {"source": "ENT-007", "target": "ENT-012", "relation": "执行"},
            {"source": "ENT-007", "target": "ENT-013", "relation": "依赖"},
            {"source": "ENT-008", "target": "ENT-012", "relation": "辅助"},
            {"source": "ENT-009", "target": "ENT-012", "relation": "执行"},
            {"source": "ENT-010", "target": "ENT-011", "relation": "供应"},
            {"source": "ENT-012", "target": "ENT-014", "relation": "基于"},
            {"source": "ENT-012", "target": "ENT-013", "relation": "采用"},
            {"source": "ENT-013", "target": "ENT-018", "relation": "依赖"},
            {"source": "ENT-014", "target": "ENT-015", "relation": "驱动"},
            {"source": "ENT-015", "target": "ENT-016", "relation": "由…制定"},
            {"source": "ENT-016", "target": "ENT-017", "relation": "指挥"},
            {"source": "ENT-018", "target": "ENT-014", "relation": "支持"},
            {"source": "ENT-019", "target": "ENT-018", "relation": "提供数据"},
            {"source": "ENT-020", "target": "ENT-012", "relation": "赋能"},
        ]
        kb["entities"] = entities
        kb["relations"] = relations

    return jsonify({
        "nodes": [{"id": e["id"], "name": e["name"], "category": e.get("category", ""),
                    "description": e.get("description", "")} for e in entities],
        "edges": [{"source": r["source"], "target": r["target"], "relation": r.get("relation", "")} for r in relations],
    })


@app.route("/api/knowledge/updates", methods=["GET"])
def api_knowledge_updates():
    """知识库更新日志"""
    kb = _runtime_store["knowledge_base"]
    updates = kb.get("updates", [])[-20:]  # 最近20条
    updates.reverse()
    return jsonify({"updates": updates})


# ============================================================
# 场景管理 API
# ============================================================

@app.route("/api/scenarios", methods=["GET"])
def list_scenarios():
    """列出所有场景"""
    scenarios = []
    if SCENARIOS_DIR.exists():
        for f in sorted(SCENARIOS_DIR.glob("*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                scenarios.append({
                    "scenario_id": data.get("scenario_id", f.stem),
                    "scenario_name": data.get("scenario_name", ""),
                    "disaster_type": data.get("disaster", {}).get("disaster_type", ""),
                    "file_name": f.name,
                    "node_count": len(data.get("logistics_network", {}).get("nodes", [])),
                    "road_count": len(data.get("logistics_network", {}).get("roads", [])),
                    "vehicle_count": len(data.get("vehicle_fleet", [])),
                    "warehouse_count": len(data.get("warehouses", [])),
                    "cargo_count": len(data.get("cargo_manifest", [])),
                    "strategy_mode": data.get("strategy_config", {}).get("mode", "time_pressure"),
                })
            except Exception as e:
                scenarios.append({
                    "scenario_id": f.stem,
                    "scenario_name": f"加载失败: {e}",
                    "file_name": f.name,
                })
    return jsonify(scenarios)


@app.route("/api/scenarios/<scenario_id>", methods=["GET"])
def get_scenario(scenario_id):
    """获取单个场景详情"""
    # 按文件名或scenario_id查找
    for f in SCENARIOS_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("scenario_id") == scenario_id or f.stem == scenario_id:
                return jsonify(data)
        except:
            continue
    return jsonify({"error": "场景不存在"}), 404


@app.route("/api/scenarios", methods=["POST"])
def save_scenario():
    """保存/创建场景"""
    data = request.get_json()
    scenario_id = data.get("scenario_id", f"SCENE-{uuid.uuid4().hex[:8]}")
    data["scenario_id"] = scenario_id
    data["created_at"] = data.get("created_at", datetime.now().isoformat(timespec="minutes"))
    
    filename = f"{scenario_id}.json"
    filepath = SCENARIOS_DIR / filename
    save_scenario_to_file(data, str(filepath))
    
    return jsonify({"status": "ok", "scenario_id": scenario_id, "file": filename})


@app.route("/api/scenarios/<scenario_id>", methods=["DELETE"])
def delete_scenario(scenario_id):
    """删除场景"""
    for f in SCENARIOS_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("scenario_id") == scenario_id or f.stem == scenario_id:
                os.remove(str(f))
                return jsonify({"status": "ok", "deleted": scenario_id})
        except:
            continue
    return jsonify({"error": "场景不存在"}), 404


# ============================================================
# 决策引擎 API
# ============================================================

@app.route("/api/engine/solve", methods=["POST"])
def engine_solve():
    """运行决策引擎，返回最优方案"""
    data = request.get_json()
    scenario_id = data.get("scenario_id", "")
    
    # 从请求中加载场景
    scenario_data = data.get("scenario_data")
    if not scenario_data:
        # 从文件加载
        for f in SCENARIOS_DIR.glob("*.json"):
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("scenario_id") == scenario_id or f.stem == scenario_id:
                scenario_data = d
                break
    
    if not scenario_data:
        return jsonify({"error": "场景数据缺失"}), 400
    
    try:
        scenario = load_scenario_from_dict(scenario_data)
        plan = engine.solve(scenario)
        impact_summary = engine.get_impact_summary()
        
        result = plan.to_dict()
        result["impact_summary"] = impact_summary
        result["scenario_info"] = {
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.scenario_name,
            "disaster_type": scenario.disaster.disaster_type.value,
            "node_count": len(scenario.logistics_network.nodes),
            "road_count": len(scenario.logistics_network.roads),
            "vehicle_count": len(scenario.vehicle_fleet),
            "warehouse_count": len(scenario.warehouses),
            "cargo_count": len(scenario.cargo_manifest),
        }
        result["map_data"] = _extract_map_data(scenario)
        
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/engine/comment", methods=["POST"])
def generate_comment():
    """生成智能评语"""
    data = request.get_json()
    score_data = data.get("score_breakdown", {})
    total_score = data.get("total_score", 0)
    disaster_type = data.get("disaster_type", "earthquake")
    literacy_profile = data.get("literacy_profile")
    
    from emergency_decision.models import (
        DimensionScore, ScoreBreakdown
    )
    
    breakdown = ScoreBreakdown(
        timeliness=DimensionScore(
            score=score_data.get("timeliness", {}).get("score", 0),
            reason=score_data.get("timeliness", {}).get("reason", "")),
        economic=DimensionScore(
            score=score_data.get("economic", {}).get("score", 0),
            reason=score_data.get("economic", {}).get("reason", "")),
        feasibility=DimensionScore(
            score=score_data.get("feasibility", {}).get("score", 0),
            reason=score_data.get("feasibility", {}).get("reason", "")),
        compliance=DimensionScore(
            score=score_data.get("compliance", {}).get("score", 0),
            reason=score_data.get("compliance", {}).get("reason", "")),
    )
    
    from emergency_decision.models import DecisionPlan
    plan = DecisionPlan(
        plan_id="TEMP", scenario_id="", generated_at="",
        total_cost=0, total_delay_hours=0, vehicles_used=0,
        warehouses_used=0, cargo_delivered=0, cargo_abandoned=0,
        cargo_stored=0, actions=[], score_breakdown=breakdown,
    )
    
    comment = engine.generate_comment(plan, disaster_type, literacy_profile)
    return jsonify({"comment": comment})


# ============================================================
# 策略适配 API
# ============================================================

@app.route("/api/strategy/context", methods=["POST"])
def strategy_context():
    """获取策略上下文 (策略二隐藏干扰 / 策略三预算约束)"""
    data = request.get_json()
    scenario_id = data.get("scenario_id")
    plan_data = data.get("optimal_plan")
    
    # 加载场景
    scenario_data = data.get("scenario_data")
    if not scenario_data:
        for f in SCENARIOS_DIR.glob("*.json"):
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("scenario_id") == scenario_id or f.stem == scenario_id:
                scenario_data = d
                break
    
    if not scenario_data or not plan_data:
        return jsonify({"error": "缺少场景或方案数据"}), 400
    
    try:
        scenario = load_scenario_from_dict(scenario_data)
        
        # 重建DecisionPlan
        from emergency_decision.models import DecisionPlan, Action, ScoreBreakdown, DimensionScore
        actions = []
        for a in plan_data.get("actions", []):
            actions.append(Action(
                action_id=a["action_id"],
                action_type=ActionPlanType(a["type"]),
                description=a["description"],
                cargo_ids=a.get("cargo_ids", []),
                vehicle_id=a.get("vehicle_id", ""),
                new_route=a.get("new_route", []),
                original_route=a.get("original_route", []),
                warehouse_id=a.get("warehouse_id", ""),
                extra_cost=a.get("extra_cost", 0),
                extra_time_min=a.get("extra_time_min", 0),
                risk_score=a.get("risk_score", 0),
                storage_cost=a.get("storage_cost", 0),
                value_loss=a.get("value_loss", 0),
                reason=a.get("reason", ""),
            ))
        
        sb = plan_data.get("score_breakdown", {})
        score_breakdown = None
        if sb:
            score_breakdown = ScoreBreakdown(
                timeliness=DimensionScore(sb.get("timeliness", {}).get("score", 0), sb.get("timeliness", {}).get("reason", "")),
                economic=DimensionScore(sb.get("economic", {}).get("score", 0), sb.get("economic", {}).get("reason", "")),
                feasibility=DimensionScore(sb.get("feasibility", {}).get("score", 0), sb.get("feasibility", {}).get("reason", "")),
                compliance=DimensionScore(sb.get("compliance", {}).get("score", 0), sb.get("compliance", {}).get("reason", "")),
            )
        
        plan = DecisionPlan(
            plan_id=plan_data.get("plan_id", ""),
            scenario_id=plan_data.get("scenario_id", ""),
            generated_at=plan_data.get("generated_at", ""),
            total_cost=plan_data.get("total_cost", 0),
            total_delay_hours=plan_data.get("total_delay_hours", 0),
            vehicles_used=plan_data.get("vehicles_used", 0),
            warehouses_used=plan_data.get("warehouses_used", 0),
            cargo_delivered=plan_data.get("cargo_delivered", 0),
            cargo_abandoned=plan_data.get("cargo_abandoned", 0),
            cargo_stored=plan_data.get("cargo_stored", 0),
            actions=actions,
            score_breakdown=score_breakdown,
            alternatives=plan_data.get("alternatives", []),
        )
        
        ctx = strategy_ctrl.get_strategy_context(plan, scenario)
        return jsonify(ctx)
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/strategy/budget/validate", methods=["POST"])
def validate_budget():
    """策略三: 校验学生方案是否超出预算"""
    data = request.get_json()
    student_actions = data.get("actions", [])
    budget_data = data.get("budget", {})
    
    from emergency_decision.strategy_adaptations import BudgetConstraint, BudgetValidator
    budget = BudgetConstraint(
        max_vehicles=budget_data.get("max_vehicles", 999),
        max_warehouses=budget_data.get("max_warehouses", 999),
        max_total_cost=budget_data.get("max_total_cost", 999999),
        max_abandon_value=budget_data.get("max_abandon_value", 999999),
    )
    validator = BudgetValidator()
    result = validator.validate(student_actions, budget)
    return jsonify(result)


# ============================================================
# 学生决策 + 行为埋点 API
# ============================================================

@app.route("/api/session/start", methods=["POST"])
def start_session():
    """开始一次决策会话"""
    data = request.get_json()
    student_id = data.get("student_id", f"STU-{uuid.uuid4().hex[:6]}")
    scenario_id = data.get("scenario_id", "")
    session_id = f"SES-{uuid.uuid4().hex[:8]}"
    
    session = behavior_tracker.start_session(session_id, student_id, scenario_id)
    
    _runtime_store["sessions"][session_id] = {
        "student_id": student_id,
        "scenario_id": scenario_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    
    return jsonify({
        "session_id": session_id,
        "student_id": student_id,
        "scenario_id": scenario_id,
    })


@app.route("/api/behavior/track", methods=["POST"])
def track_behavior():
    """记录行为事件"""
    data = request.get_json()
    session_id = data.get("session_id")
    event_type = data.get("event_type")
    detail = data.get("detail", {})
    
    behavior_tracker.record_event(session_id, event_type, detail)
    
    if session_id not in _runtime_store["behavior_events"]:
        _runtime_store["behavior_events"][session_id] = []
    _runtime_store["behavior_events"][session_id].append({
        "event_type": event_type,
        "timestamp": time.time(),
        "detail": detail,
    })
    
    return jsonify({"status": "ok"})


@app.route("/api/student/submit", methods=["POST"])
def submit_student_plan():
    """学生提交决策方案"""
    data = request.get_json()
    session_id = data.get("session_id")
    scenario_id = data.get("scenario_id")
    student_id = data.get("student_id", "STU-001")
    actions = data.get("actions", [])
    submit_time = data.get("submit_time_sec", 0)
    gtask_id = data.get("gtask_id")  # 组任务ID
    
    # 记录提交
    behavior_tracker.record_submit(session_id, actions)
    
    # 加载场景并评估
    scenario_data = data.get("scenario_data")
    if not scenario_data:
        for f in SCENARIOS_DIR.glob("*.json"):
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("scenario_id") == scenario_id or f.stem == scenario_id:
                scenario_data = d
                break
    
    if not scenario_data:
        return jsonify({"error": "场景数据缺失"}), 400
    
    try:
        scenario = load_scenario_from_dict(scenario_data)
        
        # 先运行引擎获取最优方案
        optimal_plan = engine.solve(scenario)
        
        # 构建学生提交
        student_actions = []
        for a in actions:
            student_actions.append(StudentAction(
                cargo_id=a.get("cargo_id", ""),
                action_type=ActionPlanType(a.get("action_type", "reroute")),
                vehicle_id=a.get("vehicle_id", ""),
                route=a.get("route", []),
                warehouse_id=a.get("warehouse_id", ""),
            ))
        
        submission = StudentSubmission(
            student_id=student_id,
            scenario_id=scenario_id,
            actions=student_actions,
            submit_time_offset_sec=submit_time,
            is_first_submit=True,
        )
        
        # 评估
        comparison = evaluator.evaluate(
            submission, scenario.cargo_manifest, scenario.evaluation,
            optimal_plan,
            available_vehicles=len(scenario.vehicle_fleet),
            available_warehouses=len(scenario.warehouses),
        )
        
        # 生成评语
        comment = engine.generate_comment(
            optimal_plan,
            disaster_type=scenario.disaster.disaster_type.value,
        )
        
        # 生成素养画像
        raw_metrics = behavior_tracker.get_raw_metrics(session_id)
        profile = profile_gen.generate(
            raw_metrics, student_id, scenario_id)
        growth_tracker.add_record(student_id, profile, session_id)
        
        # 存储结果
        if student_id not in _runtime_store["profiles"]:
            _runtime_store["profiles"][student_id] = []
        _runtime_store["profiles"][student_id].append(profile.to_dict())
        
        result = {
            "comparison": comparison,
            "comment": comment,
            "profile": profile.to_dict(),
            "optimal_plan": optimal_plan.to_dict(),
        }
        
        # ===== 救灾决策模式: 额外返回安全+速度考核评分 =====
        strategy_mode = scenario_data.get("strategy_config", {}).get("mode", "time_pressure")
        if strategy_mode == "emergency_relief":
            from emergency_decision.strategy_adaptations import EmergencyReliefAssessor
            assessor = EmergencyReliefAssessor()
            assessment = assessor.assess(
                student_actions=actions,
                optimal_plan=optimal_plan,
                scenario=scenario,
                submit_time_sec=submit_time,
            )
            result["emergency_assessment"] = assessment.to_dict()
        
        _runtime_store["results"][session_id] = result

        # ===== 同步更新组任务进度 =====
        if gtask_id:
            from datetime import datetime as dt
            # 1. 写入个人进度记录
            _runtime_store.setdefault("progress", {})
            if student_id not in _runtime_store["progress"]:
                _runtime_store["progress"][student_id] = []
            # 避免重复记录
            existing = [p for p in _runtime_store["progress"][student_id]
                        if p.get("task_id") == gtask_id]
            if not existing:
                _runtime_store["progress"][student_id].append({
                    "task_id": gtask_id,
                    "type": "group_task",
                    "status": "completed",
                    "submit_time": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "score": profile.to_dict()["overall"]["score"],
                    "session_id": session_id,
                    "scenario_id": scenario_id,
                })

            # 2. 检查整组成员是否全部完成 → 更新组任务状态
            gt = _runtime_store["group_tasks"].get(gtask_id)
            if gt:
                # 收集所有成员列表
                all_members = set()
                for gid, conf in gt.get("confirmations", {}).items():
                    for mid in conf.get("members", []):
                        all_members.add(mid)

                # 检查每个成员的 progress 是否都有该任务的 completed 记录
                all_completed = True
                for mid in all_members:
                    member_progress = _runtime_store["progress"].get(mid, [])
                    found = any(
                        p.get("task_id") == gtask_id and p.get("status") == "completed"
                        for p in member_progress
                    )
                    if not found:
                        all_completed = False
                        break

                if all_completed:
                    gt["status"] = "completed"

        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


# ============================================================
# 素养画像 API
# ============================================================

@app.route("/api/profile/<student_id>", methods=["GET"])
def get_profile(student_id):
    """获取学生素养画像"""
    profiles = _runtime_store["profiles"].get(student_id, [])
    if not profiles:
        # 返回一个模拟画像供前端展示
        return jsonify({
            "student_id": student_id,
            "radar_data": {"labels": ["风险意识", "系统思维", "决策韧性"], "values": [0, 0, 0]},
            "dimensions": {},
            "overall": {"score": 0, "level": "D", "level_desc": "暂无数据"},
            "message": "该学生尚未完成决策推演，暂无画像数据"
        })
    return jsonify(profiles[-1])


@app.route("/api/profile/<student_id>/growth", methods=["GET"])
def get_growth(student_id):
    """获取学生成长曲线"""
    curve = growth_tracker.get_growth_curve(student_id)
    return jsonify(curve)


# ============================================================
# 教师后台 API
# ============================================================

@app.route("/api/my-scores/<student_id>", methods=["GET"])
def my_scores(student_id):
    """学生查看自己的成绩记录"""
    profiles = _runtime_store["profiles"].get(student_id, [])
    score_list = []
    for p in profiles:
        overall = p.get("overall", {})
        score_list.append({
            "session_id": p.get("session_id", ""),
            "scenario_id": p.get("scenario_id", ""),
            "score": overall.get("score", 0),
            "level": overall.get("level", "D"),
            "level_desc": overall.get("level_desc", ""),
            "dimensions": p.get("dimensions", {}),
            "radar_data": p.get("radar_data", {}),
            "created_at": p.get("created_at", ""),
        })
    # 平均分
    avg_score = round(sum(s["score"] for s in score_list) / len(score_list), 1) if score_list else 0
    return jsonify({
        "student_id": student_id,
        "total_sessions": len(score_list),
        "avg_score": avg_score,
        "scores": score_list,
    })


@app.route("/api/teacher/dashboard", methods=["GET"])
def teacher_dashboard():
    """教师后台: 班级画像分布"""
    all_students = list(_runtime_store["profiles"].keys())
    if not all_students:
        return jsonify({
            "total_students": 0,
            "distribution": {
                "risk_awareness": {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0},
                "system_thinking": {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0},
                "decision_resilience": {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0},
            },
            "student_scores": [],
        })
    
    dist = growth_tracker.get_class_distribution(all_students)
    return jsonify(dist)


# ============================================================
# 实时灾害数据 API (地震台网 / 台风网 / 天气预警)
# ============================================================

@app.route("/api/realtime/earthquakes", methods=["GET"])
def realtime_earthquakes():
    """获取中国地震台网最新地震列表"""
    try:
        min_mag = float(request.args.get("min_magnitude", 0))
        limit = int(request.args.get("limit", 50))
        data = EarthquakeDataFetcher.fetch_as_dict(min_magnitude=min_mag, limit=limit)
        return jsonify({"count": len(data), "earthquakes": data, "source": "中国地震台网"})
    except Exception as e:
        return jsonify({"error": str(e), "earthquakes": []}), 500


@app.route("/api/realtime/earthquakes/<event_id>", methods=["GET"])
def realtime_earthquake_detail(event_id):
    """获取单条地震详情"""
    eq = EarthquakeDataFetcher.find_by_id(event_id)
    if eq:
        return jsonify(eq.to_dict())
    return jsonify({"error": "未找到该地震记录"}), 404


@app.route("/api/realtime/typhoons", methods=["GET"])
def realtime_typhoons():
    """获取台风列表"""
    try:
        year = request.args.get("year")
        if year:
            year = int(year)
        data = TyphoonDataFetcher.fetch_list_as_dict(year=year)
        return jsonify({"count": len(data), "typhoons": data, "source": "中央气象台台风网"})
    except Exception as e:
        return jsonify({"error": str(e), "typhoons": []}), 500


@app.route("/api/realtime/typhoons/<int:typhoon_id>", methods=["GET"])
def realtime_typhoon_detail(typhoon_id):
    """获取台风路径详情"""
    try:
        detail = TyphoonDataFetcher.fetch_detail(typhoon_id)
        if detail:
            return jsonify(detail)
        return jsonify({"error": "未找到该台风或数据获取失败"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/realtime/alerts", methods=["GET"])
def realtime_alerts():
    """获取天气预警(暴雨/洪水/地质灾害/山洪)"""
    try:
        alert_type = request.args.get("type")
        data = WeatherAlertFetcher.fetch_as_dict(alert_type=alert_type)
        types = WeatherAlertFetcher.get_disaster_types()
        return jsonify({
            "count": len(data),
            "alerts": data,
            "available_types": types,
            "source": "国家气象预警信息",
        })
    except Exception as e:
        return jsonify({"error": str(e), "alerts": []}), 500


@app.route("/api/realtime/import-earthquake", methods=["POST"])
def import_earthquake_as_scenario():
    """将真实地震数据导入为教学场景

    根据地震参数自动生成一套教学场景(物流网络、车辆、仓库、货物)
    """
    try:
        data = request.get_json()
        event_id = data.get("event_id")
        if not event_id:
            return jsonify({"error": "缺少event_id参数"}), 400

        eq = EarthquakeDataFetcher.find_by_id(event_id)
        if not eq:
            return jsonify({"error": f"未找到地震记录: {event_id}"}), 404

        # 转换为场景参数
        params = earthquake_to_scenario_params(eq)

        # 生成完整场景JSON
        scenario = _generate_scenario_from_earthquake(eq, params)
        scenario_id = scenario["scenario_id"]

        # 保存场景文件
        filepath = SCENARIOS_DIR / f"{scenario_id}.json"
        save_scenario_to_file(scenario, str(filepath))

        return jsonify({
            "status": "ok",
            "scenario_id": scenario_id,
            "scenario_name": scenario["scenario_name"],
            "file": f"{scenario_id}.json",
            "earthquake_params": params,
            "message": f"已将地震「{eq.location} M{eq.magnitude}」导入为教学场景",
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


def _generate_scenario_from_earthquake(eq, params) -> dict:
    """根据真实地震参数生成教学场景JSON"""
    import math

    lat, lng = eq.latitude, eq.longitude
    radius = params["influence_radius_km"]

    # 在震中周围生成4个物流节点
    nodes = []
    node_cities = [
        (f"震中({eq.location})", 0),
        ("北向60km", 60),
        ("东向80km", 80),
        ("南向50km", 50),
    ]
    for i, (label, dist_km) in enumerate(node_cities):
        # 简单偏移: 经度每度约85km, 纬度每度约111km
        if i == 0:
            n_lat, n_lng = lat, lng
        elif i == 1:
            n_lat, n_lng = lat + dist_km / 111, lng
        elif i == 2:
            n_lat, n_lng = lat, lng + dist_km / 85
        else:
            n_lat, n_lng = lat - dist_km / 111, lng
        nodes.append({
            "node_id": f"NODE-EQ{i:02d}",
            "node_name": label,
            "node_type": "warehouse" if i == 0 else "city",
            "city": eq.location if i == 0 else f"震中{label}",
            "lat": round(n_lat, 4),
            "lng": round(n_lng, 4),
        })

    # 路段: 震中-北, 震中-东, 震中-南, 北-东, 东-南
    roads = []
    road_defs = [
        ("R-01", "震中-北", "NODE-EQ00", "NODE-EQ01", 60, True, False),
        ("R-02", "震中-东", "NODE-EQ00", "NODE-EQ02", 80, False, True),
        ("R-03", "震中-南", "NODE-EQ00", "NODE-EQ03", 50, False, False),
        ("R-04", "北-东", "NODE-EQ01", "NODE-EQ02", 100, False, False),
        ("R-05", "东-南", "NODE-EQ02", "NODE-EQ03", 95, False, False),
    ]
    for rid, name, fn, tn, dist, bridge, tunnel in road_defs:
        roads.append({
            "road_id": rid,
            "road_name": name,
            "from_node": fn,
            "to_node": tn,
            "road_type": "highway",
            "is_bidirectional": True,
            "distance_km": dist,
            "speed_limit_kmh": 80,
            "current_travel_time_min": round(dist / 80 * 60),
            "road_condition": "clear",
            "has_bridge": bridge,
            "has_tunnel": tunnel,
            "capacity_per_hour": 2000,
            "toll_cost": dist * 0.5,
            "fuel_cost_per_km": 0.8,
        })

    # 车辆
    province_name = params.get("province", "")
    plate_prefix = get_license_plate_prefix(province_name)
    vehicles = []
    for i in range(4):
        n = nodes[i % len(nodes)]
        vehicles.append({
            "vehicle_id": f"V-EQ{i+1:02d}",
            "license_plate": f"{plate_prefix}A{10000+i}",
            "vehicle_type": "box_truck",
            "capacity_tons": 10,
            "capacity_m3": 40,
            "current_location_node": n["node_id"],
            "current_lat": n["lat"],
            "current_lng": n["lng"],
            "status": "idle",
            "current_cargo_ids": [],
            "current_load_tons": 0,
            "current_load_m3": 0,
            "driver_name": f"司机{i+1}",
            "home_depot": n["node_id"],
            "cost_per_km": 8,
            "cost_per_hour": 60,
            "is_refrigerated": False,
        })

    # 仓库
    warehouses = [
        {
            "warehouse_id": "WH-EQ01",
            "warehouse_name": f"{eq.location}中转仓",
            "city": eq.location,
            "address": f"{eq.location}物流园",
            "lat": lat,
            "lng": lng,
            "node_id": "NODE-EQ00",
            "total_capacity_m3": 5000,
            "used_capacity_m3": 2000,
            "storage_cost_per_m3_per_day": 2.5,
            "supported_cargo_types": ["normal"],
            "has_cold_chain": False,
            "has_dock": 4,
            "dock_occupancy": 1,
            "is_24h": True,
            "damage_status": "damaged" if eq.magnitude >= 5 else "normal",
        },
        {
            "warehouse_id": "WH-EQ02",
            "warehouse_name": "北向备选仓",
            "city": nodes[1]["node_name"],
            "address": "北向物流中心",
            "lat": nodes[1]["lat"],
            "lng": nodes[1]["lng"],
            "node_id": "NODE-EQ01",
            "total_capacity_m3": 3000,
            "used_capacity_m3": 500,
            "storage_cost_per_m3_per_day": 2.0,
            "supported_cargo_types": ["normal"],
            "has_cold_chain": False,
            "has_dock": 3,
            "dock_occupancy": 0,
            "is_24h": True,
            "damage_status": "normal",
        },
    ]

    # 货物
    cargos = []
    cargo_defs = [
        ("C-EQ01", "PO-EQ01", "medical", "急救药品一批", 3, 15, 50000, "P1", "NODE-EQ00", f"{eq.location}医院", "NODE-EQ01", 0, 0),
        ("C-EQ02", "PO-EQ02", "supplies", "帐篷被褥", 8, 30, 30000, "P2", "NODE-EQ00", "灾区安置点", "NODE-EQ02", 0, 0),
        ("C-EQ03", "PO-EQ03", "supplies", "矿泉水食品", 10, 20, 15000, "P3", "NODE-EQ00", "灾区物资点", "NODE-EQ03", 0, 0),
        ("C-EQ04", "PO-EQ04", "normal", "电子设备", 2, 8, 80000, "P3", "NODE-EQ01", "北向中转", "NODE-EQ02", 0, 0),
        ("C-EQ05", "PO-EQ05", "supplies", "建材物资", 6, 25, 20000, "P2", "NODE-EQ02", "南向重建", "NODE-EQ03", 0, 0),
    ]
    for cid, order, ctype, desc, wt, vol, val, pri, origin, origin_name, dest, d_lat, d_lng in cargo_defs:
        dest_node = [n for n in nodes if n["node_id"] == dest]
        dlat = dest_node[0]["lat"] if dest_node else 0
        dlng = dest_node[0]["lng"] if dest_node else 0
        cargos.append({
            "cargo_id": cid,
            "order_no": order,
            "cargo_type": ctype,
            "description": desc,
            "weight_tons": wt,
            "volume_m3": vol,
            "value_yuan": val,
            "priority_level": pri,
            "requires_cold_chain": False,
            "is_hazardous": False,
            "origin_node": origin,
            "origin_name": origin_name,
            "destination_node": dest,
            "destination_name": f"{dest}目的地",
            "destination_lat": dlat,
            "destination_lng": dlng,
            "assigned_vehicle_id": "",
            "current_status": "pending",
            "current_location_node": origin,
            "planned_route": [origin, dest],
            "current_route_index": 0,
            "departure_time": "",
            "deadline": "",
            "contract_penalty_per_hour": 500,
            "customer_id": f"CUST-{cid}",
            "customer_name": f"{origin_name}客户",
            "customer_type": "enterprise",
        })

    scenario_id = f"RT-EQ-{eq.event_id.split('.')[-1]}"

    return {
        "scenario_id": scenario_id,
        "scenario_name": f"真实地震场景 - {eq.location} M{eq.magnitude}",
        "scenario_description": (
            f"基于中国地震台网实时数据生成。"
            f"发震时间: {eq.time}，震源: {eq.location}，"
            f"震级: M{eq.magnitude}，震源深度: {eq.depth}km，"
            f"烈度: {eq.intensity}度。{params['severity']}。"
            f"数据来源: {params['eq_type']}。"
        ),
        "disaster": {
            "disaster_id": f"DIS-EQ-{eq.event_id.split('.')[-1]}",
            "disaster_type": "earthquake",
            "center_lat": lat,
            "center_lng": lng,
            "influence_radius_km": radius,
            "affected_areas": [eq.location],
            "occurrence_time": eq.time,
            "earthquake": {
                "magnitude": eq.magnitude,
                "epicenter_city": eq.location,
                "epicenter_lat": lat,
                "epicenter_lng": lng,
                "depth_km": eq.depth,
                "influence_radius_km": radius,
                "occur_time": eq.time,
                "affected_areas": [eq.location],
                "severity_level": "severe" if eq.magnitude >= 6 else "moderate",
                "wave_arrival_times": [],
            },
        },
        "logistics_network": {"nodes": nodes, "roads": roads},
        "vehicle_fleet": vehicles,
        "warehouses": warehouses,
        "cargo_manifest": cargos,
        "evaluation": {
            "config_id": "EVAL-RT-EQ",
            "scenario_id": scenario_id,
            "benchmark_cost": 5000,
            "benchmark_delivery_time_hours": 48,
            "weights": {
                "timeliness": 0.30,
                "economic": 0.25,
                "feasibility": 0.25,
                "compliance": 0.20,
            },
            "bonus_rules": [{"rule": "first_submit_bonus", "score": 5}],
            "penalty_rules": [{"rule": "timeout_penalty", "score": -10}],
            "max_delay_hours": 48,
        },
        "strategy_config": {"mode": "time_pressure"},
        "realtime_source": {
            "event_id": eq.event_id,
            "source": "中国地震台网",
            "report_time": eq.report_time,
        },
        "created_at": datetime.now().isoformat(timespec="minutes"),
    }


# ============================================================
# 最新灾害预警汇总 API
# ============================================================

@app.route("/api/realtime/latest", methods=["GET"])
def realtime_latest():
    """获取最新灾害汇总（地震+台风+预警），用于首页预警动画"""
    try:
        limit = int(request.args.get("limit", 5))
        data = fetch_latest_disasters(limit=limit)
        return jsonify({"count": len(data), "disasters": data, "fetched_at": datetime.now().isoformat(timespec="seconds")})
    except Exception as e:
        return jsonify({"error": str(e), "disasters": []}), 500


@app.route("/api/realtime/import-typhoon", methods=["POST"])
def import_typhoon_as_scenario():
    """将真实台风数据导入为教学场景"""
    try:
        data = request.get_json()
        typhoon_id = data.get("typhoon_id")
        if not typhoon_id:
            return jsonify({"error": "缺少typhoon_id参数"}), 400

        detail = TyphoonDataFetcher.fetch_detail(int(typhoon_id))
        if not detail:
            return jsonify({"error": "未找到台风数据"}), 404

        params = typhoon_to_scenario_params(detail)
        scenario = _generate_scenario_from_typhoon(detail, params)
        scenario_id = scenario["scenario_id"]

        filepath = SCENARIOS_DIR / f"{scenario_id}.json"
        save_scenario_to_file(scenario, str(filepath))

        return jsonify({
            "status": "ok",
            "scenario_id": scenario_id,
            "scenario_name": scenario["scenario_name"],
            "file": f"{scenario_id}.json",
            "typhoon_params": params,
            "message": f"已将台风「{detail.get('chinese_name', '')}」导入为教学场景",
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/realtime/import-alert", methods=["POST"])
def import_alert_as_scenario():
    """将天气预警数据导入为教学场景"""
    try:
        data = request.get_json()
        alert_id = data.get("alert_id")
        if not alert_id:
            return jsonify({"error": "缺少alert_id参数"}), 400

        # 从缓存中查找预警
        alert = None
        for a in WeatherAlertFetcher.fetch():
            if a.alert_id == alert_id:
                alert = a.to_dict()
                break
        if not alert:
            return jsonify({"error": "未找到预警记录"}), 404

        params = weather_alert_to_scenario_params(alert)
        scenario = _generate_scenario_from_alert(alert, params)
        scenario_id = scenario["scenario_id"]

        filepath = SCENARIOS_DIR / f"{scenario_id}.json"
        save_scenario_to_file(scenario, str(filepath))

        return jsonify({
            "status": "ok",
            "scenario_id": scenario_id,
            "scenario_name": scenario["scenario_name"],
            "file": f"{scenario_id}.json",
            "alert_params": params,
            "message": f"已将预警「{alert.get('title', '')}」导入为教学场景",
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


def _generate_scenario_from_typhoon(detail, params) -> dict:
    """根据真实台风数据生成教学场景JSON"""
    lat = params.get("latitude") or 25.0
    lng = params.get("longitude") or 130.0
    radius = max(params.get("influence_radius_km", 350), 200)
    name = params.get("chinese_name", "") or params.get("english_name", "")

    nodes = [
        {"node_id": "NODE-TF00", "node_name": f"台风中心({name})", "node_type": "city", "city": name, "lat": round(lat, 4), "lng": round(lng, 4)},
        {"node_id": "NODE-TF01", "node_name": "沿海港口", "node_type": "warehouse", "city": "沿海", "lat": round(lat - 1, 4), "lng": round(lng - 1, 4)},
        {"node_id": "NODE-TF02", "node_name": "内陆枢纽", "node_type": "city", "city": "内陆", "lat": round(lat + 2, 4), "lng": round(lng - 2, 4)},
        {"node_id": "NODE-TF03", "node_name": "北部中转", "node_type": "city", "city": "北部", "lat": round(lat + 3, 4), "lng": round(lng, 4)},
    ]

    roads = [
        {"road_id": "R-T01", "road_name": "港口-内陆", "from_node": "NODE-TF01", "to_node": "NODE-TF02", "road_type": "highway", "is_bidirectional": True, "distance_km": 200, "speed_limit_kmh": 80, "current_travel_time_min": 150, "road_condition": "slow", "has_bridge": True, "has_tunnel": False, "capacity_per_hour": 2000, "toll_cost": 100, "fuel_cost_per_km": 0.8},
        {"road_id": "R-T02", "road_name": "港口-北部", "from_node": "NODE-TF01", "to_node": "NODE-TF03", "road_type": "highway", "is_bidirectional": True, "distance_km": 250, "speed_limit_kmh": 80, "current_travel_time_min": 188, "road_condition": "congested", "has_bridge": False, "has_tunnel": False, "capacity_per_hour": 1500, "toll_cost": 125, "fuel_cost_per_km": 0.8},
        {"road_id": "R-T03", "road_name": "内陆-北部", "from_node": "NODE-TF02", "to_node": "NODE-TF03", "road_type": "highway", "is_bidirectional": True, "distance_km": 150, "speed_limit_kmh": 100, "current_travel_time_min": 90, "road_condition": "clear", "has_bridge": False, "has_tunnel": True, "capacity_per_hour": 3000, "toll_cost": 75, "fuel_cost_per_km": 0.8},
        {"road_id": "R-T04", "road_name": "台风中心-港口", "from_node": "NODE-TF00", "to_node": "NODE-TF01", "road_type": "highway", "is_bidirectional": True, "distance_km": 100, "speed_limit_kmh": 60, "current_travel_time_min": 100, "road_condition": "blocked", "has_bridge": True, "has_tunnel": False, "capacity_per_hour": 500, "toll_cost": 50, "fuel_cost_per_km": 0.8},
    ]

    province_name = params.get("province", "")
    plate_prefix = get_license_plate_prefix(province_name)
    vehicles = []
    for i, n in enumerate(nodes):
        vehicles.append({
            "vehicle_id": f"V-TF{i+1:02d}", "license_plate": f"{plate_prefix}B{20000+i}", "vehicle_type": "box_truck",
            "capacity_tons": 12, "capacity_m3": 45, "current_location_node": n["node_id"],
            "current_lat": n["lat"], "current_lng": n["lng"], "status": "idle",
            "current_cargo_ids": [], "current_load_tons": 0, "current_load_m3": 0,
            "driver_name": f"司机{i+1}", "home_depot": n["node_id"], "cost_per_km": 8, "cost_per_hour": 60, "is_refrigerated": False,
        })

    warehouses = [
        {"warehouse_id": "WH-TF01", "warehouse_name": "沿海物流仓", "city": "沿海", "address": "沿海物流园", "lat": nodes[1]["lat"], "lng": nodes[1]["lng"], "node_id": "NODE-TF01", "total_capacity_m3": 6000, "used_capacity_m3": 3000, "storage_cost_per_m3_per_day": 2.5, "supported_cargo_types": ["normal"], "has_cold_chain": False, "has_dock": 6, "dock_occupancy": 3, "is_24h": True, "damage_status": "damaged"},
        {"warehouse_id": "WH-TF02", "warehouse_name": "内陆中转仓", "city": "内陆", "address": "内陆物流中心", "lat": nodes[2]["lat"], "lng": nodes[2]["lng"], "node_id": "NODE-TF02", "total_capacity_m3": 4000, "used_capacity_m3": 1000, "storage_cost_per_m3_per_day": 2.0, "supported_cargo_types": ["normal"], "has_cold_chain": False, "has_dock": 4, "dock_occupancy": 1, "is_24h": True, "damage_status": "normal"},
    ]

    cargos = [
        {"cargo_id": "C-TF01", "order_no": "PO-TF01", "cargo_type": "supplies", "description": "应急物资一批", "weight_tons": 8, "volume_m3": 30, "value_yuan": 40000, "priority_level": "P1", "requires_cold_chain": False, "is_hazardous": False, "origin_node": "NODE-TF01", "origin_name": "沿海仓库", "destination_node": "NODE-TF02", "destination_name": "内陆中转", "destination_lat": nodes[2]["lat"], "destination_lng": nodes[2]["lng"], "assigned_vehicle_id": "", "current_status": "pending", "current_location_node": "NODE-TF01", "planned_route": ["NODE-TF01", "NODE-TF02"], "current_route_index": 0, "departure_time": "", "deadline": "", "contract_penalty_per_hour": 500, "customer_id": "CUST-TF01", "customer_name": "应急物资客户", "customer_type": "enterprise"},
        {"cargo_id": "C-TF02", "order_no": "PO-TF02", "cargo_type": "medical", "description": "医疗急救包", "weight_tons": 2, "volume_m3": 10, "value_yuan": 60000, "priority_level": "P1", "requires_cold_chain": False, "is_hazardous": False, "origin_node": "NODE-TF01", "origin_name": "沿海仓库", "destination_node": "NODE-TF03", "destination_name": "北部医院", "destination_lat": nodes[3]["lat"], "destination_lng": nodes[3]["lng"], "assigned_vehicle_id": "", "current_status": "pending", "current_location_node": "NODE-TF01", "planned_route": ["NODE-TF01", "NODE-TF03"], "current_route_index": 0, "departure_time": "", "deadline": "", "contract_penalty_per_hour": 800, "customer_id": "CUST-TF02", "customer_name": "北部医院", "customer_type": "enterprise"},
        {"cargo_id": "C-TF03", "order_no": "PO-TF03", "cargo_type": "normal", "description": "建材物资", "weight_tons": 10, "volume_m3": 35, "value_yuan": 25000, "priority_level": "P3", "requires_cold_chain": False, "is_hazardous": False, "origin_node": "NODE-TF02", "origin_name": "内陆仓库", "destination_node": "NODE-TF03", "destination_name": "北部工地", "destination_lat": nodes[3]["lat"], "destination_lng": nodes[3]["lng"], "assigned_vehicle_id": "", "current_status": "pending", "current_location_node": "NODE-TF02", "planned_route": ["NODE-TF02", "NODE-TF03"], "current_route_index": 0, "departure_time": "", "deadline": "", "contract_penalty_per_hour": 300, "customer_id": "CUST-TF03", "customer_name": "北部工地", "customer_type": "enterprise"},
    ]

    scenario_id = f"RT-TF-{detail.get('typhoon_id', 'UNK')}"
    return {
        "scenario_id": scenario_id,
        "scenario_name": f"真实台风场景 - {name} ({params.get('current_level', '')})",
        "scenario_description": f"基于中央气象台台风网实时数据。台风名称: {name}，最大风速: {params.get('wind_speed', 0)}m/s，中心气压: {params.get('pressure', 0)}hPa。{params.get('severity', '')}",
        "disaster": {
            "disaster_id": f"DIS-TF-{detail.get('typhoon_id', 'UNK')}", "disaster_type": "typhoon",
            "center_lat": lat, "center_lng": lng, "influence_radius_km": radius,
            "affected_areas": [name], "occurrence_time": params.get("start_time", ""),
            "typhoon": {
                "typhoon_name": name, "center_lat": lat, "center_lng": lng,
                "wind_force_level": params.get("wind_speed", 0) * 2,
                "moving_speed_kmh": 25, "moving_direction": "西北",
                "landing_time": params.get("start_time", ""), "landing_location": name,
                "influence_radius_km": radius, "port_closure": True, "airport_closure": True,
                "affected_areas": [name],
            },
        },
        "logistics_network": {"nodes": nodes, "roads": roads},
        "vehicle_fleet": vehicles, "warehouses": warehouses, "cargo_manifest": cargos,
        "evaluation": {
            "config_id": "EVAL-RT-TF", "scenario_id": scenario_id,
            "benchmark_cost": 8000, "benchmark_delivery_time_hours": 48,
            "weights": {"timeliness": 0.30, "economic": 0.25, "feasibility": 0.25, "compliance": 0.20},
            "bonus_rules": [{"rule": "first_submit_bonus", "score": 5}],
            "penalty_rules": [{"rule": "timeout_penalty", "score": -10}],
            "max_delay_hours": 48,
        },
        "strategy_config": {"mode": "time_pressure"},
        "realtime_source": {"typhoon_id": detail.get("typhoon_id"), "source": "中央气象台台风网"},
        "created_at": datetime.now().isoformat(timespec="minutes"),
    }


def _generate_scenario_from_alert(alert, params) -> dict:
    """根据天气预警数据生成教学场景JSON"""
    lat = params.get("latitude") or 34.0
    lng = params.get("longitude") or 113.0
    radius = max(params.get("influence_radius_km", 150), 150)  # 确保足够覆盖所有节点
    alert_type = params.get("alert_type", "暴雨")
    disaster_type = params.get("disaster_type", "rainstorm")
    title = params.get("title", "")

    nodes = [
        {"node_id": "NODE-AL00", "node_name": "预警中心", "node_type": "warehouse", "city": params.get("province", ""), "lat": round(lat, 4), "lng": round(lng, 4)},
        {"node_id": "NODE-AL01", "node_name": "东部中转", "node_type": "city", "city": "东部", "lat": round(lat, 4), "lng": round(lng + 1, 4)},
        {"node_id": "NODE-AL02", "node_name": "南部配送", "node_type": "city", "city": "南部", "lat": round(lat - 1, 4), "lng": round(lng, 4)},
        {"node_id": "NODE-AL03", "node_name": "北部仓库", "node_type": "warehouse", "city": "北部", "lat": round(lat + 1, 4), "lng": round(lng, 4)},
    ]

    roads = [
        {"road_id": "R-A01", "road_name": "中心-东部", "from_node": "NODE-AL00", "to_node": "NODE-AL01", "road_type": "highway", "is_bidirectional": True, "distance_km": 80, "speed_limit_kmh": 80, "current_travel_time_min": 60, "road_condition": "congested", "has_bridge": False, "has_tunnel": False, "capacity_per_hour": 2000, "toll_cost": 40, "fuel_cost_per_km": 0.8},
        {"road_id": "R-A02", "road_name": "中心-南部", "from_node": "NODE-AL00", "to_node": "NODE-AL02", "road_type": "highway", "is_bidirectional": True, "distance_km": 70, "speed_limit_kmh": 80, "current_travel_time_min": 53, "road_condition": "slow", "has_bridge": True, "has_tunnel": False, "capacity_per_hour": 1500, "toll_cost": 35, "fuel_cost_per_km": 0.8},
        {"road_id": "R-A03", "road_name": "中心-北部", "from_node": "NODE-AL00", "to_node": "NODE-AL03", "road_type": "highway", "is_bidirectional": True, "distance_km": 90, "speed_limit_kmh": 100, "current_travel_time_min": 54, "road_condition": "clear", "has_bridge": False, "has_tunnel": True, "capacity_per_hour": 2500, "toll_cost": 45, "fuel_cost_per_km": 0.8},
        {"road_id": "R-A04", "road_name": "东部-南部", "from_node": "NODE-AL01", "to_node": "NODE-AL02", "road_type": "highway", "is_bidirectional": True, "distance_km": 100, "speed_limit_kmh": 80, "current_travel_time_min": 75, "road_condition": "blocked", "has_bridge": True, "has_tunnel": False, "capacity_per_hour": 1000, "toll_cost": 50, "fuel_cost_per_km": 0.8},
    ]

    province_name = params.get("province", "")
    plate_prefix = get_license_plate_prefix(province_name)

    vehicles = []
    for i, n in enumerate(nodes):
        vehicles.append({
            "vehicle_id": f"V-AL{i+1:02d}", "license_plate": f"{plate_prefix}A{30000+i}", "vehicle_type": "box_truck",
            "capacity_tons": 10, "capacity_m3": 40, "current_location_node": n["node_id"],
            "current_lat": n["lat"], "current_lng": n["lng"], "status": "idle",
            "current_cargo_ids": [], "current_load_tons": 0, "current_load_m3": 0,
            "driver_name": f"司机{i+1}", "home_depot": n["node_id"], "cost_per_km": 8, "cost_per_hour": 60, "is_refrigerated": False,
        })

    warehouses = [
        {"warehouse_id": "WH-AL01", "warehouse_name": "预警中心仓", "city": params.get("province", ""), "address": "物流中心", "lat": lat, "lng": lng, "node_id": "NODE-AL00", "total_capacity_m3": 5000, "used_capacity_m3": 2500, "storage_cost_per_m3_per_day": 2.5, "supported_cargo_types": ["normal"], "has_cold_chain": False, "has_dock": 5, "dock_occupancy": 2, "is_24h": True, "damage_status": "damaged" if params.get("level") == "红色" else "normal"},
        {"warehouse_id": "WH-AL02", "warehouse_name": "北部备选仓", "city": "北部", "address": "北部物流园", "lat": nodes[3]["lat"], "lng": nodes[3]["lng"], "node_id": "NODE-AL03", "total_capacity_m3": 3000, "used_capacity_m3": 500, "storage_cost_per_m3_per_day": 2.0, "supported_cargo_types": ["normal"], "has_cold_chain": False, "has_dock": 3, "dock_occupancy": 0, "is_24h": True, "damage_status": "normal"},
    ]

    cargos = [
        {"cargo_id": "C-AL01", "order_no": "PO-AL01", "cargo_type": "supplies", "description": "应急救灾物资", "weight_tons": 6, "volume_m3": 25, "value_yuan": 35000, "priority_level": "P1", "requires_cold_chain": False, "is_hazardous": False, "origin_node": "NODE-AL00", "origin_name": "预警中心仓", "destination_node": "NODE-AL01", "destination_name": "东部安置点", "destination_lat": nodes[1]["lat"], "destination_lng": nodes[1]["lng"], "assigned_vehicle_id": "", "current_status": "pending", "current_location_node": "NODE-AL00", "planned_route": ["NODE-AL00", "NODE-AL01"], "current_route_index": 0, "departure_time": "", "deadline": "", "contract_penalty_per_hour": 500, "customer_id": "CUST-AL01", "customer_name": "东部安置点", "customer_type": "enterprise"},
        {"cargo_id": "C-AL02", "order_no": "PO-AL02", "cargo_type": "medical", "description": "医疗急救药品", "weight_tons": 2, "volume_m3": 8, "value_yuan": 55000, "priority_level": "P1", "requires_cold_chain": False, "is_hazardous": False, "origin_node": "NODE-AL00", "origin_name": "预警中心仓", "destination_node": "NODE-AL02", "destination_name": "南部医院", "destination_lat": nodes[2]["lat"], "destination_lng": nodes[2]["lng"], "assigned_vehicle_id": "", "current_status": "pending", "current_location_node": "NODE-AL00", "planned_route": ["NODE-AL00", "NODE-AL02"], "current_route_index": 0, "departure_time": "", "deadline": "", "contract_penalty_per_hour": 800, "customer_id": "CUST-AL02", "customer_name": "南部医院", "customer_type": "enterprise"},
        {"cargo_id": "C-AL03", "order_no": "PO-AL03", "cargo_type": "normal", "description": "建材设备", "weight_tons": 8, "volume_m3": 30, "value_yuan": 20000, "priority_level": "P3", "requires_cold_chain": False, "is_hazardous": False, "origin_node": "NODE-AL03", "origin_name": "北部仓库", "destination_node": "NODE-AL01", "destination_name": "东部工地", "destination_lat": nodes[1]["lat"], "destination_lng": nodes[1]["lng"], "assigned_vehicle_id": "", "current_status": "pending", "current_location_node": "NODE-AL03", "planned_route": ["NODE-AL03", "NODE-AL01"], "current_route_index": 0, "departure_time": "", "deadline": "", "contract_penalty_per_hour": 300, "customer_id": "CUST-AL03", "customer_name": "东部工地", "customer_type": "enterprise"},
    ]

    scenario_id = f"RT-AL-{alert.get('alert_id', 'UNK').replace('SAMPLE-', '').replace('WC-', '')}"

    # 根据灾害类型生成对应的灾害数据
    disaster_field = {
        "disaster_id": f"DIS-AL-{alert.get('alert_id', 'UNK')}",
        "disaster_type": disaster_type,
        "center_lat": lat, "center_lng": lng,
        "influence_radius_km": radius,
        "affected_areas": [params.get("province", "")],
        "occurrence_time": params.get("publish_time", ""),
    }

    if disaster_type == "earthquake":
        disaster_field["earthquake"] = {
            "epicenter_city": params.get("province", ""), "epicenter_lat": lat, "epicenter_lng": lng,
            "magnitude": 6.5, "depth_km": 10, "intensity": 8, "occur_time": params.get("publish_time", ""),
            "influence_radius_km": radius, "affected_areas": [params.get("province", "")],
            "severity_level": "severe", "wave_arrival_times": [],
        }
    elif disaster_type == "rainstorm":
        disaster_field["rainstorm"] = {
            "center_city": params.get("province", ""), "center_lat": lat, "center_lng": lng,
            "rainfall_mm": 200 if alert_type in ("暴雨", "洪水") else 100,
            "affected_duration_hours": 24,
            "affected_areas": [params.get("province", "")],
            "waterlogged_roads": ["R-A04"], "river_water_level": [],
        }
    elif disaster_type == "typhoon":
        disaster_field["typhoon"] = {
            "typhoon_name": alert_type if alert_type == "台风" else "大风灾害",
            "center_lat": lat, "center_lng": lng,
            "wind_force_level": 12 if alert_type == "台风" else 8,
            "moving_speed_kmh": 25, "moving_direction": "NW", "landing_time": params.get("publish_time", ""),
            "landing_location": params.get("province", ""), "influence_radius_km": radius,
            "port_closure": True, "airport_closure": alert_type == "台风",
            "affected_areas": [params.get("province", "")],
        }
    elif disaster_type == "landslide":
        disaster_field["landslide"] = {
            "location_city": params.get("province", ""), "location_lat": lat, "location_lng": lng,
            "scale_level": 3, "blocked_roads": ["R-A04"],
            "estimated_clear_hours": 48,
            "affected_areas": [params.get("province", "")],
        }
    elif disaster_type == "snowstorm":
        disaster_field["snowstorm"] = {
            "center_city": params.get("province", ""), "center_lat": lat, "center_lng": lng,
            "snowfall_cm": 30, "temperature_min": -15,
            "affected_duration_hours": 48,
            "affected_areas": [params.get("province", "")],
        }
    elif disaster_type == "sandstorm":
        disaster_field["sandstorm"] = {
            "center_city": params.get("province", ""), "center_lat": lat, "center_lng": lng,
            "wind_force_level": 9, "visibility_m": 500,
            "affected_duration_hours": 12,
            "affected_areas": [params.get("province", "")],
        }
    elif disaster_type == "wildfire":
        disaster_field["wildfire"] = {
            "center_city": params.get("province", ""), "center_lat": lat, "center_lng": lng,
            "fire_level": 3, "burned_area_ha": 500,
            "affected_areas": [params.get("province", "")],
        }
    elif disaster_type == "tsunami":
        disaster_field["tsunami"] = {
            "center_city": params.get("province", ""), "center_lat": lat, "center_lng": lng,
            "wave_height_m": 5, "warning_level": "red",
            "affected_areas": [params.get("province", "")],
        }
    else:
        disaster_field["rainstorm"] = {
            "center_city": params.get("province", ""), "center_lat": lat, "center_lng": lng,
            "rainfall_mm": 100, "affected_duration_hours": 24,
            "affected_areas": [params.get("province", "")], "waterlogged_roads": ["R-A04"], "river_water_level": [],
        }

    return {
        "scenario_id": scenario_id,
        "scenario_name": f"真实预警场景 - {alert_type}{params.get('level', '')}预警",
        "scenario_description": f"基于国家气象预警信息。预警标题: {title}。{params.get('severity', '')}",
        "disaster": disaster_field,
        "logistics_network": {"nodes": nodes, "roads": roads},
        "vehicle_fleet": vehicles, "warehouses": warehouses, "cargo_manifest": cargos,
        "evaluation": {
            "config_id": "EVAL-RT-AL", "scenario_id": scenario_id,
            "benchmark_cost": 6000, "benchmark_delivery_time_hours": 48,
            "weights": {"timeliness": 0.30, "economic": 0.25, "feasibility": 0.25, "compliance": 0.20},
            "bonus_rules": [{"rule": "first_submit_bonus", "score": 5}],
            "penalty_rules": [{"rule": "timeout_penalty", "score": -10}],
            "max_delay_hours": 48,
        },
        "strategy_config": {"mode": "time_pressure"},
        "realtime_source": {"alert_id": alert.get("alert_id", ""), "source": "国家气象预警信息"},
        "created_at": datetime.now().isoformat(timespec="minutes"),
    }


# ============================================================
# 全省物流信息查询 API
# ============================================================

# 西南地区主要物流节点（云南/四川/贵州/重庆）
PROVINCE_LOGISTICS = {
    "roads": [
        {"road_id": "G5", "road_name": "京昆高速", "from_city": "成都", "to_city": "昆明", "distance_km": 1100, "type": "高速公路", "status": "畅通", "lat1": 30.67, "lng1": 104.07, "lat2": 25.04, "lng2": 102.71},
        {"road_id": "G42", "road_name": "沪蓉高速", "from_city": "成都", "to_city": "重庆", "distance_km": 320, "type": "高速公路", "status": "畅通", "lat1": 30.67, "lng1": 104.07, "lat2": 29.56, "lng2": 106.55},
        {"road_id": "G76", "road_name": "厦蓉高速", "from_city": "成都", "to_city": "贵阳", "distance_km": 780, "type": "高速公路", "status": "畅通", "lat1": 30.67, "lng1": 104.07, "lat2": 26.65, "lng2": 106.71},
        {"road_id": "G85", "road_name": "银昆高速", "from_city": "昆明", "to_city": "重庆", "distance_km": 950, "type": "高速公路", "status": "畅通", "lat1": 25.04, "lng1": 102.71, "lat2": 29.56, "lng2": 106.55},
        {"road_id": "G56", "road_name": "杭瑞高速", "from_city": "昆明", "to_city": "贵阳", "distance_km": 630, "type": "高速公路", "status": "畅通", "lat1": 25.04, "lng1": 102.71, "lat2": 26.65, "lng2": 106.71},
        {"road_id": "G60", "road_name": "沪昆高速", "from_city": "贵阳", "to_city": "昆明", "distance_km": 630, "type": "高速公路", "status": "畅通", "lat1": 26.65, "lng1": 106.71, "lat2": 25.04, "lng2": 102.71},
        {"road_id": "G4213", "road_name": "成巴高速", "from_city": "成都", "to_city": "巴中", "distance_km": 350, "type": "高速公路", "status": "畅通", "lat1": 30.67, "lng1": 104.07, "lat2": 31.87, "lng2": 106.75},
        {"road_id": "S1", "road_name": "成渝高速", "from_city": "成都", "to_city": "重庆", "distance_km": 340, "type": "高速公路", "status": "畅通", "lat1": 30.67, "lng1": 104.07, "lat2": 29.56, "lng2": 106.55},
        {"road_id": "G5S", "road_name": "昆磨高速", "from_city": "昆明", "to_city": "西双版纳", "distance_km": 550, "type": "高速公路", "status": "畅通", "lat1": 25.04, "lng1": 102.71, "lat2": 22.00, "lng2": 100.80},
        {"road_id": "G7", "road_name": "兰海高速", "from_city": "重庆", "to_city": "贵阳", "distance_km": 380, "type": "高速公路", "status": "畅通", "lat1": 29.56, "lng1": 106.55, "lat2": 26.65, "lng2": 106.71},
    ],
    "warehouses": [
        {"warehouse_id": "WH-CD01", "name": "成都龙泉物流园", "city": "成都", "lat": 30.55, "lng": 104.15, "capacity_m3": 50000, "type": "综合仓", "status": "运营中"},
        {"warehouse_id": "WH-CD02", "name": "成都双流航空物流", "city": "成都", "lat": 30.58, "lng": 103.95, "capacity_m3": 30000, "type": "航空仓", "status": "运营中"},
        {"warehouse_id": "WH-KM01", "name": "昆明呈贡物流园", "city": "昆明", "lat": 24.89, "lng": 102.80, "capacity_m3": 40000, "type": "综合仓", "status": "运营中"},
        {"warehouse_id": "WH-KM02", "name": "昆明空港物流", "city": "昆明", "lat": 25.00, "lng": 102.93, "capacity_m3": 25000, "type": "航空仓", "status": "运营中"},
        {"warehouse_id": "WH-CQ01", "name": "重庆果园港物流", "city": "重庆", "lat": 29.65, "lng": 106.60, "capacity_m3": 60000, "type": "港口仓", "status": "运营中"},
        {"warehouse_id": "WH-CQ02", "name": "重庆空港物流", "city": "重庆", "lat": 29.72, "lng": 106.64, "capacity_m3": 35000, "type": "航空仓", "status": "运营中"},
        {"warehouse_id": "WH-GY01", "name": "贵阳龙洞堡物流", "city": "贵阳", "lat": 26.58, "lng": 106.80, "capacity_m3": 30000, "type": "航空仓", "status": "运营中"},
        {"warehouse_id": "WH-GY02", "name": "贵阳改貌物流园", "city": "贵阳", "lat": 26.50, "lng": 106.73, "capacity_m3": 35000, "type": "综合仓", "status": "运营中"},
        {"warehouse_id": "WH-PX01", "name": "攀枝花物流园", "city": "攀枝花", "lat": 26.58, "lng": 101.72, "capacity_m3": 15000, "type": "综合仓", "status": "运营中"},
        {"warehouse_id": "WH-XY01", "name": "西昌物流中转", "city": "西昌", "lat": 27.90, "lng": 102.27, "capacity_m3": 12000, "type": "综合仓", "status": "运营中"},
    ],
    "cities": [
        {"city": "成都", "lat": 30.67, "lng": 104.07, "type": "省会", "is_hub": True},
        {"city": "昆明", "lat": 25.04, "lng": 102.71, "type": "省会", "is_hub": True},
        {"city": "重庆", "lat": 29.56, "lng": 106.55, "type": "直辖市", "is_hub": True},
        {"city": "贵阳", "lat": 26.65, "lng": 106.71, "type": "省会", "is_hub": True},
        {"city": "西昌", "lat": 27.90, "lng": 102.27, "type": "地级市", "is_hub": False},
        {"city": "攀枝花", "lat": 26.58, "lng": 101.72, "type": "地级市", "is_hub": False},
        {"city": "大理", "lat": 25.61, "lng": 100.23, "type": "地级市", "is_hub": False},
        {"city": "丽江", "lat": 26.87, "lng": 100.23, "type": "地级市", "is_hub": False},
        {"city": "曲靖", "lat": 25.49, "lng": 103.80, "type": "地级市", "is_hub": False},
        {"city": "绵阳", "lat": 31.47, "lng": 104.68, "type": "地级市", "is_hub": False},
        {"city": "宜宾", "lat": 28.77, "lng": 104.62, "type": "地级市", "is_hub": False},
        {"city": "泸州", "lat": 28.87, "lng": 105.44, "type": "地级市", "is_hub": False},
    ],
}


@app.route("/api/logistics/query", methods=["GET"])
def logistics_query():
    """获取全省物流信息（道路、仓库、城市）"""
    return jsonify(PROVINCE_LOGISTICS)


# ============================================================
# 虚拟企业数据大屏 API
# ============================================================

# 虚拟第三方物流企业
COMPANY_INFO = {
    "company_name": "安迅达物流集团",
    "short_name": "安迅达",
    "english_name": "Anxunda Emergency Logistics Group",
    "logo": "🚛",
    "founded": "2015",
    "headquarters": "成都",
    "description": "西南地区领先的第三方综合物流服务商。2019年与四川省应急管理厅签订战略合作协议，正式纳入【应急运力备选库】，承接政府采购救灾物资运输任务。专注应急物流、冷链物流、干线运输与仓储配送，在地震、泥石流等灾害场景下具备快速响应能力。",
    "fleet_size": 186,
    "warehouse_count": 12,
    "drone_count": 24,
    "drone_models": [
        {"model": "大疆FlyCart 30", "count": 12, "payload_kg": 30, "range_km": 28, "use": "末端救灾物资空投"},
        {"model": "丰翼方舟M5", "count": 8, "payload_kg": 50, "range_km": 20, "use": "道路中断时跨区域投送"},
        {"model": "自研XDA-100", "count": 4, "payload_kg": 100, "range_km": 50, "use": "重型救灾设备运输"},
    ],
    "service_cities": 48,
    "employees": 1200,
    "business_scope": ["干线运输", "城配配送", "冷链物流", "仓储管理", "应急物流", "跨境物流", "无人机空投"],
    "emergency_role": {
        "title": "应急运力备选库签约企业",
        "contract_level": "省级应急运力备选库（一级响应）",
        "contract_signing": "2019年与四川省应急管理厅签订",
        "responsibilities": [
            "承接政府采购救灾物资运输",
            "灾害期间24小时内调配车辆/无人机到达指定区域",
            "协助应急管理部门进行物资中转与分发",
            "提供应急仓储与临时中转服务",
        ],
        "activation_count": 17,
        "latest_activation": "2025年8月 参与四川某地泥石流救灾物资运输",
    },
    "certifications": [
        "ISO9001质量认证",
        "A级物流企业",
        "冷链物流资质",
        "危险品运输许可",
        "应急管理部应急运力备选库资质",
        "无人机运营合格证",
    ],
    "annual_revenue": "8.6亿",
    "coverage": ["四川", "云南", "贵州", "重庆", "西藏"],
}

# 动态订单生成（每次请求基于当前时间生成不同状态）
import random as _random


@app.route("/api/company/info", methods=["GET"])
def company_info():
    """获取企业信息"""
    return jsonify(COMPANY_INFO)


@app.route("/api/company/orders", methods=["GET"])
def company_orders():
    """获取企业当前动态订单列表（含普通订单+救灾物资订单）"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute

    # 基于当前时间生成动态状态
    orders = []

    # 普通物资订单
    normal_routes = [
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-001", "from": "成都龙泉仓", "to": "昆明呈贡仓", "from_lat": 30.55, "from_lng": 104.15, "to_lat": 24.89, "to_lng": 102.80, "cargo": "电子配件 12吨", "vehicle": "川A·L8865", "distance": 1100, "revenue": 8800, "order_type": "normal"},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-002", "from": "重庆果园港", "to": "贵阳龙洞堡", "from_lat": 29.65, "from_lng": 106.60, "to_lat": 26.58, "to_lng": 106.80, "cargo": "建材物资 25吨", "vehicle": "渝B·K3321", "distance": 380, "revenue": 4500, "order_type": "normal"},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-003", "from": "昆明空港", "to": "西昌中转", "from_lat": 25.00, "from_lng": 102.93, "to_lat": 27.90, "to_lng": 102.27, "cargo": "鲜花冷链 8吨", "vehicle": "云A·X7788", "distance": 350, "revenue": 6200, "order_type": "normal"},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-004", "from": "成都双流", "to": "攀枝花", "from_lat": 30.58, "from_lng": 103.95, "to_lat": 26.58, "to_lng": 101.72, "cargo": "医疗器械 3吨", "vehicle": "川A·M5566", "distance": 550, "revenue": 7500, "order_type": "normal"},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-005", "from": "贵阳改貌", "to": "重庆空港", "from_lat": 26.50, "from_lng": 106.73, "to_lat": 29.72, "to_lng": 106.64, "cargo": "食品饮料 15吨", "vehicle": "贵A·F9988", "distance": 380, "revenue": 3800, "order_type": "normal"},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-006", "from": "成都龙泉仓", "to": "大理", "from_lat": 30.55, "from_lng": 104.15, "to_lat": 25.61, "to_lng": 100.23, "cargo": "日用百货 18吨", "vehicle": "川A·L2233", "distance": 850, "revenue": 6800, "order_type": "normal"},
    ]

    # 救灾物资订单（政府采购/应急管理部门调拨）
    emergency_routes = [
        {"order_no": f"EMR-{now.strftime('%Y%m%d')}-001", "from": "成都应急仓", "to": "甘孜灾区", "from_lat": 30.55, "from_lng": 104.15, "to_lat": 30.05, "to_lng": 101.96, "cargo": "救灾帐篷 200顶", "vehicle": "川A·EM01", "distance": 420, "revenue": 0, "order_type": "emergency", "dispatch_source": "省应急管理厅调拨", "priority": "P1-紧急"},
        {"order_no": f"EMR-{now.strftime('%Y%m%d')}-002", "from": "成都应急仓", "to": "阿坝灾区", "from_lat": 30.55, "from_lng": 104.15, "to_lat": 31.91, "to_lng": 102.22, "cargo": "饮用水5吨+食品3吨", "vehicle": "川A·EM02", "distance": 350, "revenue": 0, "order_type": "emergency", "dispatch_source": "省应急管理厅调拨", "priority": "P1-紧急"},
        {"order_no": f"EMR-{now.strftime('%Y%m%d')}-003", "from": "昆明应急仓", "to": "昭通灾区", "from_lat": 25.04, "from_lng": 102.71, "to_lat": 27.34, "to_lng": 103.72, "cargo": "棉被500床+折叠床100张", "vehicle": "无人机编队XDA-100×2", "distance": 280, "revenue": 0, "order_type": "emergency", "dispatch_source": "云南省应急厅调拨", "priority": "P1-紧急", "is_drone": True},
        {"order_no": f"EMR-{now.strftime('%Y%m%d')}-004", "from": "重庆应急仓", "to": "黔江灾区", "from_lat": 29.65, "from_lng": 106.60, "to_lat": 29.53, "to_lng": 108.77, "cargo": "发电机组2台+燃油1吨", "vehicle": "渝B·EM03", "distance": 260, "revenue": 0, "order_type": "emergency", "dispatch_source": "重庆市应急局调拨", "priority": "P2-加急"},
    ]

    all_routes = normal_routes + emergency_routes

    for i, o in enumerate(all_routes):
        # 动态进度：基于当前分钟数模拟
        progress = ((hour * 60 + minute + i * 17) % 100) / 100
        if progress > 0.95:
            status = "已送达"
        elif progress < 0.1:
            status = "已装车"
        elif progress < 0.25:
            status = "已发车"
        else:
            status = "运输中"

        # 计算当前坐标（线性插值）
        cur_lat = o["from_lat"] + (o["to_lat"] - o["from_lat"]) * progress
        cur_lng = o["from_lng"] + (o["to_lng"] - o["from_lng"]) * progress

        order_data = {
            **o,
            "status": status,
            "progress": round(progress * 100, 1),
            "current_lat": round(cur_lat, 4),
            "current_lng": round(cur_lng, 4),
            "eta_hours": round((1 - progress) * (o["distance"] / 70), 1),
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 救灾订单增加安全考核分
        if o.get("order_type") == "emergency":
            order_data["safety_score"] = 92 + (i % 8)
            order_data["speed_score"] = 88 + (i % 7)
            order_data["is_drone"] = o.get("is_drone", False)

        orders.append(order_data)

    total_revenue = sum(o["revenue"] for o in orders)
    active = sum(1 for o in orders if o["status"] == "运输中")
    delivered = sum(1 for o in orders if o["status"] == "已送达")

    # 分类统计
    normal_orders = [o for o in orders if o.get("order_type") == "normal"]
    emergency_orders = [o for o in orders if o.get("order_type") == "emergency"]

    return jsonify({
        "orders": orders,
        "stats": {
            "total_orders": len(orders),
            "active_orders": active,
            "delivered_orders": delivered,
            "total_revenue": total_revenue,
            "normal_orders": len(normal_orders),
            "emergency_orders": len(emergency_orders),
            "emergency_active": sum(1 for o in emergency_orders if o["status"] == "运输中"),
        },
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    })


# ============================================================
# 救灾物资运送考核 API
# ============================================================

@app.route("/api/emergency-relief/assess", methods=["POST"])
def emergency_relief_assess():
    """救灾决策模式评分 - 考核安全与速度双维度"""
    data = request.get_json()
    actions = data.get("actions", [])
    submit_time = data.get("submit_time_sec", 0)
    optimal_plan_data = data.get("optimal_plan", {})
    scenario_data = data.get("scenario_data")
    
    if not scenario_data:
        for f in SCENARIOS_DIR.glob("*.json"):
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("scenario_id") == data.get("scenario_id") or f.stem == data.get("scenario_id"):
                scenario_data = d
                break
    
    if not scenario_data:
        return jsonify({"error": "场景数据缺失"}), 400
    
    try:
        scenario = load_scenario_from_dict(scenario_data)
        optimal_plan = engine.solve(scenario)
        
        from emergency_decision.strategy_adaptations import EmergencyReliefAssessor
        assessor = EmergencyReliefAssessor()
        assessment = assessor.assess(
            student_actions=actions,
            optimal_plan=optimal_plan,
            scenario=scenario,
            submit_time_sec=submit_time,
        )
        
        return jsonify({
            "assessment": assessment.to_dict(),
            "optimal_plan": optimal_plan.to_dict(),
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/emergency/assessment", methods=["GET"])
def emergency_assessment():
    """救灾物资运送模式考核（安全+速度因素）"""
    now = datetime.now()

    # 考核维度定义
    dimensions = {
        "safety": {
            "name": "安全维度",
            "weight": 0.5,
            "factors": [
                {"id": "route_safety", "name": "路线安全评估", "desc": "路线地质灾害风险、道路状况评估", "max_score": 25},
                {"id": "cargo_secure", "name": "货物固定与防护", "desc": "救灾物资装卸、固定、防潮防震措施", "max_score": 25},
                {"id": "vehicle_condition", "name": "车辆/无人机状态", "desc": "运输工具安全检查、应急装备配备", "max_score": 25},
                {"id": "driver_training", "name": "驾驶员/操作员资质", "desc": "应急运输培训记录、持证情况", "max_score": 25},
            ],
        },
        "speed": {
            "name": "速度维度",
            "weight": 0.5,
            "factors": [
                {"id": "response_time", "name": "响应时效", "desc": "从接令到出库装车的时间", "max_score": 25},
                {"id": "route_optimization", "name": "路线优化", "desc": "最短/最安全路径规划能力", "max_score": 25},
                {"id": "transfer_efficiency", "name": "中转效率", "desc": "中转站货物分拨效率", "max_score": 25},
                {"id": "delivery_speed", "name": "末端送达速度", "desc": "最后一段配送时效", "max_score": 25},
            ],
        },
    }

    # 模拟历史考核记录
    history = []
    for i in range(5, 0, -1):
        dt = now - timedelta(days=i * 7)
        safety_score = 82 + (i * 3) % 15
        speed_score = 78 + (i * 5) % 20
        total = round(safety_score * 0.5 + speed_score * 0.5, 1)
        history.append({
            "date": dt.strftime("%Y-%m-%d"),
            "scenario": f"救灾物资运输考核 #{6-i}",
            "safety_score": safety_score,
            "speed_score": speed_score,
            "total_score": total,
            "grade": "A" if total >= 85 else "B" if total >= 70 else "C",
            "issues": [] if total >= 85 else ["路线选择需优化", "中转效率待提升"],
        })

    # 当前考核标准
    standards = {
        "excellent": {"min_score": 90, "desc": "卓越 - 可优先承接P1级救灾运输任务"},
        "good": {"min_score": 80, "desc": "优秀 - 可承接常规救灾运输任务"},
        "qualified": {"min_score": 70, "desc": "合格 - 需在督导下执行救灾运输"},
        "unqualified": {"min_score": 0, "desc": "不合格 - 暂停救灾运输资质"},
    }

    # 最新综合评分
    latest = history[0] if history else {"safety_score": 0, "speed_score": 0, "total_score": 0}
    grade = "A" if latest["total_score"] >= 90 else "B" if latest["total_score"] >= 80 else "C" if latest["total_score"] >= 70 else "D"

    return jsonify({
        "dimensions": dimensions,
        "latest_score": {
            "safety_score": latest["safety_score"],
            "speed_score": latest["speed_score"],
            "total_score": latest["total_score"],
            "grade": grade,
            "assessment_date": now.strftime("%Y-%m-%d"),
            "assessor": "省应急管理厅应急运输考核组",
        },
        "history": history,
        "standards": standards,
        "recommendation": "建议继续加强路线安全评估和中转效率提升" if latest["total_score"] < 90 else "继续保持优秀表现，可优先承接紧急任务",
    })


# ============================================================
# 应急管理部信息查阅推送模块 API
# ============================================================

# 应急管理部信息分类与内容
MEM_INFO_DATA = {
    "categories": [
        {"id": "notices", "name": "通知公告", "icon": "📢", "desc": "应急管理部最新通知与公告"},
        {"id": "policies", "name": "政策法规", "icon": "📋", "desc": "应急管理与防灾减灾政策法规"},
        {"id": "news", "name": "应急要闻", "icon": "📰", "desc": "全国应急救援工作动态"},
        {"id": "warnings", "name": "预警信息", "icon": "🚨", "desc": "自然灾害预警信息发布"},
        {"id": "earthquake", "name": "地震速报", "icon": "🌏", "desc": "中国地震台网正式速报"},
        {"id": "prevention", "name": "防灾减灾", "icon": "🛡️", "desc": "防灾减灾知识与科普教育"},
    ],
    "items": [
        {
            "id": "MEM-001", "category": "notices", "title": "关于做好2026年主汛期应急运输保障工作的通知",
            "source": "应急管理部", "date": "2026-07-15", "url": "https://www.mem.gov.cn/",
            "summary": "要求各级应急管理部门做好主汛期应急运输保障工作，确保救灾物资及时到位。重点强化应急运力备选库管理，完善政企协同机制。",
            "tags": ["应急运输", "主汛期", "救灾物资"],
        },
        {
            "id": "MEM-002", "category": "policies", "title": "《应急运力备选库管理办法（2026年修订）》",
            "source": "应急管理部", "date": "2026-06-20", "url": "https://www.mem.gov.cn/",
            "summary": "修订后的管理办法进一步明确了应急运力备选库企业的准入条件、考核标准、退出机制。新增无人机运输企业纳入备选库条款。",
            "tags": ["政策法规", "应急运力备选库", "无人机"],
        },
        {
            "id": "MEM-003", "category": "news", "title": "四川某地泥石流灾害应急运输救援纪实",
            "source": "应急管理部", "date": "2026-07-08", "url": "https://www.mem.gov.cn/",
            "summary": "7月8日四川某地发生泥石流灾害，应急管理部立即启动应急响应，调拨救灾帐篷200顶、棉被500床，组织应急运力备选库企业参与运输。",
            "tags": ["应急救援", "泥石流", "四川"],
        },
        {
            "id": "MEM-004", "category": "warnings", "title": "全国自然灾害综合风险预警（7月第3周）",
            "source": "应急管理部", "date": "2026-07-18", "url": "https://www.mem.gov.cn/",
            "summary": "本周西南地区地质灾害风险较高，部分地区暴雨洪涝风险增加。建议应急运力备选库企业做好24小时待命准备。",
            "tags": ["预警", "地质灾害", "西南地区"],
        },
        {
            "id": "MEM-005", "category": "earthquake", "title": "云南某地3.2级地震速报",
            "source": "中国地震台网", "date": "2026-07-19", "url": "https://www.mem.gov.cn/",
            "summary": "据中国地震台网正式测定：7月19日云南某地发生3.2级地震，震源深度10千米，暂无人员伤亡报告。",
            "tags": ["地震", "云南"],
        },
        {
            "id": "MEM-006", "category": "prevention", "title": "汛期防灾减灾科普：泥石流自救指南",
            "source": "应急管理部", "date": "2026-07-10", "url": "https://www.mem.gov.cn/",
            "summary": "科普视频与图文教程：泥石流发生时的正确自救方法、应急物资储备清单、社区疏散路线规划。",
            "tags": ["科普", "泥石流", "自救"],
        },
        {
            "id": "MEM-007", "category": "notices", "title": "关于开展2026年度应急运输企业考核工作的通知",
            "source": "应急管理部", "date": "2026-07-01", "url": "https://www.mem.gov.cn/",
            "summary": "启动年度应急运力备选库企业考核，重点考核安全维度和速度维度。考核结果将影响企业下一年度应急任务承接优先级。",
            "tags": ["考核", "应急运力备选库"],
        },
        {
            "id": "MEM-008", "category": "policies", "title": "《无人机应急运输操作规范（试行）》",
            "source": "应急管理部", "date": "2026-05-15", "url": "https://www.mem.gov.cn/",
            "summary": "首次发布无人机参与救灾物资运输的操作规范，涵盖飞行许可、载重标准、空投安全距离、应急返航等关键要求。",
            "tags": ["无人机", "操作规范", "救灾运输"],
        },
        {
            "id": "MEM-009", "category": "news", "title": "全国应急管理系统表彰先进集体和个人",
            "source": "应急管理部", "date": "2026-06-30", "url": "https://www.mem.gov.cn/",
            "summary": "表彰在应急救援工作中表现突出的集体和个人，其中包括多家应急运力备选库签约企业。",
            "tags": ["表彰", "先进集体"],
        },
        {
            "id": "MEM-010", "category": "prevention", "title": "企业参与应急运输的安全须知与培训资源",
            "source": "应急管理部", "date": "2026-06-25", "url": "https://www.mem.gov.cn/",
            "summary": "面向应急运力备选库企业的安全培训资源汇总，包含线上课程、考核题库、实操演练指南。",
            "tags": ["培训", "安全", "应急运输"],
        },
    ],
}


@app.route("/api/mem/categories", methods=["GET"])
def mem_categories():
    """获取应急管理部信息分类"""
    return jsonify({"categories": MEM_INFO_DATA["categories"]})


@app.route("/api/mem/news", methods=["GET"])
def mem_news():
    """获取应急管理部信息列表，支持分类筛选"""
    category = request.args.get("category", "")
    items = MEM_INFO_DATA["items"]
    if category:
        items = [item for item in items if item["category"] == category]
    return jsonify({
        "items": items,
        "total": len(items),
        "source": "中华人民共和国应急管理部",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/mem/push", methods=["GET"])
def mem_push():
    """获取最新的应急管理部推送信息"""
    now = datetime.now()
    # 取最近3条作为推送
    recent = MEM_INFO_DATA["items"][:3]
    return jsonify({
        "push_count": len(recent),
        "push_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "items": recent,
        "message": f"您有{len(recent)}条应急管理部最新信息待查阅",
    })


@app.route("/mem")
def mem_page():
    """应急管理部信息查阅页面"""
    ok, redirect_url = _check_auth("/mem")
    if not ok:
        return redirect(redirect_url)
    return render_template("mem_info.html", active_page="mem")

def _extract_map_data(scenario) -> dict:
    """提取地图展示数据 (节点、路段、灾害中心)"""
    nodes = []
    for n in scenario.logistics_network.nodes:
        nodes.append({
            "node_id": n.node_id,
            "node_name": n.node_name,
            "node_type": n.node_type.value if hasattr(n.node_type, 'value') else str(n.node_type),
            "city": n.city,
            "lat": n.lat,
            "lng": n.lng,
        })
    
    roads = []
    for r in scenario.logistics_network.roads:
        from_node = scenario.logistics_network.get_node(r.from_node)
        to_node = scenario.logistics_network.get_node(r.to_node)
        roads.append({
            "road_id": r.road_id,
            "road_name": r.road_name,
            "from_lat": from_node.lat if from_node else 0,
            "from_lng": from_node.lng if from_node else 0,
            "to_lat": to_node.lat if to_node else 0,
            "to_lng": to_node.lng if to_node else 0,
            "has_bridge": r.has_bridge,
            "has_tunnel": r.has_tunnel,
        })
    
    vehicles = []
    for v in scenario.vehicle_fleet:
        vehicles.append({
            "vehicle_id": v.vehicle_id,
            "license_plate": v.license_plate,
            "vehicle_type": v.vehicle_type.value,
            "lat": v.current_lat,
            "lng": v.current_lng,
            "status": v.status.value,
            "current_cargo": len(v.current_cargo_ids),
        })
    
    warehouses = []
    for w in scenario.warehouses:
        warehouses.append({
            "warehouse_id": w.warehouse_id,
            "warehouse_name": w.warehouse_name,
            "city": w.city,
            "lat": w.lat,
            "lng": w.lng,
            "damage_status": w.damage_status.value,
        })
    
    disaster = {
        "type": scenario.disaster.disaster_type.value,
        "center_lat": scenario.disaster.center_lat,
        "center_lng": scenario.disaster.center_lng,
        "influence_radius_km": scenario.disaster.influence_radius_km,
        "affected_areas": scenario.disaster.affected_areas,
    }
    
    if scenario.disaster.earthquake:
        disaster["magnitude"] = scenario.disaster.earthquake.magnitude
        disaster["epicenter_city"] = scenario.disaster.earthquake.epicenter_city
    if scenario.disaster.rainstorm:
        disaster["rainfall_mm"] = scenario.disaster.rainstorm.rainfall_mm
    if scenario.disaster.typhoon:
        disaster["wind_force"] = scenario.disaster.typhoon.wind_force_level
        disaster["typhoon_name"] = scenario.disaster.typhoon.typhoon_name
    
    return {
        "nodes": nodes,
        "roads": roads,
        "vehicles": vehicles,
        "warehouses": warehouses,
        "disaster": disaster,
    }


# ============================================================
# 系统管理 API
# ============================================================

@app.route("/api/system/clear", methods=["POST"])
def api_system_clear():
    """清空所有账号的所有历史操作（保留班级与学生名单）"""
    global _runtime_store
    try:
        # 备份班级配置（班级和学生名单是基础设施，不应被清理）
        classes_backup = _runtime_store.get("classes", {})
        # 清空班级内的动态分组（新一轮教学需重新分组）
        for cid in classes_backup:
            classes_backup[cid]["groups"] = []

        _runtime_store = {
            "sessions": {},
            "results": {},
            "profiles": {},
            "behavior_events": {},
            "group_tasks": {},
            "progress": {},
            "classes": classes_backup,
            "tasks": {},
        }
        # 删除持久化文件
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        save_state()
        return jsonify({"status": "ok", "message": "所有操作数据已清空，班级配置已保留"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# 启动
# ============================================================

def run_server(host=None, port=None, debug=None):
    """启动Flask服务器 - 支持环境变量配置"""
    host = host or os.environ.get("HOST", "0.0.0.0")
    port = int(port or os.environ.get("PORT", 5000))
    debug = debug if debug is not None else os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"应急决策教学系统 - 服务器启动")
    print(f"地址: http://{host}:{port}")
    print(f"场景目录: {SCENARIOS_DIR}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_server()
