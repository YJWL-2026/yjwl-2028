"""
行为埋点采集器 - 采集学生在决策推演中的五维行为数据
对应文档: 技术要求 "育"功能 3.2.1 数据采集层

五维原始数据:
  1. 响应速度 - 从收到预警到提交方案的时间间隔
  2. 风险偏好 - 高时效高风险路线 vs 低时效低风险路线的选择频次
  3. 资源利用 - 备用车辆/中转仓库调用率及冗余预留比例
  4. 信息关注 - 查看详细路况/天气预报/货物清单的点击次数与停留时长
  5. 方案变更 - 最终提交前修改或尝试备选方案的次数
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class BehaviorEvent:
    """单次行为事件"""
    event_type: str          # alert_received / view_road / view_weather / view_cargo / view_map / plan_modify / plan_submit / resource_allocate
    timestamp: float          # Unix时间戳
    detail: dict = field(default_factory=dict)
    # detail 可含: node_id, road_id, cargo_id, vehicle_id, warehouse_id, action_type, duration_sec, ...


@dataclass
class DecisionSession:
    """一次决策推演的完整行为记录"""
    session_id: str
    student_id: str
    scenario_id: str
    started_at: float
    events: list[BehaviorEvent] = field(default_factory=list)
    
    # 关键时间节点
    alert_received_at: float = 0.0
    first_plan_modify_at: float = 0.0
    submit_at: float = 0.0
    
    # 方案变更记录
    plan_versions: list[dict] = field(default_factory=list)  # 每次修改的快照
    
    # 最终提交的决策
    submitted_actions: list[dict] = field(default_factory=list)
    
    @property
    def response_time_sec(self) -> float:
        """从收到预警到提交的时间(秒)"""
        if self.alert_received_at > 0 and self.submit_at > 0:
            return self.submit_at - self.alert_received_at
        return 0.0
    
    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "scenario_id": self.scenario_id,
            "response_time_sec": round(self.response_time_sec, 1),
            "event_count": len(self.events),
            "plan_modify_count": len(self.plan_versions),
            "submitted_actions": self.submitted_actions,
        }


class BehaviorTracker:
    """
    行为埋点管理器
    - 记录学生在决策界面的所有操作
    - 聚合为五维原始指标
    - 为素养画像生成器提供输入
    """

    def __init__(self):
        self._sessions: dict[str, DecisionSession] = {}

    def start_session(self, session_id: str, student_id: str, 
                      scenario_id: str) -> DecisionSession:
        """开始一次决策会话"""
        now = datetime.now().timestamp()
        session = DecisionSession(
            session_id=session_id,
            student_id=student_id,
            scenario_id=scenario_id,
            started_at=now,
            alert_received_at=now,
        )
        self._sessions[session_id] = session
        return session

    def record_event(self, session_id: str, event_type: str, 
                     detail: dict | None = None):
        """记录一次行为事件"""
        session = self._sessions.get(session_id)
        if not session:
            return
        
        now = datetime.now().timestamp()
        event = BehaviorEvent(
            event_type=event_type,
            timestamp=now,
            detail=detail or {},
        )
        session.events.append(event)
        
        # 特殊事件处理
        if event_type == "plan_modify":
            if session.first_plan_modify_at == 0:
                session.first_plan_modify_at = now
            session.plan_versions.append(detail or {})

    def record_submit(self, session_id: str, actions: list[dict]):
        """记录学生提交方案"""
        session = self._sessions.get(session_id)
        if not session:
            return
        
        session.submit_at = datetime.now().timestamp()
        session.submitted_actions = actions

    def get_raw_metrics(self, session_id: str) -> dict:
        """
        从原始事件流中聚合出五维指标
        
        Returns:
            {
                "response_time_sec": float,
                "risk_preference": {"high_risk_count": int, "low_risk_count": int, "ratio": float},
                "resource_utilization": {"vehicle_usage_rate": float, "warehouse_usage_rate": float, "redundancy_ratio": float},
                "info_attention": {"view_road_count": int, "view_weather_count": int, "view_cargo_count": int, "map_time_ratio": float},
                "plan_changes": int,
            }
        """
        session = self._sessions.get(session_id)
        if not session:
            return {}
        
        events = session.events
        
        # 1. 响应速度
        response_time = session.response_time_sec
        
        # 2. 风险偏好 - 从提交的actions中统计
        high_risk_count = 0
        low_risk_count = 0
        for action in session.submitted_actions:
            risk = action.get("risk_level", "low")
            if risk == "high":
                high_risk_count += 1
            else:
                low_risk_count += 1
        total_choices = high_risk_count + low_risk_count
        risk_ratio = high_risk_count / total_choices if total_choices > 0 else 0.0
        
        # 3. 资源利用
        vehicles_allocated = len(set(
            a.get("vehicle_id") for a in session.submitted_actions
            if a.get("vehicle_id")
        ))
        warehouses_allocated = len(set(
            a.get("warehouse_id") for a in session.submitted_actions
            if a.get("warehouse_id")
        ))
        total_available_vehicles = max(
            len(set(a.get("vehicle_id") for a in session.submitted_actions)), 1
        )
        # 冗余 = 调用的总载重 / 实际货物重量
        total_capacity = sum(a.get("vehicle_capacity", 0) for a in session.submitted_actions)
        total_cargo_weight = sum(a.get("cargo_weight", 0) for a in session.submitted_actions)
        redundancy = (total_capacity - total_cargo_weight) / max(total_capacity, 1) if total_capacity > 0 else 0.0
        
        # 4. 信息关注
        view_road_count = sum(1 for e in events if e.event_type == "view_road")
        view_weather_count = sum(1 for e in events if e.event_type == "view_weather")
        view_cargo_count = sum(1 for e in events if e.event_type == "view_cargo")
        map_events = [e for e in events if e.event_type == "view_map"]
        map_total_time = sum(e.detail.get("duration_sec", 0) for e in map_events)
        total_session_time = max(session.response_time_sec, 1)
        map_time_ratio = map_total_time / total_session_time
        
        # 5. 方案变更
        plan_changes = len(session.plan_versions)
        
        return {
            "response_time_sec": round(response_time, 1),
            "risk_preference": {
                "high_risk_count": high_risk_count,
                "low_risk_count": low_risk_count,
                "ratio": round(risk_ratio, 2),
            },
            "resource_utilization": {
                "vehicles_allocated": vehicles_allocated,
                "warehouses_allocated": warehouses_allocated,
                "redundancy_ratio": round(redundancy, 2),
            },
            "info_attention": {
                "view_road_count": view_road_count,
                "view_weather_count": view_weather_count,
                "view_cargo_count": view_cargo_count,
                "map_time_ratio": round(map_time_ratio, 2),
            },
            "plan_changes": plan_changes,
        }

    def get_session(self, session_id: str) -> Optional[DecisionSession]:
        return self._sessions.get(session_id)
