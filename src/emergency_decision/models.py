"""
数据模型层 - 定义系统所有核心数据结构
对应文档: 02-basic-data-requirements.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ============================================================
# 枚举定义
# ============================================================

class DisasterType(str, Enum):
    EARTHQUAKE = "earthquake"
    RAINSTORM = "rainstorm"
    TYPHOON = "typhoon"
    LANDSLIDE = "landslide"
    MUDSLIDE = "mudslide"
    FLOOD = "flood"
    SNOWSTORM = "snowstorm"
    SANDSTORM = "sandstorm"
    WILDFIRE = "wildfire"
    TSUNAMI = "tsunami"


class VehicleType(str, Enum):
    BOX_TRUCK = "box_truck"
    FLATBED = "flatbed"
    REFRIGERATED = "refrigerated"
    CONTAINER = "container"


class VehicleStatus(str, Enum):
    IDLE = "idle"
    IN_TRANSIT = "in_transit"
    LOADING = "loading"
    MAINTENANCE = "maintenance"


class WarehouseDamage(str, Enum):
    NORMAL = "normal"
    DAMAGED = "damaged"
    CLOSED = "closed"


class CargoType(str, Enum):
    MEDICAL = "medical"
    SUPPLIES = "supplies"
    URGENT = "urgent"
    NORMAL = "normal"
    HAZARDOUS = "hazardous"
    PERISHABLE = "perishable"


class PriorityLevel(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CargoStatus(str, Enum):
    PENDING = "pending"
    LOADING = "loading"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"


class RoadType(str, Enum):
    HIGHWAY = "highway"
    NATIONAL = "national"
    PROVINCIAL = "provincial"
    CITY_ROAD = "city_road"
    COUNTY = "county"


class RoadCondition(str, Enum):
    CLEAR = "clear"
    SLOW = "slow"
    CONGESTED = "congested"
    BLOCKED = "blocked"


class AffectedType(str, Enum):
    BLOCKED = "blocked"
    RESTRICTED = "restricted"
    SLOW = "slow"
    UNAFFECTED = "unaffected"


class CustomerType(str, Enum):
    HOSPITAL = "hospital"
    SUPERMARKET = "supermarket"
    ENTERPRISE = "enterprise"
    INDIVIDUAL = "individual"
    GOVERNMENT = "government"


class NodeType(str, Enum):
    DEPOT = "depot"
    WAREHOUSE = "warehouse"
    CUSTOMER_POINT = "customer_point"
    JUNCTION = "junction"
    TRANSFER_CENTER = "transfer_center"


class ActionPlanType(str, Enum):
    REROUTE = "reroute"
    WAREHOUSE_TRANSFER = "warehouse_transfer"
    ABANDON = "abandon"
    DELAY = "delay"
    HOLD = "hold"


class StrategyMode(str, Enum):
    TIME_PRESSURE = "time_pressure"
    AGENT_ADVERSARIAL = "agent_adversarial"
    BUDGET_CONSTRAINED = "budget_constrained"
    EMERGENCY_RELIEF = "emergency_relief"


# ============================================================
# 地理与网络模型
# ============================================================

@dataclass
class GeoPoint:
    lat: float
    lng: float


@dataclass
class NetworkNode:
    node_id: str
    node_name: str
    node_type: NodeType
    city: str
    lat: float
    lng: float
    connected_road_ids: list[str] = field(default_factory=list)


@dataclass
class Road:
    road_id: str
    road_name: str
    road_type: RoadType
    from_node: str
    to_node: str
    is_bidirectional: bool
    distance_km: float
    speed_limit_kmh: float
    current_travel_time_min: float
    road_condition: RoadCondition
    has_bridge: bool = False
    has_tunnel: bool = False
    capacity_per_hour: int = 2000
    toll_cost: float = 0.0
    fuel_cost_per_km: float = 0.8

    # 灾害影响标记 (由 DisasterImpactAnalyzer 填充)
    disaster_affected: bool = False
    affected_type: AffectedType = AffectedType.UNAFFECTED
    delay_factor: float = 1.0
    estimated_recovery_hours: float = 0.0
    risk_score: float = 0.0
    affected_by_disaster: str = ""

    @property
    def normal_travel_time_min(self) -> float:
        if self.speed_limit_kmh <= 0:
            return self.distance_km * 2  # 默认30km/h
        return round(self.distance_km / self.speed_limit_kmh * 60, 1)

    @property
    def actual_travel_time_min(self) -> float:
        """灾后实际通行时间"""
        if self.affected_type == AffectedType.BLOCKED:
            return float('inf')
        return round(self.current_travel_time_min * self.delay_factor, 1)

    @property
    def is_passable(self) -> bool:
        return self.affected_type != AffectedType.BLOCKED

    def midpoint_lat(self, nodes: dict[str, NetworkNode]) -> float:
        from_node = nodes.get(self.from_node)
        to_node = nodes.get(self.to_node)
        if from_node and to_node:
            return (from_node.lat + to_node.lat) / 2
        return 0.0

    def midpoint_lng(self, nodes: dict[str, NetworkNode]) -> float:
        from_node = nodes.get(self.from_node)
        to_node = nodes.get(self.to_node)
        if from_node and to_node:
            return (from_node.lng + to_node.lng) / 2
        return 0.0


@dataclass
class LogisticsNetwork:
    nodes: list[NetworkNode] = field(default_factory=list)
    roads: list[Road] = field(default_factory=list)

    def get_node(self, node_id: str) -> Optional[NetworkNode]:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None

    def get_road(self, road_id: str) -> Optional[Road]:
        for r in self.roads:
            if r.road_id == road_id:
                return r
        return None

    def get_roads_from(self, node_id: str) -> list[Road]:
        result = []
        for r in self.roads:
            if r.from_node == node_id and r.is_passable:
                result.append(r)
            if r.is_bidirectional and r.to_node == node_id and r.is_passable:
                result.append(r)
        return result

    def get_neighbors(self, node_id: str) -> list[tuple[str, Road]]:
        """返回 [(neighbor_node_id, road), ...]"""
        result = []
        for r in self.roads:
            if not r.is_passable:
                continue
            if r.from_node == node_id:
                result.append((r.to_node, r))
            elif r.is_bidirectional and r.to_node == node_id:
                result.append((r.from_node, r))
        return result


# ============================================================
# 灾害模型
# ============================================================

@dataclass
class WaveArrival:
    node_id: str
    arrival_min: int


@dataclass
class EarthquakeData:
    epicenter_city: str
    epicenter_lat: float
    epicenter_lng: float
    magnitude: float
    depth_km: float
    influence_radius_km: float
    occur_time: str
    wave_arrival_times: list[WaveArrival] = field(default_factory=list)
    affected_areas: list[str] = field(default_factory=list)
    severity_level: str = "moderate"


@dataclass
class RainstormData:
    center_city: str
    center_lat: float
    center_lng: float
    rainfall_mm: float
    waterlogged_roads: list[dict] = field(default_factory=list)
    river_water_level: list[dict] = field(default_factory=list)
    affected_duration_hours: float = 24.0
    affected_areas: list[str] = field(default_factory=list)


@dataclass
class TyphoonData:
    typhoon_name: str
    center_lat: float
    center_lng: float
    wind_force_level: float
    moving_speed_kmh: float
    moving_direction: str
    landing_time: str
    landing_location: str
    influence_radius_km: float
    port_closure: bool = False
    airport_closure: bool = False
    affected_areas: list[str] = field(default_factory=list)


@dataclass
class LandslideData:
    location_city: str
    location_lat: float
    location_lng: float
    blocked_roads: list[str] = field(default_factory=list)
    scale_level: str = "medium"
    estimated_clear_hours: float = 48.0
    affected_areas: list[str] = field(default_factory=list)


@dataclass
class SnowstormData:
    center_city: str
    center_lat: float
    center_lng: float
    snowfall_cm: float = 30.0
    temperature_min: float = -15.0
    affected_duration_hours: float = 48.0
    affected_areas: list[str] = field(default_factory=list)


@dataclass
class SandstormData:
    center_city: str
    center_lat: float
    center_lng: float
    wind_force_level: float = 9.0
    visibility_m: float = 500.0
    affected_duration_hours: float = 12.0
    affected_areas: list[str] = field(default_factory=list)


@dataclass
class WildfireData:
    center_city: str
    center_lat: float
    center_lng: float
    fire_level: int = 3
    burned_area_ha: float = 500.0
    affected_areas: list[str] = field(default_factory=list)


@dataclass
class TsunamiData:
    center_city: str
    center_lat: float
    center_lng: float
    wave_height_m: float = 5.0
    warning_level: str = "red"
    affected_areas: list[str] = field(default_factory=list)


@dataclass
class Disaster:
    disaster_id: str
    disaster_type: DisasterType
    earthquake: Optional[EarthquakeData] = None
    rainstorm: Optional[RainstormData] = None
    typhoon: Optional[TyphoonData] = None
    landslide: Optional[LandslideData] = None
    snowstorm: Optional[SnowstormData] = None
    sandstorm: Optional[SandstormData] = None
    wildfire: Optional[WildfireData] = None
    tsunami: Optional[TsunamiData] = None
    _radius_km: float = 0.0

    @property
    def center_lat(self) -> float:
        if self.earthquake:
            return self.earthquake.epicenter_lat
        if self.rainstorm:
            return self.rainstorm.center_lat
        if self.typhoon:
            return self.typhoon.center_lat
        if self.landslide:
            return self.landslide.location_lat
        if self.snowstorm:
            return self.snowstorm.center_lat
        if self.sandstorm:
            return self.sandstorm.center_lat
        if self.wildfire:
            return self.wildfire.center_lat
        if self.tsunami:
            return self.tsunami.center_lat
        return 0.0

    @property
    def center_lng(self) -> float:
        if self.earthquake:
            return self.earthquake.epicenter_lng
        if self.rainstorm:
            return self.rainstorm.center_lng
        if self.typhoon:
            return self.typhoon.center_lng
        if self.landslide:
            return self.landslide.location_lng
        if self.snowstorm:
            return self.snowstorm.center_lng
        if self.sandstorm:
            return self.sandstorm.center_lng
        if self.wildfire:
            return self.wildfire.center_lng
        if self.tsunami:
            return self.tsunami.center_lng
        return 0.0

    @property
    def influence_radius_km(self) -> float:
        # 对于自带半径的灾害类型(地震/台风)，取自带半径和场景覆盖半径的最大值
        if self.earthquake:
            eq_radius = self.earthquake.influence_radius_km or 50.0
            return max(eq_radius, self._radius_km) if self._radius_km > 0 else eq_radius
        if self.typhoon:
            tf_radius = self.typhoon.influence_radius_km or 80.0
            return max(tf_radius, self._radius_km) if self._radius_km > 0 else tf_radius
        # 对于没有自带半径的灾害类型，优先使用场景数据中配置的半径
        if self._radius_km > 0:
            return self._radius_km
        if self.rainstorm:
            return 50.0  # 默认暴雨影响半径
        if self.landslide:
            return 80.0  # 默认滑坡影响半径
        if self.snowstorm:
            return 80.0  # 默认暴雪影响半径
        if self.sandstorm:
            return 80.0  # 默认沙尘暴影响半径
        if self.wildfire:
            return 50.0  # 默认森林火灾影响半径
        if self.tsunami:
            return 80.0  # 默认海啸影响半径
        return 50.0

    @property
    def affected_areas(self) -> list[str]:
        if self.earthquake:
            return self.earthquake.affected_areas
        if self.rainstorm:
            return self.rainstorm.affected_areas
        if self.typhoon:
            return self.typhoon.affected_areas
        if self.landslide:
            return self.landslide.affected_areas
        if self.snowstorm:
            return self.snowstorm.affected_areas
        if self.sandstorm:
            return self.sandstorm.affected_areas
        if self.wildfire:
            return self.wildfire.affected_areas
        if self.tsunami:
            return self.tsunami.affected_areas
        return []


# ============================================================
# 车辆模型
# ============================================================

@dataclass
class Vehicle:
    vehicle_id: str
    license_plate: str
    vehicle_type: VehicleType
    capacity_tons: float
    capacity_m3: float
    current_location_node: str
    current_lat: float
    current_lng: float
    status: VehicleStatus
    current_cargo_ids: list[str] = field(default_factory=list)
    current_load_tons: float = 0.0
    current_load_m3: float = 0.0
    driver_name: str = ""
    home_depot: str = ""
    cost_per_km: float = 8.0
    cost_per_hour: float = 120.0
    is_refrigerated: bool = False

    @property
    def remaining_capacity_tons(self) -> float:
        return max(0, self.capacity_tons - self.current_load_tons)

    @property
    def remaining_capacity_m3(self) -> float:
        return max(0, self.capacity_m3 - self.current_load_m3)

    @property
    def is_dispatchable(self) -> bool:
        if self.status == VehicleStatus.MAINTENANCE:
            return False
        return True

    def can_carry(self, weight_tons: float, volume_m3: float) -> bool:
        return (self.remaining_capacity_tons >= weight_tons and
                self.remaining_capacity_m3 >= volume_m3)


# ============================================================
# 仓库模型
# ============================================================

@dataclass
class Warehouse:
    warehouse_id: str
    warehouse_name: str
    city: str
    address: str
    lat: float
    lng: float
    node_id: str
    total_capacity_m3: float
    used_capacity_m3: float
    storage_cost_per_m3_per_day: float
    supported_cargo_types: list[str] = field(default_factory=lambda: ["normal"])
    has_cold_chain: bool = False
    has_dock: int = 4
    dock_occupancy: int = 0
    is_24h: bool = True
    damage_status: WarehouseDamage = WarehouseDamage.NORMAL
    estimated_recovery_hours: float = 0.0

    @property
    def remaining_capacity_m3(self) -> float:
        return max(0, self.total_capacity_m3 - self.used_capacity_m3)

    @property
    def available_capacity_m3(self) -> float:
        """灾后可用容量 (受损仓库折减)"""
        if self.damage_status == WarehouseDamage.CLOSED:
            return 0.0
        if self.damage_status == WarehouseDamage.DAMAGED:
            return self.remaining_capacity_m3 * 0.5
        return self.remaining_capacity_m3

    @property
    def available_docks(self) -> int:
        return max(0, self.has_dock - self.dock_occupancy)

    def can_accept(self, volume_m3: float, cargo_type: str) -> bool:
        type_ok = (cargo_type in self.supported_cargo_types or
                   "normal" in self.supported_cargo_types)
        return type_ok and self.available_capacity_m3 >= volume_m3


# ============================================================
# 货物/订单模型
# ============================================================

@dataclass
class Cargo:
    cargo_id: str
    order_no: str
    cargo_type: CargoType
    description: str
    weight_tons: float
    volume_m3: float
    value_yuan: float
    priority_level: PriorityLevel
    requires_cold_chain: bool = False
    is_hazardous: bool = False

    # 运输任务
    origin_node: str = ""
    origin_name: str = ""
    destination_node: str = ""
    destination_name: str = ""
    destination_lat: float = 0.0
    destination_lng: float = 0.0
    assigned_vehicle_id: str = ""
    current_status: CargoStatus = CargoStatus.PENDING
    current_location_node: str = ""
    planned_route: list[str] = field(default_factory=list)
    current_route_index: int = 0
    departure_time: str = ""
    deadline: str = ""
    contract_penalty_per_hour: float = 500.0

    # 客户
    customer_id: str = ""
    customer_name: str = ""
    customer_type: CustomerType = CustomerType.INDIVIDUAL

    # 灾害影响标记
    is_blocked: bool = False
    is_destination_restricted: bool = False

    @property
    def is_p1(self) -> bool:
        return self.priority_level == PriorityLevel.P1

    @property
    def is_p2(self) -> bool:
        return self.priority_level == PriorityLevel.P2

    @property
    def can_be_abandoned(self) -> bool:
        return self.priority_level == PriorityLevel.P3

    @property
    def deadline_urgency_hours(self) -> float:
        """距deadline还有多少小时 (简化:返回一个优先级排序用的数)"""
        if not self.deadline:
            return 999.0
        return 24.0  # 简化,实际解析时计算


# ============================================================
# 评分配置模型
# ============================================================

@dataclass
class ScoreWeights:
    timeliness: float = 0.30
    economic: float = 0.25
    feasibility: float = 0.25
    compliance: float = 0.20

    def validate(self) -> bool:
        return abs(self.timeliness + self.economic + self.feasibility + self.compliance - 1.0) < 0.01


@dataclass
class BonusRule:
    rule: str
    score: float


@dataclass
class EvaluationConfig:
    config_id: str = "EVAL-DEFAULT"
    scenario_id: str = ""
    benchmark_cost: float = 40000.0
    benchmark_delivery_time_hours: float = 24.0
    weights: ScoreWeights = field(default_factory=ScoreWeights)
    bonus_rules: list[BonusRule] = field(default_factory=lambda: [BonusRule("first_submit_bonus", 5.0)])
    penalty_rules: list[BonusRule] = field(default_factory=lambda: [BonusRule("timeout_penalty", -10.0)])
    compliance_priority_list: list[str] = field(default_factory=lambda: ["medical", "supplies"])


# ============================================================
# 策略配置模型
# ============================================================

@dataclass
class StrategyConfig:
    mode: StrategyMode = StrategyMode.TIME_PRESSURE
    time_limit_sec: int = 600
    hide_optimal_until_submit: bool = True
    objective_weights: dict = field(default_factory=lambda: {
        "w_cost": 0.3, "w_time": 0.4, "w_risk": 0.2, "w_comp": 0.1
    })
    generate_alternatives: bool = True
    max_alternatives: int = 2
    # 策略二: 隐藏干扰
    hidden_disruptions: list[dict] = field(default_factory=list)
    allow_student_override: bool = False
    # 策略三: 预算约束
    student_budget: Optional[dict] = None
    constraint_overrides: Optional[dict] = None


# ============================================================
# 场景上下文 (引擎输入)
# ============================================================

@dataclass
class ScenarioContext:
    scenario_id: str
    scenario_name: str
    disaster: Disaster
    logistics_network: LogisticsNetwork
    vehicle_fleet: list[Vehicle]
    warehouses: list[Warehouse]
    cargo_manifest: list[Cargo]
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    strategy_config: StrategyConfig = field(default_factory=StrategyConfig)
    created_at: str = ""


# ============================================================
# 决策方案 (引擎输出)
# ============================================================

@dataclass
class Action:
    action_id: str
    action_type: ActionPlanType
    description: str
    cargo_ids: list[str]
    vehicle_id: str = ""
    new_route: list[str] = field(default_factory=list)
    original_route: list[str] = field(default_factory=list)
    warehouse_id: str = ""
    extra_cost: float = 0.0
    extra_time_min: float = 0.0
    risk_score: float = 0.0
    storage_cost: float = 0.0
    storage_duration_hours: float = 0.0
    value_loss: float = 0.0
    reason: str = ""


@dataclass
class DimensionScore:
    score: float
    reason: str


@dataclass
class ScoreBreakdown:
    timeliness: DimensionScore
    economic: DimensionScore
    feasibility: DimensionScore
    compliance: DimensionScore

    @property
    def total(self) -> float:
        return round(self.timeliness.score * 0.30 +
                      self.economic.score * 0.25 +
                      self.feasibility.score * 0.25 +
                      self.compliance.score * 0.20, 1)


@dataclass
class DecisionPlan:
    plan_id: str
    scenario_id: str
    generated_at: str
    total_cost: float
    total_delay_hours: float
    vehicles_used: int
    warehouses_used: int
    cargo_delivered: int
    cargo_abandoned: int
    cargo_stored: int
    actions: list[Action]
    score_breakdown: Optional[ScoreBreakdown] = None
    alternatives: list[dict] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "scenario_id": self.scenario_id,
            "generated_at": self.generated_at,
            "total_cost": self.total_cost,
            "total_delay_hours": self.total_delay_hours,
            "vehicles_used": self.vehicles_used,
            "warehouses_used": self.warehouses_used,
            "cargo_delivered": self.cargo_delivered,
            "cargo_abandoned": self.cargo_abandoned,
            "cargo_stored": self.cargo_stored,
            "actions": [
                {
                    "action_id": a.action_id,
                    "type": a.action_type.value,
                    "description": a.description,
                    "vehicle_id": a.vehicle_id,
                    "cargo_ids": a.cargo_ids,
                    "new_route": a.new_route,
                    "original_route": a.original_route,
                    "warehouse_id": a.warehouse_id,
                    "extra_cost": a.extra_cost,
                    "extra_time_min": a.extra_time_min,
                    "risk_score": a.risk_score,
                    "storage_cost": a.storage_cost,
                    "storage_duration_hours": a.storage_duration_hours,
                    "value_loss": a.value_loss,
                    "reason": a.reason,
                }
                for a in self.actions
            ],
            "score_breakdown": {
                "timeliness": {"score": self.score_breakdown.timeliness.score,
                               "reason": self.score_breakdown.timeliness.reason},
                "economic": {"score": self.score_breakdown.economic.score,
                             "reason": self.score_breakdown.economic.reason},
                "feasibility": {"score": self.score_breakdown.feasibility.score,
                                "reason": self.score_breakdown.feasibility.reason},
                "compliance": {"score": self.score_breakdown.compliance.score,
                               "reason": self.score_breakdown.compliance.reason},
                "total": self.score_breakdown.total if self.score_breakdown else 0,
            } if self.score_breakdown else None,
            "alternatives": self.alternatives,
            "explanation": self.explanation,
        }


# ============================================================
# 学生方案对比
# ============================================================

@dataclass
class PlanComparison:
    comparison_id: str
    optimal_plan: dict
    student_plan: dict
    diff: dict
    analysis: str
