"""
方案选择 - Step 6
对应文档: 03-calculation-logic.md Step 6

功能:
  - 按优先级队列依次为货物分配最低成本方案
  - 资源消耗后约束校验
  - 生成最优方案 + 备选方案(成本优先/时效优先)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import Cargo, Vehicle, ActionPlanType
from .plan_generator import CandidatePlan
from .cost_calculator import CostCalculator
from .resources import ResourceInventory


@dataclass
class SolutionSet:
    """一组完整方案"""
    plans: list[CandidatePlan] = field(default_factory=list)
    total_cost: float = 0.0
    total_delay_hours: float = 0.0
    vehicles_used: int = 0
    warehouses_used: int = 0
    cargo_delivered: int = 0
    cargo_abandoned: int = 0
    cargo_stored: int = 0

    def description(self) -> str:
        parts = []
        if self.cargo_delivered:
            parts.append(f"改道送达{self.cargo_delivered}单")
        if self.cargo_stored:
            parts.append(f"转仓{self.cargo_stored}单")
        if self.cargo_abandoned:
            parts.append(f"放弃{self.cargo_abandoned}单")
        return "、".join(parts) if parts else "无操作"


class SolutionSelector:
    """方案选择器"""

    def __init__(self):
        self.cost_calc = CostCalculator()

    def select_optimal(self, sorted_cargo: list[Cargo],
                       candidates_map: dict[str, list[CandidatePlan]],
                       inventory: ResourceInventory,
                       cargo_map: dict[str, Cargo],
                       vehicle_map: dict[str, Vehicle]) -> SolutionSet:
        """
        按优先级依次分配方案, 生成最优方案集

        Args:
            sorted_cargo: 按优先级排序的受阻货物列表
            candidates_map: {cargo_id: [CandidatePlan, ...]}
            inventory: 资源清点结果
            cargo_map: {cargo_id: Cargo}
            vehicle_map: {vehicle_id: Vehicle}
        """
        solution = SolutionSet()

        for cargo in sorted_cargo:
            candidates = candidates_map.get(cargo.cargo_id, [])
            if not candidates:
                # 无候选方案, P1货物记为失败
                continue

            # 按成本排序候选方案
            for plan in candidates:
                vehicle = vehicle_map.get(plan.vehicle_id) if plan.vehicle_id else None
                self.cost_calc.calculate(plan, cargo, vehicle)
            candidates.sort(key=lambda p: p.total_cost)

            # 选择成本最低且可行的方案
            selected = self._select_best_feasible(candidates, cargo, inventory)

            if selected:
                solution.plans.append(selected)
                solution.total_cost += selected.total_cost
                solution.total_delay_hours += selected.delay_hours

                # 统计
                if selected.plan_type == ActionPlanType.REROUTE:
                    solution.cargo_delivered += 1
                elif selected.plan_type == ActionPlanType.WAREHOUSE_TRANSFER:
                    solution.cargo_stored += 1
                elif selected.plan_type == ActionPlanType.ABANDON:
                    solution.cargo_abandoned += 1

                # 消耗资源
                self._consume_resource(selected, cargo, inventory)

        # 统计车辆和仓库使用数
        used_vehicles = set()
        used_warehouses = set()
        for plan in solution.plans:
            if plan.vehicle_id:
                used_vehicles.add(plan.vehicle_id)
            if plan.warehouse_id:
                used_warehouses.add(plan.warehouse_id)
        solution.vehicles_used = len(used_vehicles)
        solution.warehouses_used = len(used_warehouses)
        solution.total_cost = round(solution.total_cost, 1)

        return solution

    def _select_best_feasible(self, candidates: list[CandidatePlan],
                               cargo: Cargo,
                               inventory: ResourceInventory) -> Optional[CandidatePlan]:
        """选择成本最低且可行的方案"""
        for plan in candidates:
            if not plan.feasibility:
                continue

            # P1货物不能放弃
            if plan.plan_type == ActionPlanType.ABANDON and cargo.is_p1:
                continue

            # 检查资源是否足够
            if plan.plan_type == ActionPlanType.REROUTE:
                av = inventory.find_vehicle(plan.vehicle_id)
                if not av or not av.vehicle.can_carry(cargo.weight_tons, cargo.volume_m3):
                    continue

            elif plan.plan_type == ActionPlanType.WAREHOUSE_TRANSFER:
                aw = inventory.find_warehouse(plan.warehouse_id)
                if not aw or aw.available_capacity < cargo.volume_m3:
                    continue

            return plan

        return None

    def _consume_resource(self, plan: CandidatePlan, cargo: Cargo,
                           inventory: ResourceInventory):
        """消耗资源"""
        if plan.plan_type == ActionPlanType.REROUTE and plan.vehicle_id:
            inventory.consume_vehicle(plan.vehicle_id, cargo.weight_tons, cargo.volume_m3)
        elif plan.plan_type == ActionPlanType.WAREHOUSE_TRANSFER and plan.warehouse_id:
            inventory.consume_warehouse(plan.warehouse_id, cargo.volume_m3)

    def generate_alternatives(self, sorted_cargo: list[Cargo],
                               candidates_map: dict[str, list[CandidatePlan]],
                               inventory: ResourceInventory,
                               cargo_map: dict[str, Cargo],
                               vehicle_map: dict[str, Vehicle]) -> list[SolutionSet]:
        """生成备选方案: 成本优先 + 时效优先"""
        alternatives = []

        # 成本优先: 放弃更多普通货物, 仅保障P1/P2
        cost_first = self._build_cost_first(sorted_cargo, candidates_map,
                                             inventory, cargo_map, vehicle_map)
        alternatives.append(cost_first)

        # 时效优先: 尽量改道, 不转仓不放弃
        time_first = self._build_time_first(sorted_cargo, candidates_map,
                                             inventory, cargo_map, vehicle_map)
        alternatives.append(time_first)

        return alternatives

    def _build_cost_first(self, sorted_cargo, candidates_map, inventory,
                           cargo_map, vehicle_map) -> SolutionSet:
        """成本优先方案: P3货物优先放弃"""
        solution = SolutionSet()

        for cargo in sorted_cargo:
            candidates = candidates_map.get(cargo.cargo_id, [])

            if cargo.can_be_abandoned:
                # P3直接放弃
                abandon_plan = CandidatePlan(
                    cargo_id=cargo.cargo_id,
                    plan_type=ActionPlanType.ABANDON,
                    description=f"成本优先: 放弃{cargo.cargo_id}",
                    value_loss=cargo.value_yuan,
                )
                self.cost_calc.calculate(abandon_plan, cargo, None)
                solution.plans.append(abandon_plan)
                solution.total_cost += abandon_plan.total_cost
                solution.cargo_abandoned += 1
            else:
                # P1/P2选最低成本
                for plan in candidates:
                    if plan.plan_type == ActionPlanType.ABANDON:
                        continue
                    vehicle = vehicle_map.get(plan.vehicle_id) if plan.vehicle_id else None
                    self.cost_calc.calculate(plan, cargo, vehicle)

                feasible = [p for p in candidates if p.feasibility and
                            p.plan_type != ActionPlanType.ABANDON]
                if feasible:
                    feasible.sort(key=lambda p: p.total_cost)
                    selected = feasible[0]
                    solution.plans.append(selected)
                    solution.total_cost += selected.total_cost
                    if selected.plan_type == ActionPlanType.REROUTE:
                        solution.cargo_delivered += 1
                    elif selected.plan_type == ActionPlanType.WAREHOUSE_TRANSFER:
                        solution.cargo_stored += 1
                    self._consume_resource(selected, cargo, inventory)

        used_v = set(p.vehicle_id for p in solution.plans if p.vehicle_id)
        used_w = set(p.warehouse_id for p in solution.plans if p.warehouse_id)
        solution.vehicles_used = len(used_v)
        solution.warehouses_used = len(used_w)
        solution.total_cost = round(solution.total_cost, 1)
        return solution

    def _build_time_first(self, sorted_cargo, candidates_map, inventory,
                           cargo_map, vehicle_map) -> SolutionSet:
        """时效优先方案: 尽量改道送达"""
        solution = SolutionSet()

        for cargo in sorted_cargo:
            candidates = candidates_map.get(cargo.cargo_id, [])

            # 优先选改道方案(时效最快)
            reroute_plans = [p for p in candidates
                             if p.plan_type == ActionPlanType.REROUTE and p.feasibility]
            if reroute_plans:
                for p in reroute_plans:
                    vehicle = vehicle_map.get(p.vehicle_id) if p.vehicle_id else None
                    self.cost_calc.calculate(p, cargo, vehicle)
                reroute_plans.sort(key=lambda p: p.route_time_min)
                selected = reroute_plans[0]
                solution.plans.append(selected)
                solution.total_cost += selected.total_cost
                solution.cargo_delivered += 1
                self._consume_resource(selected, cargo, inventory)
            else:
                # 次选转仓
                transfer_plans = [p for p in candidates
                                  if p.plan_type == ActionPlanType.WAREHOUSE_TRANSFER and p.feasibility]
                if transfer_plans:
                    for p in transfer_plans:
                        self.cost_calc.calculate(p, cargo, None)
                    transfer_plans.sort(key=lambda p: p.total_cost)
                    selected = transfer_plans[0]
                    solution.plans.append(selected)
                    solution.total_cost += selected.total_cost
                    solution.cargo_stored += 1
                    self._consume_resource(selected, cargo, inventory)
                elif cargo.can_be_abandoned:
                    abandon = CandidatePlan(
                        cargo_id=cargo.cargo_id,
                        plan_type=ActionPlanType.ABANDON,
                        description=f"时效优先: 无法送达, 放弃{cargo.cargo_id}",
                        value_loss=cargo.value_yuan,
                    )
                    self.cost_calc.calculate(abandon, cargo, None)
                    solution.plans.append(abandon)
                    solution.total_cost += abandon.total_cost
                    solution.cargo_abandoned += 1

        used_v = set(p.vehicle_id for p in solution.plans if p.vehicle_id)
        used_w = set(p.warehouse_id for p in solution.plans if p.warehouse_id)
        solution.vehicles_used = len(used_v)
        solution.warehouses_used = len(used_w)
        solution.total_cost = round(solution.total_cost, 1)
        return solution
