"""
三策略适配模块 - 对应技术要求中的三种教学策略

策略一: 人机竞速模式 (TimePressure)
  - 预警推送后进入"黄金10分钟"倒计时
  - 系统隐藏最优方案，学生先提交自己的决策
  - 提交后亮出AI方案，并排对比

策略二: 智能体对抗模式 (AgentAdversarial)
  - AI生成最优方案后，系统额外生成"极端干扰因素"
  - 干扰信息只显示给学生，不显示给AI
  - 学生需要审核并修正AI的方案

策略三: 有限预算博弈 (BudgetConstrained)
  - AI算出最优方案需要的资源量
  - 但学生账户里的资源只有AI方案需求的一部分
  - 学生必须在资源受限前提下重新调整方案
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import (
    Action,
    ActionPlanType,
    Cargo,
    CargoType,
    DecisionPlan,
    PriorityLevel,
    ScenarioContext,
    StrategyConfig,
    StrategyMode,
    Vehicle,
    Warehouse,
)


# ============================================================
# 策略二: 隐藏干扰因素生成器
# ============================================================

@dataclass
class HiddenDisruption:
    """隐藏的极端干扰因素（只显示给学生，不显示给AI）"""
    disruption_id: str
    disruption_type: str       # bridge_damage / road_collapse / fuel_shortage / warehouse_flood
    target_id: str             # 影响的路段ID / 仓库ID / 车辆ID
    target_name: str
    description: str
    severity: str              # critical / moderate / minor
    affected_action_hint: str  # 提示学生应如何调整AI方案
    
    def to_dict(self) -> dict:
        return {
            "disruption_id": self.disruption_id,
            "disruption_type": self.disruption_type,
            "target_id": self.target_id,
            "target_name": self.target_name,
            "description": self.description,
            "severity": self.severity,
            "affected_action_hint": self.affected_action_hint,
        }


class DisruptionGenerator:
    """
    为策略二生成隐藏干扰因素
    - 从AI推荐方案中识别其依赖的关键路段/仓库
    - 生成针对性的干扰，让学生判断是否需要修正
    """

    # 干扰因素模板
    TEMPLATES = [
        {
            "type": "bridge_damage",
            "severity": "critical",
            "desc_template": "前方{road_name}上有桥梁受损，预计{hours}小时内无法通行",
            "hint": "AI方案推荐的绕行路线依赖此路段，建议改为就地卸货转运",
        },
        {
            "type": "road_collapse",
            "severity": "critical",
            "desc_template": "{road_name}发生路基塌陷，信息尚未上报到系统",
            "hint": "AI方案中此路段被标记为可通行，实际已中断",
        },
        {
            "type": "fuel_shortage",
            "severity": "moderate",
            "desc_template": "{city}周边加油站因灾害停电，柴油供应紧张",
            "hint": "经过此区域的车辆燃油可能不足，建议缩短绕行距离",
        },
        {
            "type": "warehouse_flood",
            "severity": "critical",
            "desc_template": "{warehouse_name}库区出现渗水，底层货物面临受潮风险",
            "hint": "AI方案建议转运到此仓库的货物需注意防水",
        },
        {
            "type": "secondary_disaster",
            "severity": "moderate",
            "desc_template": "气象预报显示{area}未来6小时有强降雨，可能引发次生灾害",
            "hint": "AI方案未考虑次生灾害风险，建议提前规避",
        },
    ]

    def generate(self, optimal_plan: DecisionPlan, 
                 scenario: ScenarioContext,
                 count: int = 2) -> list[HiddenDisruption]:
        """
        从AI最优方案中生成隐藏干扰
        
        Args:
            optimal_plan: AI生成的最优方案
            scenario: 场景上下文
            count: 生成几个干扰因素(默认2个)
        """
        disruptions = []
        used_targets = set()
        
        # 从AI方案的动作中提取关键路段和仓库
        critical_roads = set()
        critical_warehouses = set()
        
        for action in optimal_plan.actions:
            if action.action_type == ActionPlanType.REROUTE:
                for i in range(len(action.new_route) - 1):
                    road_key = f"{action.new_route[i]}->{action.new_route[i+1]}"
                    critical_roads.add(road_key)
            elif action.action_type == ActionPlanType.WAREHOUSE_TRANSFER:
                if action.warehouse_id:
                    critical_warehouses.add(action.warehouse_id)
        
        # 从场景路网中查找路段名
        road_name_map = {}
        for road in scenario.logistics_network.roads:
            key = f"{road.from_node}->{road.to_node}"
            road_name_map[key] = road.road_name
        
        # 从场景仓库中查找仓库名
        wh_name_map = {w.warehouse_id: w.warehouse_name for w in scenario.warehouses}
        
        generated = 0
        template_idx = 0
        
        # 优先针对AI方案依赖的关键路段生成干扰
        for road_key in critical_roads:
            if generated >= count:
                break
            road_name = road_name_map.get(road_key, road_key)
            template = self.TEMPLATES[template_idx % len(self.TEMPLATES)]
            template_idx += 1
            
            disruption = HiddenDisruption(
                disruption_id=f"HD-{generated+1:03d}",
                disruption_type=template["type"],
                target_id=road_key,
                target_name=road_name,
                description=template["desc_template"].format(
                    road_name=road_name, hours="3"),
                severity=template["severity"],
                affected_action_hint=template["hint"],
            )
            disruptions.append(disruption)
            generated += 1
        
        # 如果AI方案用了仓库，也生成仓库相关干扰
        for wh_id in critical_warehouses:
            if generated >= count:
                break
            wh_name = wh_name_map.get(wh_id, wh_id)
            template = self.TEMPLATES[3]  # warehouse_flood
            
            disruption = HiddenDisruption(
                disruption_id=f"HD-{generated+1:03d}",
                disruption_type=template["type"],
                target_id=wh_id,
                target_name=wh_name,
                description=template["desc_template"].format(
                    warehouse_name=wh_name),
                severity=template["severity"],
                affected_action_hint=template["hint"],
            )
            disruptions.append(disruption)
            generated += 1
        
        # 如果数量不够，补充次生灾害干扰
        while generated < count:
            template = self.TEMPLATES[4]
            area = scenario.disaster.affected_areas[0] if scenario.disaster.affected_areas else "灾区"
            disruption = HiddenDisruption(
                disruption_id=f"HD-{generated+1:03d}",
                disruption_type=template["type"],
                target_id="area",
                target_name=area,
                description=template["desc_template"].format(area=area),
                severity=template["severity"],
                affected_action_hint=template["hint"],
            )
            disruptions.append(disruption)
            generated += 1
        
        return disruptions[:count]


# ============================================================
# 策略三: 预算约束管理器
# ============================================================

@dataclass
class BudgetConstraint:
    """学生可用的预算约束"""
    max_vehicles: int            # 最多可用备用车辆数
    max_warehouses: int          # 最多可用仓库数
    max_total_cost: float       # 总成本上限(元)
    max_abandon_value: float     # 最多可放弃的货物价值(元)
    
    # AI最优方案需要的资源(对比用)
    ai_required_vehicles: int = 0
    ai_required_warehouses: int = 0
    ai_required_cost: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "max_vehicles": self.max_vehicles,
            "max_warehouses": self.max_warehouses,
            "max_total_cost": self.max_total_cost,
            "max_abandon_value": self.max_abandon_value,
            "ai_required_vehicles": self.ai_required_vehicles,
            "ai_required_warehouses": self.ai_required_warehouses,
            "ai_required_cost": self.ai_required_cost,
            "vehicle_gap": self.ai_required_vehicles - self.max_vehicles,
            "cost_gap": round(self.ai_required_cost - self.max_total_cost, 1),
        }


class BudgetConstraintManager:
    """
    策略三的预算约束生成器
    - 分析AI最优方案需要的资源量
    - 为学生设置约束条件(通常只有AI方案需求的40%-60%)
    """

    def generate_constraint(self, optimal_plan: DecisionPlan,
                             scenario: ScenarioContext,
                             constraint_ratio: float = 0.4) -> BudgetConstraint:
        """
        生成预算约束
        
        Args:
            optimal_plan: AI最优方案
            constraint_ratio: 学生可用资源占AI需求的比例(0.4=只有40%)
        """
        ai_vehicles = optimal_plan.vehicles_used
        ai_warehouses = optimal_plan.warehouses_used
        ai_cost = optimal_plan.total_cost
        
        # 学生可用资源 = AI需求 × ratio (向下取整，至少1)
        student_vehicles = max(1, int(ai_vehicles * constraint_ratio))
        student_warehouses = max(1, int(ai_warehouses * constraint_ratio))
        student_cost = ai_cost * (constraint_ratio + 0.2)  # 成本约束稍宽松
        
        # 可放弃的货物总价值 (总货物价值的30%)
        total_cargo_value = sum(c.value_yuan for c in scenario.cargo_manifest)
        max_abandon = total_cargo_value * 0.3
        
        return BudgetConstraint(
            max_vehicles=student_vehicles,
            max_warehouses=student_warehouses,
            max_total_cost=round(student_cost, 1),
            max_abandon_value=round(max_abandon, 1),
            ai_required_vehicles=ai_vehicles,
            ai_required_warehouses=ai_warehouses,
            ai_required_cost=round(ai_cost, 1),
        )


# ============================================================
# 策略三: 学生方案预算校验
# ============================================================

class BudgetValidator:
    """校验学生方案是否超出预算约束"""

    def validate(self, student_actions: list[dict],
                 budget: BudgetConstraint) -> dict:
        """
        校验学生方案是否在预算范围内
        
        Returns:
            {
                "is_valid": bool,
                "violations": [str],
                "vehicle_usage": int,
                "warehouse_usage": int,
                "estimated_cost": float,
                "abandoned_value": float,
            }
        """
        vehicles_used = set()
        warehouses_used = set()
        total_cost = 0.0
        abandoned_value = 0.0
        violations = []
        
        for action in student_actions:
            if action.get("vehicle_id"):
                vehicles_used.add(action["vehicle_id"])
            if action.get("warehouse_id"):
                warehouses_used.add(action["warehouse_id"])
            
            action_type = action.get("action_type", "")
            if action_type == "abandon":
                abandoned_value += action.get("cargo_value", 0)
            
            # 粗估成本
            if action_type == "reroute":
                route_len = len(action.get("route", []))
                total_cost += route_len * 80
            elif action_type == "warehouse_transfer":
                total_cost += action.get("storage_cost", 100)
            elif action_type == "abandon":
                total_cost += action.get("cargo_value", 0)
        
        if len(vehicles_used) > budget.max_vehicles:
            violations.append(
                f"车辆超出预算: 使用{len(vehicles_used)}辆, "
                f"上限{budget.max_vehicles}辆")
        
        if len(warehouses_used) > budget.max_warehouses:
            violations.append(
                f"仓库超出预算: 使用{len(warehouses_used)}个, "
                f"上限{budget.max_warehouses}个")
        
        if total_cost > budget.max_total_cost:
            violations.append(
                f"成本超出预算: 估计{total_cost:.0f}元, "
                f"上限{budget.max_total_cost:.0f}元")
        
        if abandoned_value > budget.max_abandon_value:
            violations.append(
                f"放弃货物价值过高: {abandoned_value:.0f}元, "
                f"上限{budget.max_abandon_value:.0f}元")
        
        return {
            "is_valid": len(violations) == 0,
            "violations": violations,
            "vehicle_usage": len(vehicles_used),
            "warehouse_usage": len(warehouses_used),
            "estimated_cost": round(total_cost, 1),
            "abandoned_value": round(abandoned_value, 1),
            "budget": budget.to_dict(),
        }


# ============================================================
# 策略总控
# ============================================================

class StrategyController:
    """
    策略总控制器
    - 根据策略模式配置不同的教学场景
    - 提供策略相关的上下文数据
    """

    def __init__(self):
        self.disruption_gen = DisruptionGenerator()
        self.budget_manager = BudgetConstraintManager()
        self.budget_validator = BudgetValidator()

    def get_strategy_context(self, optimal_plan: DecisionPlan,
                              scenario: ScenarioContext) -> dict:
        """
        根据策略模式返回策略上下文数据
        """
        mode = scenario.strategy_config.mode
        
        if mode == StrategyMode.AGENT_ADVERSARIAL:
            # 策略二: 生成隐藏干扰
            disruptions = self.disruption_gen.generate(
                optimal_plan, scenario, count=2)
            return {
                "mode": "agent_adversarial",
                "mode_name": "智能体对抗模式",
                "description": "系统已生成隐藏干扰因素，仅你可见。请审核AI方案并修正。",
                "hidden_disruptions": [d.to_dict() for d in disruptions],
                "ai_plan_visible": True,
                "time_limit": None,
                "budget_constraint": None,
            }
        
        elif mode == StrategyMode.BUDGET_CONSTRAINED:
            # 策略三: 生成预算约束
            budget = self.budget_manager.generate_constraint(
                optimal_plan, scenario, constraint_ratio=0.4)
            return {
                "mode": "budget_constrained",
                "mode_name": "有限预算博弈",
                "description": f"你的资源只有AI方案的{int(0.4*100)}%，必须在受限前提下做取舍。",
                "hidden_disruptions": [],
                "ai_plan_visible": True,
                "time_limit": None,
                "budget_constraint": budget.to_dict(),
            }
        
        else:
            # 策略一: 人机竞速
            return {
                "mode": "time_pressure",
                "mode_name": "人机竞速模式",
                "description": "黄金10分钟倒计时！请先提交你的决策，之后系统将展示AI方案进行对比。",
                "hidden_disruptions": [],
                "ai_plan_visible": False,  # 先隐藏AI方案
                "time_limit": scenario.strategy_config.time_limit_sec,
                "budget_constraint": None,
            }
