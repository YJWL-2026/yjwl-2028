"""
场景加载器 - 从JSON加载/保存场景数据
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .models import (
    ScenarioContext, Disaster, DisasterType,
    EarthquakeData, RainstormData, TyphoonData, LandslideData,
    WaveArrival,
    LogisticsNetwork, NetworkNode, Road, RoadType, RoadCondition,
    Vehicle, VehicleType, VehicleStatus,
    Warehouse, WarehouseDamage,
    Cargo, CargoType, PriorityLevel, CargoStatus, CustomerType,
    EvaluationConfig, ScoreWeights, BonusRule,
    StrategyConfig, StrategyMode, NodeType,
)


def load_scenario_from_dict(data: dict) -> ScenarioContext:
    """从dict加载场景"""
    # 解析灾害
    d = data['disaster']
    eq_data = rs_data = tf_data = ls_data = None

    if d.get('earthquake'):
        eq = d['earthquake']
        wave_arrivals = []
        for w in eq.get('wave_arrival_times', []):
            wave_arrivals.append(WaveArrival(
                node_id=w['node_id'], arrival_min=w['arrival_min']))
        eq_data = EarthquakeData(
            epicenter_city=eq['epicenter_city'],
            epicenter_lat=eq['epicenter_lat'],
            epicenter_lng=eq['epicenter_lng'],
            magnitude=eq['magnitude'],
            depth_km=eq['depth_km'],
            influence_radius_km=eq['influence_radius_km'],
            occur_time=eq['occur_time'],
            wave_arrival_times=wave_arrivals,
            affected_areas=eq.get('affected_areas', []),
            severity_level=eq.get('severity_level', 'moderate'),
        )

    if d.get('rainstorm'):
        rs = d['rainstorm']
        rs_data = RainstormData(
            center_city=rs['center_city'],
            center_lat=rs['center_lat'],
            center_lng=rs['center_lng'],
            rainfall_mm=rs['rainfall_mm'],
            waterlogged_roads=rs.get('waterlogged_roads', []),
            river_water_level=rs.get('river_water_level', []),
            affected_duration_hours=rs.get('affected_duration_hours', 24),
            affected_areas=rs.get('affected_areas', []),
        )

    if d.get('typhoon'):
        tf = d['typhoon']
        tf_data = TyphoonData(
            typhoon_name=tf['typhoon_name'],
            center_lat=tf['center_lat'],
            center_lng=tf['center_lng'],
            wind_force_level=tf['wind_force_level'],
            moving_speed_kmh=tf['moving_speed_kmh'],
            moving_direction=tf['moving_direction'],
            landing_time=tf['landing_time'],
            landing_location=tf['landing_location'],
            influence_radius_km=tf['influence_radius_km'],
            port_closure=tf.get('port_closure', False),
            airport_closure=tf.get('airport_closure', False),
            affected_areas=tf.get('affected_areas', []),
        )

    if d.get('landslide'):
        ls = d['landslide']
        ls_data = LandslideData(
            location_city=ls['location_city'],
            location_lat=ls['location_lat'],
            location_lng=ls['location_lng'],
            blocked_roads=ls.get('blocked_roads', []),
            scale_level=ls.get('scale_level', 'medium'),
            estimated_clear_hours=ls.get('estimated_clear_hours', 48),
            affected_areas=ls.get('affected_areas', []),
        )

    disaster = Disaster(
        disaster_id=d['disaster_id'],
        disaster_type=DisasterType(d['disaster_type']),
        earthquake=eq_data,
        rainstorm=rs_data,
        typhoon=tf_data,
        landslide=ls_data,
    )

    # 解析物流网络
    nodes = []
    for n in data['logistics_network']['nodes']:
        node_type = n['node_type']
        if isinstance(node_type, str):
            try:
                node_type = NodeType(node_type)
            except ValueError:
                node_type = NodeType.JUNCTION
        nodes.append(NetworkNode(
            node_id=n['node_id'],
            node_name=n['node_name'],
            node_type=node_type,
            city=n['city'],
            lat=n['lat'],
            lng=n['lng'],
            connected_road_ids=n.get('connected_road_ids', []),
        ))
    roads = []
    for r in data['logistics_network']['roads']:
        roads.append(Road(
            road_id=r['road_id'],
            road_name=r['road_name'],
            road_type=RoadType(r['road_type']),
            from_node=r['from_node'],
            to_node=r['to_node'],
            is_bidirectional=r['is_bidirectional'],
            distance_km=r['distance_km'],
            speed_limit_kmh=r['speed_limit_kmh'],
            current_travel_time_min=r['current_travel_time_min'],
            road_condition=RoadCondition(r['road_condition']),
            has_bridge=r.get('has_bridge', False),
            has_tunnel=r.get('has_tunnel', False),
            capacity_per_hour=r.get('capacity_per_hour', 2000),
            toll_cost=r.get('toll_cost', 0),
            fuel_cost_per_km=r.get('fuel_cost_per_km', 0.8),
        ))
    network = LogisticsNetwork(nodes=nodes, roads=roads)

    # 解析车辆
    vehicles = []
    for v in data['vehicle_fleet']:
        vehicles.append(Vehicle(
            vehicle_id=v['vehicle_id'],
            license_plate=v['license_plate'],
            vehicle_type=VehicleType(v['vehicle_type']),
            capacity_tons=v['capacity_tons'],
            capacity_m3=v['capacity_m3'],
            current_location_node=v['current_location_node'],
            current_lat=v['current_lat'],
            current_lng=v['current_lng'],
            status=VehicleStatus(v['status']),
            current_cargo_ids=v.get('current_cargo_ids', []),
            current_load_tons=v.get('current_load_tons', 0),
            current_load_m3=v.get('current_load_m3', 0),
            driver_name=v.get('driver_name', ''),
            home_depot=v.get('home_depot', ''),
            cost_per_km=v.get('cost_per_km', 8.0),
            cost_per_hour=v.get('cost_per_hour', 120),
            is_refrigerated=v.get('is_refrigerated', False),
        ))

    # 解析仓库
    warehouses = []
    for w in data['warehouses']:
        warehouses.append(Warehouse(
            warehouse_id=w['warehouse_id'],
            warehouse_name=w['warehouse_name'],
            city=w['city'],
            address=w.get('address', ''),
            lat=w['lat'],
            lng=w['lng'],
            node_id=w['node_id'],
            total_capacity_m3=w['total_capacity_m3'],
            used_capacity_m3=w['used_capacity_m3'],
            storage_cost_per_m3_per_day=w['storage_cost_per_m3_per_day'],
            supported_cargo_types=w.get('supported_cargo_types', ['normal']),
            has_cold_chain=w.get('has_cold_chain', False),
            has_dock=w.get('has_dock', 4),
            dock_occupancy=w.get('dock_occupancy', 0),
            is_24h=w.get('is_24h', True),
            damage_status=WarehouseDamage(w.get('damage_status', 'normal')),
        ))

    # 解析货物
    cargos = []
    for c in data['cargo_manifest']:
        cargos.append(Cargo(
            cargo_id=c['cargo_id'],
            order_no=c.get('order_no', ''),
            cargo_type=CargoType(c['cargo_type']),
            description=c.get('description', ''),
            weight_tons=c['weight_tons'],
            volume_m3=c['volume_m3'],
            value_yuan=c['value_yuan'],
            priority_level=PriorityLevel(c.get('priority_level', 'P3')),
            requires_cold_chain=c.get('requires_cold_chain', False),
            is_hazardous=c.get('is_hazardous', False),
            origin_node=c.get('origin_node', ''),
            origin_name=c.get('origin_name', ''),
            destination_node=c.get('destination_node', ''),
            destination_name=c.get('destination_name', ''),
            destination_lat=c.get('destination_lat', 0),
            destination_lng=c.get('destination_lng', 0),
            assigned_vehicle_id=c.get('assigned_vehicle_id', ''),
            current_status=CargoStatus(c.get('current_status', 'pending')),
            current_location_node=c.get('current_location_node', ''),
            planned_route=c.get('planned_route', []),
            current_route_index=c.get('current_route_index', 0),
            departure_time=c.get('departure_time', ''),
            deadline=c.get('deadline', ''),
            contract_penalty_per_hour=c.get('contract_penalty_per_hour', 500),
            customer_id=c.get('customer_id', ''),
            customer_name=c.get('customer_name', ''),
            customer_type=CustomerType(c.get('customer_type', 'individual')),
        ))

    # 解析评分配置
    ev = data.get('evaluation', {})
    weights_data = ev.get('weights', {})
    eval_config = EvaluationConfig(
        config_id=ev.get('config_id', 'EVAL-DEFAULT'),
        scenario_id=ev.get('scenario_id', ''),
        benchmark_cost=ev.get('benchmark_cost', 40000),
        benchmark_delivery_time_hours=ev.get('benchmark_delivery_time_hours', 24),
        weights=ScoreWeights(
            timeliness=weights_data.get('timeliness', 0.3),
            economic=weights_data.get('economic', 0.25),
            feasibility=weights_data.get('feasibility', 0.25),
            compliance=weights_data.get('compliance', 0.2),
        ),
        bonus_rules=[BonusRule(rule=r['rule'], score=r['score'])
                      for r in ev.get('bonus_rules', [{'rule': 'first_submit_bonus', 'score': 5}])],
        penalty_rules=[BonusRule(rule=r['rule'], score=r['score'])
                        for r in ev.get('penalty_rules', [{'rule': 'timeout_penalty', 'score': -10}])],
        compliance_priority_list=ev.get('compliance_priority_list', ['medical', 'supplies']),
    )

    # 解析策略配置
    sc = data.get('strategy_config', {})
    strategy_config = StrategyConfig(
        mode=StrategyMode(sc.get('mode', 'time_pressure')),
        time_limit_sec=sc.get('time_limit_sec', 600),
        hide_optimal_until_submit=sc.get('hide_optimal_until_submit', True),
        generate_alternatives=sc.get('generate_alternatives', True),
        max_alternatives=sc.get('max_alternatives', 2),
    )

    return ScenarioContext(
        scenario_id=data['scenario_id'],
        scenario_name=data.get('scenario_name', ''),
        disaster=disaster,
        logistics_network=network,
        vehicle_fleet=vehicles,
        warehouses=warehouses,
        cargo_manifest=cargos,
        evaluation=eval_config,
        strategy_config=strategy_config,
        created_at=data.get('created_at', ''),
    )


def load_scenario_from_file(filepath: str) -> ScenarioContext:
    """从JSON文件加载场景"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return load_scenario_from_dict(data)


def save_scenario_to_file(data: dict, filepath: str):
    """保存场景到JSON文件"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def scenario_to_dict(scenario: ScenarioContext) -> dict:
    """将ScenarioContext对象转回dict (用于编辑器显示)"""
    d = scenario.disaster
    disaster_dict = {
        "disaster_id": d.disaster_id,
        "disaster_type": d.disaster_type.value,
    }
    if d.earthquake:
        eq = d.earthquake
        disaster_dict["earthquake"] = {
            "epicenter_city": eq.epicenter_city,
            "epicenter_lat": eq.epicenter_lat,
            "epicenter_lng": eq.epicenter_lng,
            "magnitude": eq.magnitude,
            "depth_km": eq.depth_km,
            "influence_radius_km": eq.influence_radius_km,
            "occur_time": eq.occur_time,
            "affected_areas": eq.affected_areas,
            "severity_level": eq.severity_level,
            "wave_arrival_times": [
                {"node_id": w.node_id, "arrival_min": w.arrival_min}
                for w in eq.wave_arrival_times
            ],
        }
    if d.rainstorm:
        rs = d.rainstorm
        disaster_dict["rainstorm"] = {
            "center_city": rs.center_city,
            "center_lat": rs.center_lat,
            "center_lng": rs.center_lng,
            "rainfall_mm": rs.rainfall_mm,
            "waterlogged_roads": rs.waterlogged_roads,
            "river_water_level": rs.river_water_level,
            "affected_duration_hours": rs.affected_duration_hours,
            "affected_areas": rs.affected_areas,
        }
    if d.typhoon:
        tf = d.typhoon
        disaster_dict["typhoon"] = {
            "typhoon_name": tf.typhoon_name,
            "center_lat": tf.center_lat,
            "center_lng": tf.center_lng,
            "wind_force_level": tf.wind_force_level,
            "moving_speed_kmh": tf.moving_speed_kmh,
            "moving_direction": tf.moving_direction,
            "landing_time": tf.landing_time,
            "landing_location": tf.landing_location,
            "influence_radius_km": tf.influence_radius_km,
            "port_closure": tf.port_closure,
            "airport_closure": tf.airport_closure,
            "affected_areas": tf.affected_areas,
        }

    return {
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.scenario_name,
        "disaster": disaster_dict,
        "logistics_network": {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "node_name": n.node_name,
                    "node_type": n.node_type.value if hasattr(n.node_type, 'value') else str(n.node_type),
                    "city": n.city,
                    "lat": n.lat,
                    "lng": n.lng,
                    "connected_road_ids": n.connected_road_ids,
                }
                for n in scenario.logistics_network.nodes
            ],
            "roads": [
                {
                    "road_id": r.road_id,
                    "road_name": r.road_name,
                    "road_type": r.road_type.value,
                    "from_node": r.from_node,
                    "to_node": r.to_node,
                    "is_bidirectional": r.is_bidirectional,
                    "distance_km": r.distance_km,
                    "speed_limit_kmh": r.speed_limit_kmh,
                    "current_travel_time_min": r.current_travel_time_min,
                    "road_condition": r.road_condition.value,
                    "has_bridge": r.has_bridge,
                    "has_tunnel": r.has_tunnel,
                    "capacity_per_hour": r.capacity_per_hour,
                    "toll_cost": r.toll_cost,
                    "fuel_cost_per_km": r.fuel_cost_per_km,
                }
                for r in scenario.logistics_network.roads
            ],
        },
        "vehicle_fleet": [
            {
                "vehicle_id": v.vehicle_id,
                "license_plate": v.license_plate,
                "vehicle_type": v.vehicle_type.value,
                "capacity_tons": v.capacity_tons,
                "capacity_m3": v.capacity_m3,
                "current_location_node": v.current_location_node,
                "current_lat": v.current_lat,
                "current_lng": v.current_lng,
                "status": v.status.value,
                "current_cargo_ids": v.current_cargo_ids,
                "current_load_tons": v.current_load_tons,
                "current_load_m3": v.current_load_m3,
                "driver_name": v.driver_name,
                "home_depot": v.home_depot,
                "cost_per_km": v.cost_per_km,
                "cost_per_hour": v.cost_per_hour,
                "is_refrigerated": v.is_refrigerated,
            }
            for v in scenario.vehicle_fleet
        ],
        "warehouses": [
            {
                "warehouse_id": w.warehouse_id,
                "warehouse_name": w.warehouse_name,
                "city": w.city,
                "address": w.address,
                "lat": w.lat,
                "lng": w.lng,
                "node_id": w.node_id,
                "total_capacity_m3": w.total_capacity_m3,
                "used_capacity_m3": w.used_capacity_m3,
                "storage_cost_per_m3_per_day": w.storage_cost_per_m3_per_day,
                "supported_cargo_types": w.supported_cargo_types,
                "has_cold_chain": w.has_cold_chain,
                "has_dock": w.has_dock,
                "dock_occupancy": w.dock_occupancy,
                "is_24h": w.is_24h,
                "damage_status": w.damage_status.value,
            }
            for w in scenario.warehouses
        ],
        "cargo_manifest": [
            {
                "cargo_id": c.cargo_id,
                "order_no": c.order_no,
                "cargo_type": c.cargo_type.value,
                "description": c.description,
                "weight_tons": c.weight_tons,
                "volume_m3": c.volume_m3,
                "value_yuan": c.value_yuan,
                "priority_level": c.priority_level.value,
                "requires_cold_chain": c.requires_cold_chain,
                "is_hazardous": c.is_hazardous,
                "origin_node": c.origin_node,
                "origin_name": c.origin_name,
                "destination_node": c.destination_node,
                "destination_name": c.destination_name,
                "destination_lat": c.destination_lat,
                "destination_lng": c.destination_lng,
                "assigned_vehicle_id": c.assigned_vehicle_id,
                "current_status": c.current_status.value,
                "current_location_node": c.current_location_node,
                "planned_route": c.planned_route,
                "current_route_index": c.current_route_index,
                "departure_time": c.departure_time,
                "deadline": c.deadline,
                "contract_penalty_per_hour": c.contract_penalty_per_hour,
                "customer_id": c.customer_id,
                "customer_name": c.customer_name,
                "customer_type": c.customer_type.value,
            }
            for c in scenario.cargo_manifest
        ],
        "evaluation": {
            "config_id": scenario.evaluation.config_id,
            "scenario_id": scenario.evaluation.scenario_id,
            "benchmark_cost": scenario.evaluation.benchmark_cost,
            "benchmark_delivery_time_hours": scenario.evaluation.benchmark_delivery_time_hours,
            "weights": {
                "timeliness": scenario.evaluation.weights.timeliness,
                "economic": scenario.evaluation.weights.economic,
                "feasibility": scenario.evaluation.weights.feasibility,
                "compliance": scenario.evaluation.weights.compliance,
            },
            "bonus_rules": [{"rule": r.rule, "score": r.score} for r in scenario.evaluation.bonus_rules],
            "penalty_rules": [{"rule": r.rule, "score": r.score} for r in scenario.evaluation.penalty_rules],
            "compliance_priority_list": scenario.evaluation.compliance_priority_list,
        },
        "strategy_config": {
            "mode": scenario.strategy_config.mode.value,
            "time_limit_sec": scenario.strategy_config.time_limit_sec,
            "hide_optimal_until_submit": scenario.strategy_config.hide_optimal_until_submit,
            "generate_alternatives": scenario.strategy_config.generate_alternatives,
            "max_alternatives": scenario.strategy_config.max_alternatives,
        },
        "created_at": scenario.created_at,
    }
