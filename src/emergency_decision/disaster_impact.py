"""
灾害影响分析 - Step 1
对应文档: 03-calculation-logic.md Step 1

功能:
  - 计算灾害波及范围
  - 标记受影响路段(风险评分、延迟系数、影响类型)
  - 标记受困车辆、受阻货物、受损仓库
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .geo import haversine_distance
from .models import (
    AffectedType,
    Cargo,
    CargoStatus,
    Disaster,
    DisasterType,
    LogisticsNetwork,
    Road,
    Vehicle,
    Warehouse,
    WarehouseDamage,
)


@dataclass
class DisasterImpactResult:
    """灾害影响分析结果"""
    affected_roads: list[Road] = field(default_factory=list)
    blocked_road_ids: list[str] = field(default_factory=list)
    restricted_road_ids: list[str] = field(default_factory=list)
    slow_road_ids: list[str] = field(default_factory=list)

    trapped_vehicle_ids: list[str] = field(default_factory=list)
    reroute_needed_vehicle_ids: list[str] = field(default_factory=list)

    blocked_cargo_ids: list[str] = field(default_factory=list)
    destination_restricted_cargo_ids: list[str] = field(default_factory=list)

    damaged_warehouse_ids: list[str] = field(default_factory=list)
    closed_warehouse_ids: list[str] = field(default_factory=list)

    @property
    def total_affected_roads(self) -> int:
        return len(self.affected_roads)

    @property
    def total_affected_cargo(self) -> int:
        return len(self.blocked_cargo_ids) + len(self.destination_restricted_cargo_ids)

    def summary(self) -> str:
        lines = [
            f"受影响路段: {self.total_affected_roads} 条 "
            f"(中断{len(self.blocked_road_ids)}, 限行{len(self.restricted_road_ids)}, "
            f"减速{len(self.slow_road_ids)})",
            f"受困车辆: {len(self.trapped_vehicle_ids)} 辆",
            f"需改道车辆: {len(self.reroute_needed_vehicle_ids)} 辆",
            f"受阻货物: {len(self.blocked_cargo_ids)} 单",
            f"目的受限货物: {len(self.destination_restricted_cargo_ids)} 单",
            f"受损仓库: {len(self.damaged_warehouse_ids)} 个",
            f"关闭仓库: {len(self.closed_warehouse_ids)} 个",
        ]
        return "\n".join(lines)


class DisasterImpactAnalyzer:
    """灾害影响分析器"""

    def __init__(self, network: LogisticsNetwork):
        self.network = network
        self._node_map: dict[str, object] = {}
        for n in network.nodes:
            self._node_map[n.node_id] = n

    def analyze(self, disaster: Disaster,
                vehicles: list[Vehicle],
                cargo_list: list[Cargo],
                warehouses: list[Warehouse]) -> DisasterImpactResult:
        """执行灾害影响分析, 返回结果"""
        result = DisasterImpactResult()

        # 1. 标记受影响路段
        self._mark_roads(disaster, result)

        # 2. 标记受影响车辆
        self._mark_vehicles(disaster, result, vehicles)

        # 3. 标记受影响货物
        self._mark_cargo(disaster, result, cargo_list)

        # 4. 标记受影响仓库
        self._mark_warehouses(disaster, result, warehouses)

        return result

    def _mark_roads(self, disaster: Disaster, result: DisasterImpactResult):
        """标记受影响路段"""
        center_lat = disaster.center_lat
        center_lng = disaster.center_lng
        radius = disaster.influence_radius_km

        for road in self.network.roads:
            # 计算路段中点到震中的距离
            mid_lat = road.midpoint_lat(self._node_map)
            mid_lng = road.midpoint_lng(self._node_map)
            dist = haversine_distance(mid_lat, mid_lng, center_lat, center_lng)

            if dist > radius:
                continue  # 不受影响

            result.affected_roads.append(road)

            # 按灾害类型标记
            if disaster.disaster_type == DisasterType.EARTHQUAKE:
                self._mark_earthquake_road(road, dist, radius, disaster.disaster_id)
            elif disaster.disaster_type == DisasterType.RAINSTORM:
                self._mark_rainstorm_road(road, disaster, disaster.disaster_id)
            elif disaster.disaster_type == DisasterType.TYPHOON:
                self._mark_typhoon_road(road, dist, radius, disaster.disaster_id)
            elif disaster.disaster_type in (DisasterType.LANDSLIDE,
                                             DisasterType.MUDSLIDE,
                                             DisasterType.FLOOD):
                self._mark_landslide_road(road, disaster, disaster.disaster_id)
            elif disaster.disaster_type == DisasterType.SNOWSTORM:
                self._mark_snowstorm_road(road, dist, radius, disaster.disaster_id)
            elif disaster.disaster_type == DisasterType.SANDSTORM:
                self._mark_sandstorm_road(road, dist, radius, disaster.disaster_id)
            elif disaster.disaster_type == DisasterType.WILDFIRE:
                self._mark_wildfire_road(road, dist, radius, disaster.disaster_id)
            elif disaster.disaster_type == DisasterType.TSUNAMI:
                self._mark_tsunami_road(road, dist, radius, disaster.disaster_id)
            else:
                # 未匹配类型的通用回退处理
                self._mark_generic_road(road, dist, radius, disaster.disaster_id)

            # 归类
            if road.affected_type == AffectedType.BLOCKED:
                result.blocked_road_ids.append(road.road_id)
            elif road.affected_type == AffectedType.RESTRICTED:
                result.restricted_road_ids.append(road.road_id)
            elif road.affected_type == AffectedType.SLOW:
                result.slow_road_ids.append(road.road_id)

    def _mark_earthquake_road(self, road: Road, dist: float,
                               radius: float, disaster_id: str):
        """地震影响标记"""
        ratio = dist / radius if radius > 0 else 1.0

        if ratio <= 0.3:
            # 极近: 高风险
            road.risk_score = max(0.8, 1.0 - ratio)
            road.delay_factor = 3.0
            if road.has_bridge and road.risk_score > 0.6:
                road.affected_type = AffectedType.BLOCKED
                road.estimated_recovery_hours = 24.0
            else:
                road.affected_type = AffectedType.RESTRICTED
        elif ratio <= 0.6:
            # 中近: 中风险
            road.risk_score = max(0.4, 0.8 - (ratio - 0.3))
            road.delay_factor = 2.0
            road.affected_type = AffectedType.RESTRICTED
        else:
            # 远: 低风险
            road.risk_score = max(0.0, 0.4 - (ratio - 0.6))
            road.delay_factor = 1.5
            road.affected_type = AffectedType.SLOW

        road.disaster_affected = True
        road.affected_by_disaster = disaster_id

    def _mark_rainstorm_road(self, road: Road, disaster: Disaster,
                              disaster_id: str):
        """暴雨影响标记"""
        # 检查场景预置的积水路段数据(兼容字符串ID和字典格式)
        waterlogged_ids: set = set()
        waterlogged_details: dict = {}
        if disaster.rainstorm and disaster.rainstorm.waterlogged_roads:
            for wr in disaster.rainstorm.waterlogged_roads:
                if isinstance(wr, str):
                    waterlogged_ids.add(wr)
                elif isinstance(wr, dict):
                    rid = wr.get("road_id", "")
                    if rid:
                        waterlogged_ids.add(rid)
                        waterlogged_details[rid] = wr

        # 检查场景预置的中断状态
        if road.road_condition.value == "blocked":
            road.risk_score = 1.0
            road.delay_factor = float('inf')
            road.affected_type = AffectedType.BLOCKED
            road.estimated_recovery_hours = 24.0
        elif road.road_id in waterlogged_ids:
            wr_detail = waterlogged_details.get(road.road_id, {})
            water_depth = wr_detail.get("water_depth_cm", 50) if isinstance(wr_detail, dict) else 50
            is_passable = wr_detail.get("passable", False) if isinstance(wr_detail, dict) else False
            if not is_passable or water_depth >= 50:
                road.risk_score = 0.9
                road.delay_factor = float('inf')
                road.affected_type = AffectedType.BLOCKED
                road.estimated_recovery_hours = 12.0
            else:
                road.risk_score = 0.6
                road.delay_factor = 3.0
                road.affected_type = AffectedType.RESTRICTED
        elif road.road_condition.value in ("congested",):
            road.risk_score = 0.6
            road.delay_factor = 2.5
            road.affected_type = AffectedType.RESTRICTED
        else:
            road.risk_score = 0.4
            road.delay_factor = 1.8
            road.affected_type = AffectedType.SLOW

        road.disaster_affected = True
        road.affected_by_disaster = disaster_id

    def _mark_typhoon_road(self, road: Road, dist: float,
                            radius: float, disaster_id: str):
        """台风影响标记"""
        ratio = dist / radius if radius > 0 else 1.0
        road.risk_score = max(0.3, 0.8 - ratio * 0.5)
        road.delay_factor = 2.0

        if road.road_type.value in ("highway",) and road.has_bridge:
            road.affected_type = AffectedType.BLOCKED
        else:
            road.affected_type = AffectedType.RESTRICTED

        road.disaster_affected = True
        road.affected_by_disaster = disaster_id

    def _mark_landslide_road(self, road: Road, disaster: Disaster,
                              disaster_id: str):
        """滑坡/泥石流影响标记"""
        blocked_ids = []
        if disaster.landslide and disaster.landslide.blocked_roads:
            blocked_ids = disaster.landslide.blocked_roads

        if road.road_id in blocked_ids:
            road.affected_type = AffectedType.BLOCKED
            road.risk_score = 1.0
            road.delay_factor = float('inf')
            road.estimated_recovery_hours = disaster.landslide.estimated_clear_hours
        else:
            road.affected_type = AffectedType.SLOW
            road.risk_score = 0.3
            road.delay_factor = 1.5

        road.disaster_affected = True
        road.affected_by_disaster = disaster_id

    def _mark_vehicles(self, disaster: Disaster, result: DisasterImpactResult,
                        vehicles: list[Vehicle]):
        """标记受影响车辆"""
        center_lat = disaster.center_lat
        center_lng = disaster.center_lng
        radius = disaster.influence_radius_km

        for vehicle in vehicles:
            if vehicle.status.value != "in_transit":
                continue

            # 判断车辆是否在灾区
            dist = haversine_distance(vehicle.current_lat, vehicle.current_lng,
                                       center_lat, center_lng)
            if dist <= radius * 0.3:
                result.trapped_vehicle_ids.append(vehicle.vehicle_id)
                continue

            # 判断原计划路线是否经过中断路段
            if self._route_blocked(vehicle, result):
                result.reroute_needed_vehicle_ids.append(vehicle.vehicle_id)

    def _route_blocked(self, vehicle: Vehicle, result: DisasterImpactResult) -> bool:
        """检查车辆路线是否经过中断路段 (简化: 检查当前节点相邻路段)"""
        blocked_set = set(result.blocked_road_ids)
        neighbors = self.network.get_neighbors(vehicle.current_location_node)
        for _, road in neighbors:
            if road.road_id in blocked_set:
                return True
        return False

    def _mark_cargo(self, disaster: Disaster, result: DisasterImpactResult,
                     cargo_list: list[Cargo]):
        """标记受影响货物"""
        blocked_set = set(result.blocked_road_ids)

        for cargo in cargo_list:
            # 检查所有待运和在途货物的路线是否经过中断路段
            if cargo.current_status in (CargoStatus.IN_TRANSIT, CargoStatus.PENDING):
                if cargo.planned_route:
                    for i in range(len(cargo.planned_route) - 1):
                        for road in self.network.roads:
                            # 检查正向和反向(双向路)
                            if ((road.from_node == cargo.planned_route[i] and
                                 road.to_node == cargo.planned_route[i + 1]) or
                                (road.is_bidirectional and
                                 road.to_node == cargo.planned_route[i] and
                                 road.from_node == cargo.planned_route[i + 1])):
                                if road.road_id in blocked_set:
                                    cargo.is_blocked = True
                                    if cargo.cargo_id not in result.blocked_cargo_ids:
                                        result.blocked_cargo_ids.append(cargo.cargo_id)
                                    break
                        if cargo.is_blocked:
                            break

            # 检查目的地是否在灾区
            if cargo.destination_lat and cargo.destination_lng:
                dist = haversine_distance(cargo.destination_lat, cargo.destination_lng,
                                           disaster.center_lat, disaster.center_lng)
                if dist <= disaster.influence_radius_km:
                    cargo.is_destination_restricted = True
                    if cargo.cargo_id not in result.destination_restricted_cargo_ids:
                        result.destination_restricted_cargo_ids.append(cargo.cargo_id)

    def _mark_warehouses(self, disaster: Disaster, result: DisasterImpactResult,
                          warehouses: list[Warehouse]):
        """标记受影响仓库"""
        center_lat = disaster.center_lat
        center_lng = disaster.center_lng
        radius = disaster.influence_radius_km

        for wh in warehouses:
            dist = haversine_distance(wh.lat, wh.lng, center_lat, center_lng)

            if dist > radius:
                continue

            ratio = dist / radius if radius > 0 else 1.0

            if ratio <= 0.3:
                wh.damage_status = WarehouseDamage.DAMAGED
                wh.estimated_recovery_hours = 12.0
                result.damaged_warehouse_ids.append(wh.warehouse_id)
            elif ratio <= 0.6:
                wh.damage_status = WarehouseDamage.DAMAGED
                wh.estimated_recovery_hours = 6.0
                result.damaged_warehouse_ids.append(wh.warehouse_id)
            # else: normal, 不标记

    def _mark_snowstorm_road(self, road: Road, dist: float,
                              radius: float, disaster_id: str):
        """暴雪影响标记"""
        ratio = dist / radius if radius > 0 else 1.0
        road.risk_score = max(0.3, 0.85 - ratio * 0.5)
        # 暴雪：道路结冰风险高，视距离影响程度标记
        if ratio <= 0.3:
            road.affected_type = AffectedType.BLOCKED
            road.delay_factor = float('inf')
            road.estimated_recovery_hours = 36.0
        elif ratio <= 0.5:
            road.affected_type = AffectedType.RESTRICTED
            road.delay_factor = 3.0
        else:
            road.affected_type = AffectedType.SLOW
            road.delay_factor = 2.0
        road.disaster_affected = True
        road.affected_by_disaster = disaster_id

    def _mark_sandstorm_road(self, road: Road, dist: float,
                              radius: float, disaster_id: str):
        """沙尘暴影响标记"""
        ratio = dist / radius if radius > 0 else 1.0
        road.risk_score = max(0.2, 0.7 - ratio * 0.4)
        # 沙尘暴：能见度极低，所有受影响道路限行
        if ratio <= 0.4:
            road.affected_type = AffectedType.BLOCKED
            road.delay_factor = float('inf')
            road.estimated_recovery_hours = 12.0
        else:
            road.affected_type = AffectedType.RESTRICTED
            road.delay_factor = 2.5
        road.disaster_affected = True
        road.affected_by_disaster = disaster_id

    def _mark_wildfire_road(self, road: Road, dist: float,
                             radius: float, disaster_id: str):
        """森林火灾影响标记"""
        ratio = dist / radius if radius > 0 else 1.0
        road.risk_score = max(0.3, 0.9 - ratio * 0.6)
        # 火灾：近距离完全阻断，稍远限行
        if ratio <= 0.2:
            road.affected_type = AffectedType.BLOCKED
            road.delay_factor = float('inf')
            road.estimated_recovery_hours = 48.0
        elif ratio <= 0.5:
            road.affected_type = AffectedType.RESTRICTED
            road.delay_factor = 3.0
        else:
            road.affected_type = AffectedType.SLOW
            road.delay_factor = 1.8
        road.disaster_affected = True
        road.affected_by_disaster = disaster_id

    def _mark_tsunami_road(self, road: Road, dist: float,
                            radius: float, disaster_id: str):
        """海啸影响标记"""
        ratio = dist / radius if radius > 0 else 1.0
        road.risk_score = max(0.4, 0.95 - ratio * 0.5)
        # 海啸：近海路段完全冲毁
        if ratio <= 0.3:
            road.affected_type = AffectedType.BLOCKED
            road.delay_factor = float('inf')
            road.estimated_recovery_hours = 72.0
        elif ratio <= 0.6:
            road.affected_type = AffectedType.RESTRICTED
            road.delay_factor = 4.0
        else:
            road.affected_type = AffectedType.SLOW
            road.delay_factor = 2.0
        road.disaster_affected = True
        road.affected_by_disaster = disaster_id

    def _mark_generic_road(self, road: Road, dist: float,
                            radius: float, disaster_id: str):
        """通用灾害回退标记 - 未明确匹配的灾害类型"""
        ratio = dist / radius if radius > 0 else 1.0
        road.risk_score = max(0.2, 0.7 - ratio * 0.5)
        # 通用规则：根据距离分级标记
        if ratio <= 0.3:
            road.affected_type = AffectedType.BLOCKED
            road.delay_factor = float('inf')
            road.estimated_recovery_hours = 24.0
        elif ratio <= 0.6:
            road.affected_type = AffectedType.RESTRICTED
            road.delay_factor = 2.5
        else:
            road.affected_type = AffectedType.SLOW
            road.delay_factor = 1.5
        road.disaster_affected = True
        road.affected_by_disaster = disaster_id
