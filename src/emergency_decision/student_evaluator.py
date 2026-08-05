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
        # 1. 评估学生方案（传入optimal_plan做相对评分）
        student_result = self._evaluate_student_actions(
            submission, cargo_list, config,
            available_vehicles, available_warehouses, optimal_plan)

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
                                    av: int, aw: int,
                                    optimal_plan: DecisionPlan = None) -> dict:
        """评估学生提交的动作 — 与最优方案对比评分"""
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

        # 最优方案数据（用于相对评分）
        opt_cost = optimal_plan.total_cost if optimal_plan else config.benchmark_cost
        opt_vehicles = optimal_plan.vehicles_used if optimal_plan else 0
        opt_delivered = optimal_plan.cargo_delivered if optimal_plan else 0
        opt_actions_count = len(optimal_plan.actions) if optimal_plan else 0

        # 受影响的货物总数（最优方案需要处理的）
        affected_cargo_count = max(opt_actions_count, opt_delivered, 1)

        for action in submission.actions:
            cargo = cargo_map.get(action.cargo_id)
            if not cargo:
                continue

            if action.action_type == ActionPlanType.REROUTE:
                delivered += 1
                if action.vehicle_id:
                    vehicles_used.add(action.vehicle_id)
                # 运输成本: 路线距离 × 单价 (与引擎一致)
                route_nodes = len(action.route) if action.route else 2
                cost = route_nodes * 8.0  # 每段路8元
                total_cost += cost
                # 延迟估算: 如果提交时间>120秒，开始累计延迟
                if submission.submit_time_offset_sec > 120:
                    total_delay += (submission.submit_time_offset_sec - 120) / 60.0 * 0.5

            elif action.action_type == ActionPlanType.WAREHOUSE_TRANSFER:
                stored += 1
                if action.warehouse_id:
                    warehouses_used.add(action.warehouse_id)
                # 仓储成本: 货物体积 × 仓储单价 (与引擎一致)
                cost = cargo.volume_m3 * 2.5
                total_cost += cost

            elif action.action_type == ActionPlanType.ABANDON:
                if cargo.is_p1:
                    feasibility_issues.append(f"P1货物{cargo.cargo_id}不可放弃")
                else:
                    abandoned += 1
                    total_cost += cargo.value_yuan

        # ===== 评分维度 =====

        # 1. 时效性 (30%): 基于提交时间和延迟
        # 提交越快分越高; 超过预期时间扣分
        submit_sec = submission.submit_time_offset_sec
        if submit_sec <= 60:
            time_score = 100
        elif submit_sec <= 180:
            time_score = 100 - (submit_sec - 60) * 0.3  # 60-180秒: 100→64
        elif submit_sec <= 300:
            time_score = 64 - (submit_sec - 180) * 0.2  # 180-300秒: 64→40
        else:
            time_score = max(10, 40 - (submit_sec - 300) * 0.1)  # 300秒+: 递减
        # 延迟扣分
        time_score = max(0, time_score - total_delay * 10)
        timeliness = DimensionScore(
            score=round(time_score, 1),
            reason=f"提交用时{submit_sec:.0f}秒" + (f", 延迟{total_delay:.1f}小时" if total_delay > 0 else "")
        )

        # 2. 经济性 (25%: 与最优方案成本对比
        # 学生成本 vs 最优成本, 越接近最优分越高
        if opt_cost > 0:
            if total_cost <= opt_cost:
                # 成本低于或等于最优 → 满分(但需检查是否漏处理货物)
                handled = delivered + stored
                if handled < affected_cargo_count:
                    # 漏处理货物: 成本低是因为没干活, 扣分
                    ratio = handled / affected_cargo_count
                    econ_score = round(100 * ratio, 1)
                else:
                    econ_score = 100.0
            else:
                # 成本高于最优 → 按比例扣分
                ratio = opt_cost / total_cost
                econ_score = round(100 * ratio, 1)
        else:
            # 最优方案零成本(无需操作)
            if total_cost > 0:
                # 学生做了不必要的操作
                econ_score = max(20, 100 - total_cost / 100)
            else:
                econ_score = 100.0
        economic = DimensionScore(
            score=econ_score,
            reason=f"学生成本{total_cost:.0f}元 vs 最优{opt_cost:.0f}元"
        )

        # 3. 可行性 (25%): 资源使用合理性 + 车辆多余调用扣分
        feas_score = 100.0
        # 车辆超限扣分
        if len(vehicles_used) > av and av > 0:
            feas_score -= 60
        # 仓库超限扣分
        if len(warehouses_used) > aw and aw > 0:
            feas_score -= 40
        # 比最优方案多调用的车辆扣分
        extra_vehicles = len(vehicles_used) - opt_vehicles
        if extra_vehicles > 0:
            feas_score -= extra_vehicles * 8  # 每多一辆车扣8分
        feas_score = max(0, feas_score)
        feasibility = DimensionScore(
            score=round(feas_score, 1),
            reason=f"使用{len(vehicles_used)}辆车(最优{opt_vehicles}辆)" +
                   (f", 多用{extra_vehicles}辆" if extra_vehicles > 0 else "")
        )

        # 4. 合规性 (20%): P1保障 + 货物覆盖率
        compliance_score = 100.0
        if feasibility_issues:
            compliance_score = max(0, 100 - len(feasibility_issues) * 30)
        # 货物覆盖率: 学生处理的货物数 vs 应处理货物数
        handled = delivered + stored
        if affected_cargo_count > 0 and handled < affected_cargo_count:
            coverage = handled / affected_cargo_count
            # 覆盖率不足扣分
            compliance_score = min(compliance_score, round(100 * coverage, 1))
        compliance = DimensionScore(
            score=round(compliance_score, 1),
            reason="; ".join(feasibility_issues) if feasibility_issues else
                   (f"处理{handled}/{affected_cargo_count}单" if handled < affected_cargo_count else "合规")
        )

        breakdown = ScoreBreakdown(
            timeliness=timeliness,
            economic=economic,
            feasibility=feasibility,
            compliance=compliance,
        )

        weights = config.weights
        total_score = self.scoring.calc_total_score(breakdown, weights)

        # 超时大惩罚（>10分钟才扣，不额外奖励首次提交）
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
