"""
方案生成 - Step 4
对应文档: 03-calculation-logic.md Step 4

为每件受阻货物生成三类候选方案:
  - 改道(reroute): 车辆变更路线绕过中断路段
  - 就近转仓(warehouse_transfer): 货物转存至最近可用仓库
  - 放弃配送(abandon): 仅限P3货物
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import (
    Action,
    ActionPlanType,
    Cargo,
    LogisticsNetwork,
    Vehicle,
    Warehouse,
)
from .geo import haversine_distance
from .resources import AvailableVehicle, ResourceInventory
from .route_finder import PathResult, RouteFinder


@dataclass
class CandidatePlan:
    """候选方案"""
    cargo_id: str
    plan_type: ActionPlanType
    description: str
    vehicle_id: str = ""
    warehouse_id: str = ""
    route: list[str] = field(default_factory=list)
    route_distance_km: float = 0.0
    route_time_min: float = 0.0
    route_risk: float = 0.0
    toll_cost: float = 0.0
    storage_cost: float = 0.0
    storage_duration_hours: float = 0.0
    value_loss: float = 0.0
    feasibility: bool = True
    reason: str = ""
    # 成本明细 (由CostCalculator填充)
    total_cost: float = 0.0
    delay_hours: float = 0.0

    def to_action(self, action_id: str) -> Action:
        return Action(
            action_id=action_id,
            action_type=self.plan_type,
            description=self.description,
            cargo_ids=[self.cargo_id],
            vehicle_id=self.vehicle_id,
            new_route=self.route,
            warehouse_id=self.warehouse_id,
            extra_cost=round(self.total_cost, 1),
            extra_time_min=round(self.route_time_min, 1),
            risk_score=self.route_risk,
            storage_cost=round(self.storage_cost, 1),
            storage_duration_hours=self.storage_duration_hours,
            value_loss=self.value_loss,
            reason=self.reason,
        )


class PlanGenerator:
    """方案生成器"""

    def __init__(self, network: LogisticsNetwork):
        self.network = network
        self.route_finder = RouteFinder(network)

    def generate_candidates(self, cargo: Cargo,
                             inventory: ResourceInventory) -> list[CandidatePlan]:
        """为一件受阻货物生成所有候选方案"""
        candidates = []

        # 1. 改道方案
        reroute = self._try_reroute(cargo, inventory)
        if reroute:
            candidates.append(reroute)

        # 2. 就近转仓方案
        transfer = self._try_warehouse_transfer(cargo, inventory)
        if transfer:
            candidates.append(transfer)

        # 3. 放弃方案 (仅P3)
        if cargo.can_be_abandoned:
            abandon = CandidatePlan(
                cargo_id=cargo.cargo_id,
                plan_type=ActionPlanType.ABANDON,
                description=f"放弃货物 {cargo.cargo_id} ({cargo.description})",
                value_loss=cargo.value_yuan,
                reason="资源不足, 放弃低优先级货物",
            )
            candidates.append(abandon)

        return candidates

    def _try_reroute(self, cargo: Cargo,
                     inventory: ResourceInventory) -> Optional[CandidatePlan]:
        """尝试生成改道方案"""
        # 找当前车辆位置或货物当前位置
        start_node = cargo.current_location_node or cargo.origin_node
        end_node = cargo.destination_node

        if not start_node or not end_node:
            return None

        # 在灾后路网中搜索可达路径
        path = self.route_finder.find_shortest_path(start_node, end_node, "cost")

        if not path.is_valid:
            return None

        # 找一辆有运力的车
        vehicle = self._find_vehicle(cargo, inventory)
        if not vehicle:
            return None

        return CandidatePlan(
            cargo_id=cargo.cargo_id,
            plan_type=ActionPlanType.REROUTE,
            description=f"货物{cargo.cargo_id}改道: {' → '.join(path.route[:4])}{'...' if len(path.route)>4 else ''}",
            vehicle_id=vehicle.vehicle.vehicle_id,
            route=path.route,
            route_distance_km=path.total_distance_km,
            route_time_min=path.total_time_min,
            route_risk=path.total_risk,
            toll_cost=path.total_toll_cost,
            reason=f"原路线中断, 绕行{path.total_distance_km}km",
        )

    def _try_warehouse_transfer(self, cargo: Cargo,
                                  inventory: ResourceInventory) -> Optional[CandidatePlan]:
        """尝试生成就近转仓方案"""
        start_node = cargo.current_location_node or cargo.origin_node
        start_node_obj = self.network.get_node(start_node)
        if not start_node_obj:
            return None

        # 找最近的有容量的仓库
        aw = inventory.find_nearest_warehouse(
            start_node_obj.lat, start_node_obj.lng, cargo.volume_m3)

        if not aw:
            return None

        wh = aw.warehouse
        # 估算仓储时间 (灾后恢复时间)
        storage_hours = 24.0
        storage_cost = cargo.volume_m3 * wh.storage_cost_per_m3_per_day * (storage_hours / 24)

        return CandidatePlan(
            cargo_id=cargo.cargo_id,
            plan_type=ActionPlanType.WAREHOUSE_TRANSFER,
            description=f"货物{cargo.cargo_id}就近转存至{wh.warehouse_name}",
            warehouse_id=wh.warehouse_id,
            storage_cost=round(storage_cost, 1),
            storage_duration_hours=storage_hours,
            route=[start_node, wh.node_id],
            route_risk=0.0,
            reason=f"路线不可达, 转存{wh.city}仓库待灾后配送",
        )

    def _find_vehicle(self, cargo: Cargo,
                      inventory: ResourceInventory) -> Optional[AvailableVehicle]:
        """为货物找一辆有运力的可调度车辆"""
        # 优先找原有分配的车辆
        if cargo.assigned_vehicle_id:
            av = inventory.find_vehicle(cargo.assigned_vehicle_id)
            if av and av.vehicle.can_carry(cargo.weight_tons, cargo.volume_m3):
                return av

        # 找任意可用的空闲车辆
        for av in inventory.available_vehicles:
            if av.vehicle.can_carry(cargo.weight_tons, cargo.volume_m3):
                return av

        return None
