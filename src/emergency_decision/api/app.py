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
from datetime import datetime
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

# ============================================================
# 虚拟账号系统
# ============================================================

VIRTUAL_USERS = {
    # 教师账号
    "teacher01": {"password": "teach123", "role": "teacher", "name": "王老师", "avatar": "👨‍🏫"},
    "teacher02": {"password": "teach456", "role": "teacher", "name": "李老师", "avatar": "👩‍🏫"},
    # 学生账号
    "student01": {"password": "stud123", "role": "student", "name": "张同学", "avatar": "👨‍🎓"},
    "student02": {"password": "stud456", "role": "student", "name": "刘同学", "avatar": "👩‍🎓"},
    "student03": {"password": "stud789", "role": "student", "name": "陈同学", "avatar": "🧑‍🎓"},
}

# 各角色可访问的页面
ROLE_PAGES = {
    "teacher": ["/", "/editor", "/decision", "/profile", "/dashboard", "/disaster-query", "/logistics", "/company"],
    "student": ["/", "/decision", "/profile", "/disaster-query", "/company"],
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

# 存储运行时数据 (实际项目中应使用数据库)
_runtime_store = {
    "sessions": {},        # session_id -> {student_id, scenario_id, ...}
    "results": {},         # session_id -> engine result
    "profiles": {},        # student_id -> [profile dicts]
    "behavior_events": {}, # session_id -> [events]
}


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

    # 根据角色跳转不同首页
    redirect_url = "/dashboard" if user["role"] == "teacher" else "/decision"
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
    # 已登录用户跳转到角色默认页
    user = session.get("user", {})
    if user.get("role") == "teacher":
        return redirect("/dashboard")
    return redirect("/decision")

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
        
        _runtime_store["results"][session_id] = result
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
    vehicles = []
    for i in range(4):
        n = nodes[i % len(nodes)]
        vehicles.append({
            "vehicle_id": f"V-EQ{i+1:02d}",
            "license_plate": f"川A{10000+i}",
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
    lat = params["latitude"] or 25.0
    lng = params["longitude"] or 130.0
    radius = params["influence_radius_km"]
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

    vehicles = []
    for i, n in enumerate(nodes):
        vehicles.append({
            "vehicle_id": f"V-TF{i+1:02d}", "license_plate": f"闽B{20000+i}", "vehicle_type": "box_truck",
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
    lat = params["latitude"] or 34.0
    lng = params["longitude"] or 113.0
    radius = params["influence_radius_km"]
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

    vehicles = []
    for i, n in enumerate(nodes):
        vehicles.append({
            "vehicle_id": f"V-AL{i+1:02d}", "license_plate": f"豫A{30000+i}", "vehicle_type": "box_truck",
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
    return {
        "scenario_id": scenario_id,
        "scenario_name": f"真实预警场景 - {alert_type}{params.get('level', '')}预警",
        "scenario_description": f"基于国家气象预警信息。预警标题: {title}。{params.get('severity', '')}",
        "disaster": {
            "disaster_id": f"DIS-AL-{alert.get('alert_id', 'UNK')}", "disaster_type": disaster_type,
            "center_lat": lat, "center_lng": lng, "influence_radius_km": radius,
            "affected_areas": [params.get("province", "")], "occurrence_time": params.get("publish_time", ""),
            "rainstorm": {"center_city": params.get("province", ""), "center_lat": lat, "center_lng": lng, "rainfall_mm": 200 if alert_type == "暴雨" else 0, "affected_duration_hours": 24, "affected_areas": [params.get("province", "")], "waterlogged_roads": ["R-A04"], "river_water_level": []} if disaster_type == "rainstorm" else None,
        },
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
    "english_name": "Anxunda Logistics Group",
    "logo": "🚚",
    "founded": "2015",
    "headquarters": "成都",
    "description": "西南地区领先的第三方综合物流服务商，专注应急物流、冷链物流、干线运输与仓储配送",
    "fleet_size": 186,
    "warehouse_count": 12,
    "service_cities": 48,
    "employees": 1200,
    "business_scope": ["干线运输", "城配配送", "冷链物流", "仓储管理", "应急物流", "跨境物流"],
    "certifications": ["ISO9001质量认证", "A级物流企业", "冷链物流资质", "危险品运输许可"],
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
    """获取企业当前动态订单列表"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute

    # 基于当前时间生成动态状态
    orders = []
    routes = [
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-001", "from": "成都龙泉仓", "to": "昆明呈贡仓", "from_lat": 30.55, "from_lng": 104.15, "to_lat": 24.89, "to_lng": 102.80, "cargo": "电子配件 12吨", "vehicle": "川A·L8865", "distance": 1100, "revenue": 8800},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-002", "from": "重庆果园港", "to": "贵阳龙洞堡", "from_lat": 29.65, "from_lng": 106.60, "to_lat": 26.58, "to_lng": 106.80, "cargo": "建材物资 25吨", "vehicle": "渝B·K3321", "distance": 380, "revenue": 4500},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-003", "from": "昆明空港", "to": "西昌中转", "from_lat": 25.00, "from_lng": 102.93, "to_lat": 27.90, "to_lng": 102.27, "cargo": "鲜花冷链 8吨", "vehicle": "云A·X7788", "distance": 350, "revenue": 6200},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-004", "from": "成都双流", "to": "攀枝花", "from_lat": 30.58, "from_lng": 103.95, "to_lat": 26.58, "to_lng": 101.72, "cargo": "医疗器械 3吨", "vehicle": "川A·M5566", "distance": 550, "revenue": 7500},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-005", "from": "贵阳改貌", "to": "重庆空港", "from_lat": 26.50, "from_lng": 106.73, "to_lat": 29.72, "to_lng": 106.64, "cargo": "食品饮料 15吨", "vehicle": "贵A·F9988", "distance": 380, "revenue": 3800},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-006", "from": "成都龙泉仓", "to": "大理", "from_lat": 30.55, "from_lng": 104.15, "to_lat": 25.61, "to_lng": 100.23, "cargo": "日用百货 18吨", "vehicle": "川A·L2233", "distance": 850, "revenue": 6800},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-007", "from": "昆明呈贡", "to": "曲靖", "from_lat": 24.89, "from_lng": 102.80, "to_lat": 25.49, "to_lng": 103.80, "cargo": "快递包裹 5吨", "vehicle": "云A·X1122", "distance": 130, "revenue": 1800},
        {"order_no": f"AXD-{now.strftime('%Y%m%d')}-008", "from": "重庆果园港", "to": "绵阳", "from_lat": 29.65, "from_lng": 106.60, "to_lat": 31.47, "to_lng": 104.68, "cargo": "机械设备 20吨", "vehicle": "渝B·K7766", "distance": 320, "revenue": 5200},
    ]

    statuses = ["运输中", "已发车", "运输中", "运输中", "已装车", "运输中", "已送达", "运输中"]
    progresses = []

    for i, o in enumerate(routes):
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

        orders.append({
            **o,
            "status": status,
            "progress": round(progress * 100, 1),
            "current_lat": round(cur_lat, 4),
            "current_lng": round(cur_lng, 4),
            "eta_hours": round((1 - progress) * (o["distance"] / 70), 1),
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        })

    total_revenue = sum(o["revenue"] for o in orders)
    active = sum(1 for o in orders if o["status"] == "运输中")
    delivered = sum(1 for o in orders if o["status"] == "已送达")

    return jsonify({
        "orders": orders,
        "stats": {
            "total_orders": len(orders),
            "active_orders": active,
            "delivered_orders": delivered,
            "total_revenue": total_revenue,
            "total_cargo_tons": sum(int(o["cargo"].split()[1].replace("吨", "")) for o in orders if "吨" in o["cargo"]),
        },
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    })


# ============================================================
# 辅助函数
# ============================================================

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
