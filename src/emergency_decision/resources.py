"""
可用资源清点 - Step 3
对应文档: 03-calculation-logic.md Step 3

功能:
  - 筛选可调度车辆池
  - 筛选可用仓库池
  - 构建灾后路网状态 (中断路段移除)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    LogisticsNetwork,
    Road,
    Vehicle,
    VehicleStatus,
    Warehouse,
    WarehouseDamage,
)
from .disaster_impact import DisasterImpactResult


@dataclass
class AvailableVehicle:
    """可调度车辆"""
    vehicle: Vehicle
    available_tons: float
    available_m3: float
    needs_reroute: bool = False


@dataclass
class AvailableWarehouse:
    """可用仓库"""
    warehouse: Warehouse
    available_capacity: float
    is_damaged: bool = False


@dataclass
class ResourceInventory:
    """资源清点结果"""
    available_vehicles: list[AvailableVehicle] = field(default_factory=list)
    available_warehouses: list[AvailableWarehouse] = field(default_factory=list)
    passable_roads: list[Road] = field(default_factory=list)
    blocked_road_ids: list[str] = field(default_factory=list)

    @property
    def vehicle_count(self) -> int:
        return len(self.available_vehicles)

    @property
    def warehouse_count(self) -> int:
        return len(self.available_warehouses)

    @property
    def total_available_tons(self) -> float:
        return sum(v.available_tons for v in self.available_vehicles)

    @property
    def total_available_m3(self) -> float:
        return sum(v.available_m3 for v in self.available_vehicles)

    def consume_vehicle(self, vehicle_id: str, tons: float, m3: float):
        """消耗车辆运力"""
        for av in self.available_vehicles:
            if av.vehicle.vehicle_id == vehicle_id:
                av.available_tons = max(0, av.available_tons - tons)
                av.available_m3 = max(0, av.available_m3 - m3)
                break

    def consume_warehouse(self, warehouse_id: str, volume: float):
        """消耗仓库容量"""
        for aw in self.available_warehouses:
            if aw.warehouse.warehouse_id == warehouse_id:
                aw.available_capacity = max(0, aw.available_capacity - volume)
                break

    def find_vehicle(self, vehicle_id: str) -> AvailableVehicle | None:
        for av in self.available_vehicles:
            if av.vehicle.vehicle_id == vehicle_id:
                return av
        return None

    def find_warehouse(self, warehouse_id: str) -> AvailableWarehouse | None:
        for aw in self.available_warehouses:
            if aw.warehouse.warehouse_id == warehouse_id:
                return aw
        return None

    def find_nearest_warehouse(self, lat: float, lng: float,
                                volume_needed: float) -> AvailableWarehouse | None:
        """找最近的有容量的可用仓库"""
        from .geo import haversine_distance
        candidates = [aw for aw in self.available_warehouses
                       if aw.available_capacity >= volume_needed]
        if not candidates:
            return None
        candidates.sort(key=lambda aw: haversine_distance(
            lat, lng, aw.warehouse.lat, aw.warehouse.lng))
        return candidates[0] if candidates else None


class ResourceInventoryChecker:
    """资源清点器"""

    def __init__(self, network: LogisticsNetwork):
        self.network = network

    def check(self, vehicles: list[Vehicle],
              warehouses: list[Warehouse],
              impact: DisasterImpactResult) -> ResourceInventory:
        """执行资源清点"""
        inventory = ResourceInventory()

        # 1. 筛选可调度车辆
        reroute_set = set(impact.reroute_needed_vehicle_ids)
        for v in vehicles:
            if not v.is_dispatchable:
                continue
            av = AvailableVehicle(
                vehicle=v,
                available_tons=v.remaining_capacity_tons,
                available_m3=v.remaining_capacity_m3,
                needs_reroute=v.vehicle_id in reroute_set,
            )
            inventory.available_vehicles.append(av)

        # 2. 筛选可用仓库
        damaged_set = set(impact.damaged_warehouse_ids)
        closed_set = set(impact.closed_warehouse_ids)
        for wh in warehouses:
            if wh.warehouse_id in closed_set:
                continue
            if wh.damage_status == WarehouseDamage.CLOSED:
                continue
            aw = AvailableWarehouse(
                warehouse=wh,
                available_capacity=wh.available_capacity_m3,
                is_damaged=wh.warehouse_id in damaged_set,
            )
            inventory.available_warehouses.append(aw)

        # 3. 构建灾后路网
        blocked_set = set(impact.blocked_road_ids)
        for road in self.network.roads:
            if road.road_id not in blocked_set:
                inventory.passable_roads.append(road)
            else:
                inventory.blocked_road_ids.append(road.road_id)

        return inventory
