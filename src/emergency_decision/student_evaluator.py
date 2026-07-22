"""
学生方案评估 - 对比学生提交的方案与系统最优方案
对应文档: 01-decision-engine-spec.md Section 6
         03-calculation-logic.md 学生方案对比逻辑
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    Action,
    ActionPlanType,
    Cargo,
    DecisionPlan,
    DimensionScore,
    EvaluationConfig,
    ScoreBreakdown,
    ScoreWeights,
)
from .scoring import ScoringEngine


@dataclass
class StudentAction:
    """学生提交的决策动作"""
    cargo_id: str
    action_type: ActionPlanType
    vehicle_id: str = ""
    route: list[str] = field(default_factory=list)
    warehouse_id: str = ""


@dataclass
class StudentSubmission:
    """学生方案提交"""
    student_id: str
    scenario_id: str
    actions: list[StudentAction] = field(default_factory=list)
    submit_time_offset_sec: float = 0  # 从预警到提交的时间(秒)
    is_first_submit: bool = True


class StudentPlanEvaluator:
    """学生方案评估器"""

    def __init__(self):
        self.scoring = ScoringEngine()

    def evaluate(self, submission: StudentSubmission,
                 cargo_list: list[Cargo],
                 config: EvaluationConfig,
                 optimal_plan: DecisionPlan,
                 available_vehicles: int = 0,
                 available_warehouses: int = 0) -> dict:
        """
        评估学生方案并与最优方案对比

        Returns:
            对比结果dict (含optimal_plan, student_plan, diff, analysis)
        """
        # 1. 评估学生方案
        student_result = self._evaluate_student_actions(
            submission, cargo_list, config,
            available_vehicles, available_warehouses)

        # 2. 与最优方案对比
        diff = self._calc_diff(optimal_plan, student_result)

        # 3. 生成分析文本
        analysis = self._generate_analysis(optimal_plan, student_result, diff)

        return {
            "comparison_id": f"CMP-{submission.scenario_id}-{submission.student_id}",
            "optimal_plan": optimal_plan.to_dict(),
            "student_plan": student_result,
            "diff": diff,
            "analysis": analysis,
        }

    def _evaluate_student_actions(self, submission: StudentSubmission,
                                    cargo_list: list[Cargo],
                                    config: EvaluationConfig,
                                    av: int, aw: int) -> dict:
        """评估学生提交的动作"""
        cargo_map = {c.cargo_id: c for c in cargo_list}

        total_cost = 0.0
        total_delay = 0.0
        delivered = 0
        abandoned = 0
        stored = 0
        vehicles_used = set()
        warehouses_used = set()

        # 可行性校验
        feasibility_issues = []

        for action in submission.actions:
            cargo = cargo_map.get(action.cargo_id)
            if not cargo:
                continue

            if action.action_type == ActionPlanType.REROUTE:
                delivered += 1
                if action.vehicle_id:
                    vehicles_used.add(action.vehicle_id)
                # 简化成本估算
                cost = len(action.route) * 8.0 * 10  # 粗估
                total_cost += cost
                total_delay += 0  # 简化

            elif action.action_type == ActionPlanType.WAREHOUSE_TRANSFER:
                stored += 1
                if action.warehouse_id:
                    warehouses_used.add(action.warehouse_id)
                cost = cargo.volume_m3 * 2.5  # 简化仓储成本
                total_cost += cost

            elif action.action_type == ActionPlanType.ABANDON:
                if cargo.is_p1:
                    feasibility_issues.append(f"P1货物{cargo.cargo_id}不可放弃")
                else:
                    abandoned += 1
                    total_cost += cargo.value_yuan

        # 评分
        timeliness = DimensionScore(
            score=max(0, 100 - total_delay * 10),
            reason=f"超时{total_delay:.1f}小时" if total_delay > 0 else "按时送达"
        )
        economic = DimensionScore(
            score=round(min(100, 100 * config.benchmark_cost / max(total_cost, 1)), 1),
            reason=f"总成本{total_cost:.0f}元"
        )
        feasibility_score = 100
        if feasibility_issues:
            feasibility_score = max(0, 100 - len(feasibility_issues) * 30)
        feasibility = DimensionScore(
            score=feasibility_score,
            reason="; ".join(feasibility_issues) if feasibility_issues else "方案可行"
        )
        compliance = DimensionScore(
            score=100 if not feasibility_issues else 50,
            reason="合规" if not feasibility_issues else "存在违规"
        )

        breakdown = ScoreBreakdown(
            timeliness=timeliness,
            economic=economic,
            feasibility=feasibility,
            compliance=compliance,
        )

        weights = config.weights
        total_score = self.scoring.calc_total_score(breakdown, weights)

        # 加减分
        if submission.is_first_submit:
            total_score = min(100, total_score + 5)
        if submission.submit_time_offset_sec > 600:
            total_score = max(0, total_score - 10)

        return {
            "total_cost": round(total_cost, 1),
            "total_delay_hours": round(total_delay, 1),
            "vehicles_used": len(vehicles_used),
            "warehouses_used": len(warehouses_used),
            "cargo_delivered": delivered,
            "cargo_abandoned": abandoned,
            "cargo_stored": stored,
            "score_breakdown": {
                "timeliness": {"score": timeliness.score, "reason": timeliness.reason},
                "economic": {"score": economic.score, "reason": economic.reason},
                "feasibility": {"score": feasibility.score, "reason": feasibility.reason},
                "compliance": {"score": compliance.score, "reason": compliance.reason},
                "total": total_score,
            },
            "feasibility_issues": feasibility_issues,
        }

    def _calc_diff(self, optimal: DecisionPlan, student: dict) -> dict:
        """计算差异"""
        opt_score = optimal.score_breakdown.total if optimal.score_breakdown else 0
        stu_score = student.get("score_breakdown", {}).get("total", 0)

        return {
            "cost_delta": round(student["total_cost"] - optimal.total_cost, 1),
            "score_delta": round(stu_score - opt_score, 1),
            "timeliness_delta": round(
                student["score_breakdown"]["timeliness"]["score"] -
                (optimal.score_breakdown.timeliness.score if optimal.score_breakdown else 0), 1),
            "economic_delta": round(
                student["score_breakdown"]["economic"]["score"] -
                (optimal.score_breakdown.economic.score if optimal.score_breakdown else 0), 1),
            "feasibility_delta": round(
                student["score_breakdown"]["feasibility"]["score"] -
                (optimal.score_breakdown.feasibility.score if optimal.score_breakdown else 0), 1),
            "compliance_delta": round(
                student["score_breakdown"]["compliance"]["score"] -
                (optimal.score_breakdown.compliance.score if optimal.score_breakdown else 0), 1),
            "vehicles_delta": student["vehicles_used"] - optimal.vehicles_used,
        }

    def _generate_analysis(self, optimal: DecisionPlan,
                            student: dict, diff: dict) -> str:
        """生成对比分析文本"""
        lines = []

        cost_delta = diff["cost_delta"]
        if cost_delta > 0:
            pct = (cost_delta / max(optimal.total_cost, 1)) * 100
            lines.append(
                f"你的方案总成本 {student['total_cost']:.0f} 元, "
                f"比最优方案高 {cost_delta:.0f} 元 (+{pct:.0f}%)。")
        elif cost_delta < 0:
            lines.append(
                f"你的方案总成本 {student['total_cost']:.0f} 元, "
                f"比最优方案低 {-cost_delta:.0f} 元。")
        else:
            lines.append(f"你的方案成本与最优方案持平 ({student['total_cost']:.0f} 元)。")

        # 车辆差异
        v_delta = diff["vehicles_delta"]
        if v_delta > 0:
            lines.append(f"你多调用了 {v_delta} 辆备用车 "
                         f"(最优方案用{optimal.vehicles_used}辆, 你用了{student['vehicles_used']}辆)。")
        elif v_delta < 0:
            lines.append(f"你少调用了 {-v_delta} 辆车。")

        # 评分差异
        score_delta = diff["score_delta"]
        if score_delta < 0:
            lines.append(f"评分方面, 你的总分比最优方案低 {-score_delta:.1f} 分。")
            # 找差距最大的维度
            dims = {
                "时效性": diff["timeliness_delta"],
                "经济性": diff["economic_delta"],
                "可行性": diff["feasibility_delta"],
                "合规性": diff["compliance_delta"],
            }
            worst = min(dims, key=lambda k: dims[k])
            if dims[worst] < 0:
                lines.append(f"主要差距在{worst}维度 (低{-dims[worst]:.1f}分)。")
        else:
            lines.append("评分方面, 你的方案与最优方案接近。")

        # 建议
        if cost_delta > 0 or v_delta > 0:
            lines.append("建议: 关注资源利用率, 考虑是否可以合并配送以减少车辆调用。")

        return "\n".join(lines)
