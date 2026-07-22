"""
素养画像生成器 - 将五维行为数据映射为三维核心素养
对应文档: 技术要求 "育"功能 3.2.2 素养画像生成模型

三大核心素养维度:
  1. 风险意识 (Risk Awareness)     - 对潜在威胁的敏感度和预判能力
  2. 系统思维 (System Thinking)     - 全局视角统筹多环节的综合决策能力
  3. 决策韧性 (Decision Resilience) - 面对突发干扰时保持理性的能力

算法逻辑 (权重参考):
  风险意识 = 响应速度(20%) + 安全路线偏好(40%) + 查看路况/天气频次(30%) + 预留资源比例(10%)
  系统思维 = 查看货物清单频次(20%) + 多环节联动操作(40%) + 备选方案尝试次数(40%)
  决策韧性 = 决策用时稳定性(50%) + 最终方案偏离初始方案的程度(50%)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# 等级定义
# ============================================================

LEVEL_THRESHOLDS = {
    "S": (95, "卓越"),
    "A": (85, "优秀"),
    "B": (70, "良好"),
    "C": (55, "合格"),
    "D": (0, "待提升"),
}

LEVEL_BADGES = {
    "risk_awareness": {
        "S": "S级（洞察）",
        "A": "A级（敏锐）",
        "B": "B级（良好）",
        "C": "C级（一般）",
        "D": "D级（不足）",
    },
    "system_thinking": {
        "S": "S级（全局）",
        "A": "A级（优秀）",
        "B": "B级（良好）",
        "C": "C级（一般）",
        "D": "D级（不足）",
    },
    "decision_resilience": {
        "S": "S级（稳健）",
        "A": "A级（从容）",
        "B": "B级（良好）",
        "C": "C级（一般）",
        "D": "D级（不足）",
    },
}


def get_level(score: float) -> tuple[str, str]:
    """根据分数返回 (等级字母, 描述)"""
    for level, (threshold, desc) in LEVEL_THRESHOLDS.items():
        if score >= threshold:
            return level, desc
    return "D", "待提升"


@dataclass
class DimensionResult:
    """单维素养结果"""
    score: float
    level: str
    level_desc: str
    badge: str
    sub_scores: dict        # 子项得分明细
    assessment: str          # 该维度的文字评价


@dataclass
class LiteracyProfile:
    """三维素养画像"""
    student_id: str
    scenario_id: str
    risk_awareness: DimensionResult
    system_thinking: DimensionResult
    decision_resilience: DimensionResult
    
    @property
    def overall_score(self) -> float:
        return round(
            (self.risk_awareness.score + 
             self.system_thinking.score + 
             self.decision_resilience.score) / 3, 1
        )
    
    @property
    def overall_level(self) -> tuple[str, str]:
        return get_level(self.overall_score)

    def to_dict(self) -> dict:
        ol, old = self.overall_level
        return {
            "student_id": self.student_id,
            "scenario_id": self.scenario_id,
            "radar_data": {
                "labels": ["风险意识", "系统思维", "决策韧性"],
                "values": [
                    self.risk_awareness.score,
                    self.system_thinking.score,
                    self.decision_resilience.score,
                ],
            },
            "dimensions": {
                "risk_awareness": {
                    "score": self.risk_awareness.score,
                    "level": self.risk_awareness.level,
                    "badge": self.risk_awareness.badge,
                    "assessment": self.risk_awareness.assessment,
                    "sub_scores": self.risk_awareness.sub_scores,
                },
                "system_thinking": {
                    "score": self.system_thinking.score,
                    "level": self.system_thinking.level,
                    "badge": self.system_thinking.badge,
                    "assessment": self.system_thinking.assessment,
                    "sub_scores": self.system_thinking.sub_scores,
                },
                "decision_resilience": {
                    "score": self.decision_resilience.score,
                    "level": self.decision_resilience.level,
                    "badge": self.decision_resilience.badge,
                    "assessment": self.decision_resilience.assessment,
                    "sub_scores": self.decision_resilience.sub_scores,
                },
            },
            "overall": {
                "score": self.overall_score,
                "level": ol,
                "level_desc": old,
            },
        }


class ProfileGenerator:
    """素养画像生成器"""

    def generate(self, raw_metrics: dict, student_id: str, 
                 scenario_id: str,
                 multi_session_times: list[float] | None = None,
                 multi_session_plans: list[dict] | None = None) -> LiteracyProfile:
        """
        从五维原始指标生成三维素养画像
        
        Args:
            raw_metrics: BehaviorTracker.get_raw_metrics() 的输出
            student_id: 学生ID
            scenario_id: 场景ID
            multi_session_times: 多轮决策的用时列表(用于计算决策韧性中的稳定性)
            multi_session_plans: 多轮决策的方案列表(用于计算方案偏离度)
        """
        risk = self._calc_risk_awareness(raw_metrics)
        system = self._calc_system_thinking(raw_metrics)
        resilience = self._calc_decision_resilience(
            raw_metrics, multi_session_times, multi_session_plans)

        return LiteracyProfile(
            student_id=student_id,
            scenario_id=scenario_id,
            risk_awareness=risk,
            system_thinking=system,
            decision_resilience=resilience,
        )

    def _calc_risk_awareness(self, metrics: dict) -> DimensionResult:
        """
        风险意识 = 响应速度(20%) + 安全路线偏好(40%) + 查看路况/天气频次(30%) + 预留资源比例(10%)
        """
        response_sec = metrics.get("response_time_sec", 300)
        risk_pref = metrics.get("risk_preference", {})
        info = metrics.get("info_attention", {})
        resource = metrics.get("resource_utilization", {})
        
        # 子项1: 响应速度 (越快越高分，<=60秒=100, >=600秒=0)
        if response_sec <= 60:
            response_score = 100
        elif response_sec >= 600:
            response_score = max(0, 100 - (response_sec - 600) / 10)
        else:
            response_score = 100 - (response_sec - 60) / 5.4
        response_score = max(0, min(100, response_score))
        
        # 子项2: 安全路线偏好 (低风险选择占比越高，风险意识越好)
        # ratio = 高风险选择比例，1-ratio = 安全选择比例
        safe_ratio = 1 - risk_pref.get("ratio", 0)
        safe_score = safe_ratio * 100
        
        # 子项3: 查看路况/天气频次 (查看越多，风险意识越强)
        view_count = (info.get("view_road_count", 0) + 
                      info.get("view_weather_count", 0))
        if view_count >= 5:
            view_score = 100
        else:
            view_score = view_count * 20
        
        # 子项4: 预留资源比例 (适度的冗余说明有风险预案)
        redundancy = resource.get("redundancy_ratio", 0)
        # 0.1-0.3 是最佳冗余区间，过高过低都扣分
        if 0.1 <= redundancy <= 0.3:
            resource_score = 100
        elif redundancy < 0.1:
            resource_score = redundancy / 0.1 * 100
        else:
            resource_score = max(0, 100 - (redundancy - 0.3) * 200)
        
        total = (response_score * 0.20 + safe_score * 0.40 + 
                 view_score * 0.30 + resource_score * 0.10)
        total = round(total, 1)
        
        level, desc = get_level(total)
        badge = LEVEL_BADGES["risk_awareness"][level]
        
        assessment = self._risk_assessment(response_sec, safe_ratio, view_count, total)
        
        return DimensionResult(
            score=total,
            level=level,
            level_desc=desc,
            badge=badge,
            sub_scores={
                "response_speed": round(response_score, 1),
                "safe_route_preference": round(safe_score, 1),
                "info_inspection": round(view_score, 1),
                "resource_reserve": round(resource_score, 1),
            },
            assessment=assessment,
        )

    def _risk_assessment(self, response_sec, safe_ratio, view_count, score) -> str:
        parts = []
        if response_sec <= 120:
            parts.append("预警响应迅速")
        elif response_sec > 300:
            parts.append("预警响应偏慢")
        
        if safe_ratio >= 0.7:
            parts.append("偏好安全路线，风险规避意识强")
        elif safe_ratio < 0.4:
            parts.append("频繁选择高风险路线，需增强风险预判")
        
        if view_count >= 3:
            parts.append("主动查看路况和天气信息")
        else:
            parts.append("信息查看不足，可能遗漏次生灾害")
        
        return "；".join(parts) + "。"

    def _calc_system_thinking(self, metrics: dict) -> DimensionResult:
        """
        系统思维 = 查看货物清单频次(20%) + 多环节联动操作(40%) + 备选方案尝试次数(40%)
        """
        info = metrics.get("info_attention", {})
        resource = metrics.get("resource_utilization", {})
        plan_changes = metrics.get("plan_changes", 0)
        submitted = metrics.get("submitted_actions", [])
        
        # 子项1: 查看货物清单频次
        view_cargo = info.get("view_cargo_count", 0)
        if view_cargo >= 5:
            cargo_score = 100
        else:
            cargo_score = view_cargo * 20
        
        # 子项2: 多环节联动操作 (同时调车+改仓 的比例)
        # 统计学生方案中同时涉及车辆和仓库的操作
        multi_link = 0
        total_actions = len(submitted)
        has_vehicle = any(a.get("vehicle_id") for a in submitted)
        has_warehouse = any(a.get("warehouse_id") for a in submitted)
        if has_vehicle and has_warehouse:
            multi_link = 1  # 至少有一次联动
        
        # 从resource数据推断联动度
        vehicles = resource.get("vehicles_allocated", 0)
        warehouses = resource.get("warehouses_allocated", 0)
        if vehicles > 0 and warehouses > 0:
            link_score = 100
        elif vehicles > 0 or warehouses > 0:
            link_score = 50
        else:
            link_score = 0
        
        # 子项3: 备选方案尝试次数 (适度尝试=好，频繁改=差)
        if plan_changes >= 3:
            plan_score = 100
        elif plan_changes >= 1:
            plan_score = plan_changes * 33
        else:
            plan_score = 20  # 没尝试说明没探索
        
        total = (cargo_score * 0.20 + link_score * 0.40 + plan_score * 0.40)
        total = round(total, 1)
        
        level, desc = get_level(total)
        badge = LEVEL_BADGES["system_thinking"][level]
        
        assessment = self._system_assessment(view_cargo, vehicles, warehouses, 
                                              plan_changes, total)
        
        return DimensionResult(
            score=total,
            level=level,
            level_desc=desc,
            badge=badge,
            sub_scores={
                "cargo_inspection": round(cargo_score, 1),
                "multi_link_operation": round(link_score, 1),
                "alternative_attempts": round(plan_score, 1),
            },
            assessment=assessment,
        )

    def _system_assessment(self, view_cargo, vehicles, warehouses, 
                            plan_changes, score) -> str:
        parts = []
        if view_cargo >= 3:
            parts.append("全面查看货物清单，了解全局物资分布")
        else:
            parts.append("货物清单查看不足，可能遗漏关键物资")
        
        if vehicles > 0 and warehouses > 0:
            parts.append("能同时调度车辆和仓库，体现多环节联动思维")
        else:
            parts.append("仅单一环节操作，缺乏全局统筹")
        
        if plan_changes >= 2:
            parts.append("尝试多个备选方案，思维灵活")
        elif plan_changes == 0:
            parts.append("未尝试备选方案，思维偏单一")
        
        return "；".join(parts) + "。"

    def _calc_decision_resilience(self, metrics: dict,
                                    multi_times: list[float] | None,
                                    multi_plans: list[dict] | None) -> DimensionResult:
        """
        决策韧性 = 决策用时稳定性(50%) + 最终方案偏离初始方案的程度(50%)
        """
        response_sec = metrics.get("response_time_sec", 300)
        plan_changes = metrics.get("plan_changes", 0)
        
        # 子项1: 决策用时稳定性
        # 多轮决策的用时标准差越小，越稳定
        if multi_times and len(multi_times) >= 2:
            avg = sum(multi_times) / len(multi_times)
            if avg > 0:
                variance = sum((t - avg) ** 2 for t in multi_times) / len(multi_times)
                cv = (variance ** 0.5) / avg  # 变异系数
                # CV越小越稳定，CV<0.2=满分
                if cv <= 0.2:
                    stability_score = 100
                elif cv >= 1.0:
                    stability_score = 30
                else:
                    stability_score = 100 - (cv - 0.2) / 0.8 * 70
            else:
                stability_score = 50
        else:
            # 单轮决策，用响应时间在合理区间来评估
            if 60 <= response_sec <= 300:
                stability_score = 80  # 合理用时区间
            elif response_sec < 60:
                stability_score = 60  # 过快可能未深思
            else:
                stability_score = 40  # 过慢可能犹豫
        
        # 子项2: 最终方案偏离初始方案的程度
        # 适度调整=好(说明根据新信息修正)，大改或完全不变都可能有问题
        if plan_changes == 0:
            # 没改过——可能太固执或没收到新信息
            deviation_score = 60
        elif plan_changes <= 3:
            # 适度调整——根据新信息修正，体现理性
            deviation_score = 100
        elif plan_changes <= 5:
            # 改得较多——有一定波动
            deviation_score = 70
        else:
            # 频繁修改——决策摇摆
            deviation_score = 40
        
        total = stability_score * 0.50 + deviation_score * 0.50
        total = round(total, 1)
        
        level, desc = get_level(total)
        badge = LEVEL_BADGES["decision_resilience"][level]
        
        assessment = self._resilience_assessment(
            stability_score, deviation_score, plan_changes, total)
        
        return DimensionResult(
            score=total,
            level=level,
            level_desc=desc,
            badge=badge,
            sub_scores={
                "time_stability": round(stability_score, 1),
                "plan_deviation": round(deviation_score, 1),
            },
            assessment=assessment,
        )

    def _resilience_assessment(self, stability, deviation, 
                                 plan_changes, score) -> str:
        parts = []
        if stability >= 80:
            parts.append("决策用时稳定，情绪控制良好")
        elif stability >= 50:
            parts.append("决策用时波动一般")
        else:
            parts.append("决策用时波动较大，可能受情绪干扰")
        
        if plan_changes == 0:
            parts.append("方案一次定型，建议适当评估备选")
        elif plan_changes <= 3:
            parts.append("方案适度修正，体现理性迭代")
        else:
            parts.append("方案频繁变更，需提升决策定力")
        
        return "；".join(parts) + "。"


@dataclass
class GrowthRecord:
    """成长曲线记录"""
    session_id: str
    scenario_id: str
    timestamp: str
    risk_awareness: float
    system_thinking: float
    decision_resilience: float
    overall: float


class GrowthTracker:
    """成长曲线追踪器 - 跨多轮决策记录素养变化"""

    def __init__(self):
        self._records: dict[str, list[GrowthRecord]] = {}  # student_id -> records

    def add_record(self, student_id: str, profile: LiteracyProfile, 
                   session_id: str):
        record = GrowthRecord(
            session_id=session_id,
            scenario_id=profile.scenario_id,
            timestamp=__import__("datetime").datetime.now().isoformat(
                timespec="minutes"),
            risk_awareness=profile.risk_awareness.score,
            system_thinking=profile.system_thinking.score,
            decision_resilience=profile.decision_resilience.score,
            overall=profile.overall_score,
        )
        if student_id not in self._records:
            self._records[student_id] = []
        self._records[student_id].append(record)

    def get_growth_curve(self, student_id: str) -> dict:
        records = self._records.get(student_id, [])
        if not records:
            return {"labels": [], "risk": [], "system": [], "resilience": [], "overall": []}
        
        return {
            "labels": [r.timestamp for r in records],
            "risk": [r.risk_awareness for r in records],
            "system": [r.system_thinking for r in records],
            "resilience": [r.decision_resilience for r in records],
            "overall": [r.overall for r in records],
        }

    def get_class_distribution(self, student_ids: list[str]) -> dict:
        """获取班级全体学生的画像分布（用于教师后台）"""
        distribution = {
            "risk_awareness": {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0},
            "system_thinking": {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0},
            "decision_resilience": {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0},
        }
        student_latest = {}
        for sid in student_ids:
            records = self._records.get(sid, [])
            if records:
                student_latest[sid] = records[-1]
        
        for sid, record in student_latest.items():
            for dim, attr in [("risk_awareness", "risk_awareness"),
                              ("system_thinking", "system_thinking"),
                              ("decision_resilience", "decision_resilience")]:
                score = getattr(record, attr)
                level, _ = get_level(score)
                distribution[dim][level] += 1
        
        return {
            "total_students": len(student_latest),
            "distribution": distribution,
            "student_scores": [
                {
                    "student_id": sid,
                    "risk_awareness": r.risk_awareness,
                    "system_thinking": r.system_thinking,
                    "decision_resilience": r.decision_resilience,
                    "overall": r.overall,
                }
                for sid, r in student_latest.items()
            ],
        }
