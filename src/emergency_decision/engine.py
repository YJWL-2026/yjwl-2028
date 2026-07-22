"""
主引擎 - 串联 Step 1~7 的完整决策流程
对应文档: 03-calculation-logic.md

流程:
  Step 1: 灾害影响分析
  Step 2: 货物优先级排序
  Step 3: 可用资源清点
  Step 4: 方案生成
  Step 5: 成本计算
  Step 6: 方案选择与备选方案
  Step 7: 评分计算
"""

from __future__ import annotations

import time
from datetime import datetime

from .models import (
    Action,
    ActionPlanType,
    Cargo,
    DecisionPlan,
    EvaluationConfig,
    ScenarioContext,
    ScoreBreakdown,
    Vehicle,
)
from .disaster_impact import DisasterImpactAnalyzer, DisasterImpactResult
from .priority import sort_cargo_by_priority, auto_assign_priority
from .resources import ResourceInventoryChecker, ResourceInventory
from .plan_generator import PlanGenerator, CandidatePlan
from .cost_calculator import CostCalculator
from .solution_selector import SolutionSelector, SolutionSet
from .scoring import ScoringEngine
from .comment_generator import CommentGenerator


class EmergencyDecisionEngine:
    """应急决策引擎 - 主调度器"""

    def __init__(self):
        self.impact_analyzer = DisasterImpactAnalyzer.__new__(DisasterImpactAnalyzer)
        self.inventory_checker = ResourceInventoryChecker.__new__(ResourceInventoryChecker)
        self.plan_generator = PlanGenerator.__new__(PlanGenerator)
        self.selector = SolutionSelector()
        self.scoring = ScoringEngine()
        self.comment_gen = CommentGenerator()
        self.cost_calc = CostCalculator()

        self.last_impact: DisasterImpactResult | None = None
        self.last_inventory: ResourceInventory | None = None

    def solve(self, scenario: ScenarioContext) -> DecisionPlan:
        """执行完整决策流程, 返回最优方案"""
        start_time = time.time()

        # Step 1: 灾害影响分析
        self.impact_analyzer = DisasterImpactAnalyzer(scenario.logistics_network)
        impact = self.impact_analyzer.analyze(
            scenario.disaster,
            scenario.vehicle_fleet,
            scenario.cargo_manifest,
            scenario.warehouses,
        )
        self.last_impact = impact

        # Step 2: 货物优先级排序
        # 自动判定优先级
        for cargo in scenario.cargo_manifest:
            auto_assign_priority(cargo)

        # 筛选受阻货物并排序
        blocked_ids = impact.blocked_cargo_ids + impact.destination_restricted_cargo_ids
        blocked_cargo = [c for c in scenario.cargo_manifest
                         if c.cargo_id in set(blocked_ids)]
        sorted_cargo = sort_cargo_by_priority(blocked_cargo)

        # Step 3: 可用资源清点
        self.inventory_checker = ResourceInventoryChecker(scenario.logistics_network)
        inventory = self.inventory_checker.check(
            scenario.vehicle_fleet,
            scenario.warehouses,
            impact,
        )
        self.last_inventory = inventory

        # Step 4: 方案生成
        self.plan_generator = PlanGenerator(scenario.logistics_network)
        candidates_map: dict[str, list[CandidatePlan]] = {}
        for cargo in sorted_cargo:
            candidates = self.plan_generator.generate_candidates(cargo, inventory)
            candidates_map[cargo.cargo_id] = candidates

        # 构建查找表
        cargo_map = {c.cargo_id: c for c in scenario.cargo_manifest}
        vehicle_map = {v.vehicle_id: v for v in scenario.vehicle_fleet}

        # Step 5: 成本计算 (在方案选择中执行)
        # Step 6: 方案选择
        # 为备选方案生成需要独立的inventory副本
        optimal = self.selector.select_optimal(
            sorted_cargo, candidates_map, inventory, cargo_map, vehicle_map)

        # 生成备选方案
        alternatives_raw = self.selector.generate_alternatives(
            sorted_cargo, candidates_map, inventory, cargo_map, vehicle_map)

        # Step 7: 评分计算
        score = self.scoring.score_solution(
            optimal, scenario.cargo_manifest, scenario.evaluation,
            total_blocked_roads=len(impact.blocked_road_ids),
            available_vehicle_count=inventory.vehicle_count,
            available_warehouse_count=inventory.warehouse_count,
        )

        # 生成备选方案dict
        alternatives = []
        labels = ["成本优先方案", "时效优先方案"]
        for i, alt in enumerate(alternatives_raw[:2]):
            alt_score = self.scoring.score_solution(
                alt, scenario.cargo_manifest, scenario.evaluation,
                total_blocked_roads=len(impact.blocked_road_ids),
                available_vehicle_count=inventory.vehicle_count,
                available_warehouse_count=inventory.warehouse_count,
            )
            alternatives.append({
                "plan_id": f"ALT-{i+1}",
                "description": f"{labels[i]}: {alt.description()}",
                "total_cost": alt.total_cost,
                "cargo_abandoned": alt.cargo_abandoned,
                "vehicles_used": alt.vehicles_used,
                "score": alt_score.total,
            })

        # 生成方案说明
        explanation = self._generate_explanation(
            optimal, scenario, impact)

        # 构建Action列表
        actions = []
        for i, plan in enumerate(optimal.plans):
            action = plan.to_action(f"ACT-{i+1:03d}")
            actions.append(action)

        solve_time = round((time.time() - start_time) * 1000, 0)

        result = DecisionPlan(
            plan_id=f"OPT-{scenario.scenario_id}-v1",
            scenario_id=scenario.scenario_id,
            generated_at=datetime.now().isoformat(timespec='seconds'),
            total_cost=optimal.total_cost,
            total_delay_hours=round(optimal.total_delay_hours, 1),
            vehicles_used=optimal.vehicles_used,
            warehouses_used=optimal.warehouses_used,
            cargo_delivered=optimal.cargo_delivered,
            cargo_abandoned=optimal.cargo_abandoned,
            cargo_stored=optimal.cargo_stored,
            actions=actions,
            score_breakdown=score,
            alternatives=alternatives,
            explanation=explanation,
        )

        return result

    def generate_comment(self, plan: DecisionPlan,
                          disaster_type: str = "earthquake",
                          literacy_profile: dict | None = None) -> str:
        """生成三段式评语"""
        if not plan.score_breakdown:
            return "评分数据缺失"

        breakdown_dict = {
            "timeliness": {"score": plan.score_breakdown.timeliness.score,
                           "reason": plan.score_breakdown.timeliness.reason},
            "economic": {"score": plan.score_breakdown.economic.score,
                         "reason": plan.score_breakdown.economic.reason},
            "feasibility": {"score": plan.score_breakdown.feasibility.score,
                            "reason": plan.score_breakdown.feasibility.reason},
            "compliance": {"score": plan.score_breakdown.compliance.score,
                          "reason": plan.score_breakdown.compliance.reason},
        }

        return self.comment_gen.generate(
            total_score=plan.score_breakdown.total,
            score_breakdown=breakdown_dict,
            disaster_type=disaster_type,
            literacy_profile=literacy_profile,
        )

    def _generate_explanation(self, solution: SolutionSet,
                               scenario: ScenarioContext,
                               impact: DisasterImpactResult) -> str:
        """生成方案说明"""
        parts = []

        parts.append(
            f"灾害影响: {impact.total_affected_roads}条路段受影响"
            f"(中断{len(impact.blocked_road_ids)}, "
            f"限行{len(impact.restricted_road_ids)}), "
            f"{impact.total_affected_cargo}单货物受阻。")

        parts.append(
            f"推荐方案: {solution.description()}. "
            f"使用{solution.vehicles_used}辆车, "
            f"{solution.warehouses_used}个仓库, "
            f"总成本{solution.total_cost:.0f}元。")

        if solution.cargo_delivered > 0:
            parts.append(f"改道送达{solution.cargo_delivered}单(含医疗物资保障)。")
        if solution.cargo_stored > 0:
            parts.append(f"转仓暂存{solution.cargo_stored}单待灾后配送。")
        if solution.cargo_abandoned > 0:
            parts.append(f"放弃{solution.cargo_abandoned}单普通货物以节省资源。")

        return " ".join(parts)

    def get_impact_summary(self) -> str:
        """获取灾害影响摘要"""
        if self.last_impact:
            return self.last_impact.summary()
        return "未执行分析"
