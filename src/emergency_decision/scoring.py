"""
评分计算 - Step 7
对应文档: 03-calculation-logic.md Step 7

四维评分:
  - 时效性 (30%): 超时扣分
  - 经济性 (25%): 实际成本 vs 基准成本
  - 可行性 (25%): 资源合规 + 路径可达
  - 合规性 (20%): P1货物保障检查
"""

from __future__ import annotations

from .models import (
    Cargo,
    DimensionScore,
    EvaluationConfig,
    ScoreBreakdown,
    ScoreWeights,
)
from .solution_selector import SolutionSet
from .plan_generator import CandidatePlan
from .models import ActionPlanType


class ScoringEngine:
    """评分引擎"""

    def score_solution(self, solution: SolutionSet,
                        cargo_list: list[Cargo],
                        config: EvaluationConfig,
                        total_blocked_roads: int = 0,
                        available_vehicle_count: int = 0,
                        available_warehouse_count: int = 0) -> ScoreBreakdown:
        """对方案集计算四维评分"""

        timeliness = self._score_timeliness(solution, cargo_list)
        economic = self._score_economic(solution, config)
        feasibility = self._score_feasibility(solution,
                                                available_vehicle_count,
                                                available_warehouse_count,
                                                total_blocked_roads)
        compliance = self._score_compliance(solution, cargo_list)

        return ScoreBreakdown(
            timeliness=timeliness,
            economic=economic,
            feasibility=feasibility,
            compliance=compliance,
        )

    def _score_timeliness(self, solution: SolutionSet,
                            cargo_list: list[Cargo]) -> DimensionScore:
        """时效性得分 = 100 - 超时扣分"""
        total_penalty = 0.0
        overtime_count = 0

        for plan in solution.plans:
            if plan.delay_hours > 0:
                deduction = plan.delay_hours * 10  # 每小时扣10分
                total_penalty += deduction
                overtime_count += 1

        score = max(0, 100 - total_penalty)

        if overtime_count == 0:
            reason = "所有货物按时送达"
        else:
            avg_delay = solution.total_delay_hours / max(overtime_count, 1)
            reason = f"{overtime_count}单超时, 平均超时{avg_delay:.1f}小时"

        return DimensionScore(score=round(score, 1), reason=reason)

    def _score_economic(self, solution: SolutionSet,
                          config: EvaluationConfig) -> DimensionScore:
        """经济性得分 = 100 × (基准成本 / max(实际成本, 基准成本))"""
        benchmark = config.benchmark_cost
        actual = solution.total_cost

        if actual <= 0:
            return DimensionScore(score=100, reason="无运输成本")

        if actual <= benchmark:
            score = 100
            reason = f"总成本{actual:.0f}元 ≤ 基准{benchmark:.0f}元"
        else:
            ratio = benchmark / actual
            score = round(100 * ratio, 1)
            over_pct = (actual - benchmark) / benchmark * 100
            reason = f"总成本{actual:.0f}元, 超基准{over_pct:.0f}%"

        return DimensionScore(score=score, reason=reason)

    def _score_feasibility(self, solution: SolutionSet,
                            available_vehicles: int,
                            available_warehouses: int,
                            total_blocked_roads: int) -> DimensionScore:
        """可行性得分 = 资源合规分×0.6 + 路径可达分×0.4"""

        # 资源合规
        resource_score = 100
        if solution.vehicles_used > available_vehicles and available_vehicles > 0:
            resource_score -= 60  # 车辆不足
        if solution.warehouses_used > available_warehouses and available_warehouses > 0:
            resource_score -= 40  # 仓库不足
        resource_score = max(0, resource_score)

        # 路径可达
        path_score = 100
        # 检查是否有方案经过中断路段 (简化: 所有reroute方案都算可达)
        blocked_routes = 0
        for plan in solution.plans:
            if not plan.feasibility:
                blocked_routes += 1
                path_score -= 30
        path_score = max(0, path_score)

        total_score = round(resource_score * 0.6 + path_score * 0.4, 1)

        reasons = []
        if resource_score == 100:
            reasons.append("资源使用合规")
        else:
            reasons.append("资源超限")
        if path_score == 100:
            reasons.append("路径全部可达")
        else:
            reasons.append(f"{blocked_routes}个方案路径不可达")

        return DimensionScore(score=total_score, reason="; ".join(reasons))

    def _score_compliance(self, solution: SolutionSet,
                            cargo_list: list[Cargo]) -> DimensionScore:
        """合规性得分 = 100 - 违规扣分"""
        deduction = 0.0
        violations = []

        cargo_map = {c.cargo_id: c for c in cargo_list}

        for plan in solution.plans:
            cargo = cargo_map.get(plan.cargo_id)
            if not cargo:
                continue

            # P1货物被放弃 → 扣50分
            if plan.plan_type == ActionPlanType.ABANDON and cargo.is_p1:
                deduction += 50
                violations.append(f"P1货物{cargo.cargo_id}被放弃(严重)")

            # P1货物超时 → 扣20分
            elif cargo.is_p1 and plan.delay_hours > 0:
                deduction += 20
                violations.append(f"P1货物{cargo.cargo_id}超时")

            # P2货物被放弃 → 扣10分
            elif plan.plan_type == ActionPlanType.ABANDON and cargo.is_p2:
                deduction += 10
                violations.append(f"P2货物{cargo.cargo_id}被放弃")

        # 检查是否有医疗物资未优先保障
        medical_cargos = [c for c in cargo_list if c.cargo_type.value == "medical"]
        medical_abandoned = sum(1 for p in solution.plans
                                for c in [cargo_map.get(p.cargo_id)]
                                if c and c.cargo_type.value == "medical"
                                and p.plan_type == ActionPlanType.ABANDON)
        if medical_abandoned > 0:
            deduction += 20
            violations.append("医疗物资未优先保障")

        score = max(0, 100 - deduction)

        if not violations:
            reason = "医疗/民生物资全部保障"
        else:
            reason = "; ".join(violations)

        return DimensionScore(score=round(score, 1), reason=reason)

    def calc_total_score(self, breakdown: ScoreBreakdown,
                          weights: ScoreWeights,
                          bonus: float = 0, penalty: float = 0) -> float:
        """计算总分 = Σ(各维度得分×权重) + 加减分"""
        total = (breakdown.timeliness.score * weights.timeliness +
                 breakdown.economic.score * weights.economic +
                 breakdown.feasibility.score * weights.feasibility +
                 breakdown.compliance.score * weights.compliance)
        total += bonus + penalty
        return round(max(0, min(100, total)), 1)

    @staticmethod
    def get_grade(score: float) -> tuple[str, str]:
        """评分等级映射"""
        if score >= 90:
            return "A", "卓越的全局掌控力"
        elif score >= 80:
            return "B", "方案整体可行, 有优化空间"
        elif score >= 70:
            return "C", "基本完成决策, 存在明显不足"
        elif score >= 60:
            return "D", "决策存在较大问题"
        else:
            return "E", "决策失败, 需重新学习"
