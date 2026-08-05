"""
成本计算 - Step 5
对应文档: 03-calculation-logic.md Step 5

成本构成:
  方案总成本 = 运输成本 + 仓储成本 + 违约成本 + 货物损失成本 + 风险成本
"""

from __future__ import annotations

from .models import Cargo, Vehicle
from .plan_generator import CandidatePlan


class CostCalculator:
    """成本计算器"""

    RISK_WEIGHT = 0.1  # 风险成本权重

    def calculate(self, plan: CandidatePlan, cargo: Cargo,
                  vehicle: Vehicle | None = None) -> float:
        """计算候选方案的总成本"""
        transport_cost = self._calc_transport(plan, vehicle)
        storage_cost = plan.storage_cost
        penalty_cost = self._calc_penalty(plan, cargo)
        abandon_cost = plan.value_loss
        risk_cost = self._calc_risk(plan, cargo)

        total = transport_cost + storage_cost + penalty_cost + abandon_cost + risk_cost
        plan.total_cost = round(total, 1)
        return plan.total_cost

    def _calc_transport(self, plan: CandidatePlan,
                         vehicle: Vehicle | None) -> float:
        """运输成本 = 里程 × 油耗/公里 + 过路费"""
        if plan.plan_type.value == "abandon":
            return 0.0

        if not vehicle:
            return 0.0

        fuel = plan.route_distance_km * vehicle.cost_per_km
        return round(fuel + plan.toll_cost, 1)

    def _calc_penalty(self, plan: CandidatePlan, cargo: Cargo) -> float:
        """违约成本 = max(0, 超时小时) × 每小时违约金"""
        if plan.plan_type.value == "abandon":
            return 0.0

        # 估算送达时间 (分钟转小时)
        estimated_arrival_hours = plan.route_time_min / 60.0
        # 简化: 假设deadline为24小时, 当前已用时间未计入
        deadline_hours = cargo.deadline_urgency_hours

        if estimated_arrival_hours > deadline_hours:
            delay = estimated_arrival_hours - deadline_hours
            plan.delay_hours = round(delay, 1)
            return round(delay * cargo.contract_penalty_per_hour, 1)

        return 0.0

    def _calc_risk(self, plan: CandidatePlan, cargo: Cargo) -> float:
        """风险成本 = Σ risk_score × 风险权重 × 货物价值"""
        return round(plan.route_risk * self.RISK_WEIGHT * cargo.value_yuan, 1)

    def calc_plan_set_cost(self, plans: list[CandidatePlan],
                            cargo_map: dict[str, Cargo],
                            vehicle_map: dict[str, Vehicle]) -> float:
        """计算一组方案的总成本"""
        total = 0.0
        for plan in plans:
            cargo = cargo_map.get(plan.cargo_id)
            vehicle = vehicle_map.get(plan.vehicle_id) if plan.vehicle_id else None
            if cargo:
                total += self.calculate(plan, cargo, vehicle)
        return round(total, 1)
