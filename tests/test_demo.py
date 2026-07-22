"""
测试验证脚本 - 加载地震场景, 运行完整决策流程, 输出结果
"""

import json
import sys
import os

# 添加src到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from emergency_decision.models import (
    ScenarioContext, Disaster, DisasterType, EarthquakeData,
    LogisticsNetwork, NetworkNode, Road, RoadType, RoadCondition,
    Vehicle, VehicleType, VehicleStatus,
    Warehouse, WarehouseDamage,
    Cargo, CargoType, PriorityLevel, CargoStatus, CustomerType,
    EvaluationConfig, ScoreWeights, BonusRule, StrategyConfig,
    ActionPlanType,
)
from emergency_decision.engine import EmergencyDecisionEngine
from emergency_decision.student_evaluator import StudentPlanEvaluator, StudentSubmission, StudentAction


def load_scenario(filepath: str) -> ScenarioContext:
    """从JSON加载场景"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 解析灾害
    d = data['disaster']
    eq_data = None
    if 'earthquake' in d and d['earthquake']:
        eq = d['earthquake']
        eq_data = EarthquakeData(
            epicenter_city=eq['epicenter_city'],
            epicenter_lat=eq['epicenter_lat'],
            epicenter_lng=eq['epicenter_lng'],
            magnitude=eq['magnitude'],
            depth_km=eq['depth_km'],
            influence_radius_km=eq['influence_radius_km'],
            occur_time=eq['occur_time'],
            affected_areas=eq.get('affected_areas', []),
            severity_level=eq.get('severity_level', 'moderate'),
        )
    disaster = Disaster(
        disaster_id=d['disaster_id'],
        disaster_type=DisasterType(d['disaster_type']),
        earthquake=eq_data,
    )

    # 解析物流网络
    nodes = []
    for n in data['logistics_network']['nodes']:
        nodes.append(NetworkNode(
            node_id=n['node_id'],
            node_name=n['node_name'],
            node_type=n['node_type'],
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
                      for r in ev.get('bonus_rules', [])],
        penalty_rules=[BonusRule(rule=r['rule'], score=r['score'])
                        for r in ev.get('penalty_rules', [])],
        compliance_priority_list=ev.get('compliance_priority_list', ['medical', 'supplies']),
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
    )


def test_main():
    """主测试函数"""
    scenario_path = os.path.join(
        os.path.dirname(__file__), '..', 'scenarios', 'earthquake_demo.json')
    scenario_path = os.path.abspath(scenario_path)

    print("=" * 70)
    print("应急决策引擎 - 测试验证")
    print("=" * 70)
    print(f"\n加载场景: {scenario_path}")

    scenario = load_scenario(scenario_path)
    print(f"场景名称: {scenario.scenario_name}")
    print(f"灾害类型: {scenario.disaster.disaster_type.value}")
    print(f"网络节点: {len(scenario.logistics_network.nodes)} 个")
    print(f"道路路段: {len(scenario.logistics_network.roads)} 条")
    print(f"车辆: {len(scenario.vehicle_fleet)} 辆")
    print(f"仓库: {len(scenario.warehouses)} 个")
    print(f"货物: {len(scenario.cargo_manifest)} 单")

    # 运行引擎
    print("\n" + "=" * 70)
    print("运行决策引擎...")
    print("=" * 70)

    engine = EmergencyDecisionEngine()
    plan = engine.solve(scenario)

    # 输出灾害影响
    print("\n--- 灾害影响分析 ---")
    print(engine.get_impact_summary())

    # 输出最优方案
    print("\n--- 最优方案 ---")
    print(f"方案ID: {plan.plan_id}")
    print(f"生成时间: {plan.generated_at}")
    print(f"总成本: {plan.total_cost:,.1f} 元")
    print(f"总超时: {plan.total_delay_hours:.1f} 小时")
    print(f"使用车辆: {plan.vehicles_used} 辆")
    print(f"使用仓库: {plan.warehouses_used} 个")
    print(f"改道送达: {plan.cargo_delivered} 单")
    print(f"转仓暂存: {plan.cargo_stored} 单")
    print(f"放弃货物: {plan.cargo_abandoned} 单")

    # 输出动作明细
    print(f"\n--- 决策动作明细 ({len(plan.actions)}个) ---")
    for a in plan.actions:
        print(f"  [{a.action_id}] {a.action_type.value}: {a.description}")
        print(f"       涉及货物: {a.cargo_ids}, 成本: {a.extra_cost}元, "
              f"超时: {a.extra_time_min}分钟, 风险: {a.risk_score}")

    # 输出评分
    if plan.score_breakdown:
        print(f"\n--- 评分明细 ---")
        sb = plan.score_breakdown
        print(f"  时效性: {sb.timeliness.score:.1f} ({sb.timeliness.reason})")
        print(f"  经济性: {sb.economic.score:.1f} ({sb.economic.reason})")
        print(f"  可行性: {sb.feasibility.score:.1f} ({sb.feasibility.reason})")
        print(f"  合规性: {sb.compliance.score:.1f} ({sb.compliance.reason})")
        print(f"  总分: {sb.total:.1f}")
        grade, desc = __import__('emergency_decision.scoring',
                                  fromlist=['ScoringEngine']).ScoringEngine.get_grade(sb.total)
        print(f"  等级: {grade} ({desc})")

    # 输出备选方案
    if plan.alternatives:
        print(f"\n--- 备选方案 ---")
        for alt in plan.alternatives:
            print(f"  {alt['plan_id']}: {alt['description']}")
            print(f"    成本: {alt['total_cost']:,.1f}元, 放弃: {alt['cargo_abandoned']}单, "
                  f"评分: {alt['score']}")

    # 输出方案说明
    print(f"\n--- 方案说明 ---")
    print(plan.explanation)

    # 生成评语
    print(f"\n--- 智能评语 ---")
    comment = engine.generate_comment(plan, disaster_type="earthquake")
    print(comment)

    # 测试学生方案对比
    print("\n" + "=" * 70)
    print("测试学生方案评估...")
    print("=" * 70)

    student_sub = StudentSubmission(
        student_id="STU-001",
        scenario_id=scenario.scenario_id,
        actions=[
            StudentAction(cargo_id="C-101", action_type=ActionPlanType.REROUTE,
                          vehicle_id="V-01",
                          route=["NODE-CD03", "NODE-DY01", "NODE-MY01", "NODE-MY02"]),
            StudentAction(cargo_id="C-102", action_type=ActionPlanType.WAREHOUSE_TRANSFER,
                          warehouse_id="WH-02"),
            StudentAction(cargo_id="C-104", action_type=ActionPlanType.ABANDON),
        ],
        submit_time_offset_sec=480,
        is_first_submit=True,
    )

    evaluator = StudentPlanEvaluator()
    comparison = evaluator.evaluate(
        student_sub,
        scenario.cargo_manifest,
        scenario.evaluation,
        plan,
        available_vehicles=5,
        available_warehouses=3,
    )

    print(f"\n学生方案对比结果:")
    print(f"  最优方案成本: {comparison['optimal_plan']['total_cost']:,.1f}元")
    print(f"  学生方案成本: {comparison['student_plan']['total_cost']:,.1f}元")
    print(f"  成本差异: {comparison['diff']['cost_delta']:+,.1f}元")
    print(f"  评分差异: {comparison['diff']['score_delta']:+.1f}分")
    print(f"\n  对比分析:")
    for line in comparison['analysis'].split('\n'):
        print(f"    {line}")

    # 保存结果到文件
    print("\n" + "=" * 70)
    print("保存结果到文件...")
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
    os.makedirs(output_dir, exist_ok=True)

    result = plan.to_dict()
    result['comment'] = comment
    result['student_comparison'] = comparison

    output_path = os.path.join(output_dir, 'decision_result.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {output_path}")

    print("\n" + "=" * 70)
    print("测试完成!")
    print("=" * 70)


if __name__ == '__main__':
    test_main()
