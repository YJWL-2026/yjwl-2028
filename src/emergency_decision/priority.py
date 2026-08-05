"""
货物优先级排序 - Step 2
对应文档: 03-calculation-logic.md Step 2

排序规则 (多级排序):
  1. priority_level: P1 > P2 > P3
  2. cargo_type: medical > supplies > urgent > normal
  3. deadline 紧急度: 时间越短越优先
  4. value_yuan: 价值越高越优先
"""

from __future__ import annotations

from .models import Cargo, CargoType, PriorityLevel

# 货物类型排序权重
CARGO_TYPE_ORDER = {
    CargoType.MEDICAL: 0,
    CargoType.SUPPLIES: 1,
    CargoType.URGENT: 2,
    CargoType.PERISHABLE: 3,
    CargoType.HAZARDOUS: 4,
    CargoType.NORMAL: 5,
}

# 优先级排序权重
PRIORITY_ORDER = {
    PriorityLevel.P1: 0,
    PriorityLevel.P2: 1,
    PriorityLevel.P3: 2,
}


def auto_assign_priority(cargo: Cargo) -> Cargo:
    """自动判定货物优先级 (教师可覆盖)"""
    if cargo.cargo_type in (CargoType.MEDICAL, CargoType.SUPPLIES):
        cargo.priority_level = PriorityLevel.P1
    elif (cargo.cargo_type == CargoType.URGENT or
          cargo.value_yuan > 50000):
        cargo.priority_level = PriorityLevel.P2
    else:
        cargo.priority_level = PriorityLevel.P3
    return cargo


def sort_cargo_by_priority(cargo_list: list[Cargo]) -> list[Cargo]:
    """按优先级排序货物, 返回保障队列 (高 -> 低)"""
    def sort_key(c: Cargo) -> tuple:
        return (
            PRIORITY_ORDER.get(c.priority_level, 9),
            CARGO_TYPE_ORDER.get(c.cargo_type, 9),
            c.deadline_urgency_hours,
            -c.value_yuan,  # 价值越高排越前
        )

    return sorted(cargo_list, key=sort_key)


def get_protection_status(cargo: Cargo) -> str:
    """获取货物保障状态标记"""
    if cargo.priority_level == PriorityLevel.P1:
        return "must_deliver"
    elif cargo.priority_level == PriorityLevel.P2:
        return "preferred"
    else:
        return "optional"


def get_blocked_cargo_sorted(cargo_list: list[Cargo],
                              blocked_ids: list[str]) -> list[Cargo]:
    """从全部货物中筛选受阻货物并按优先级排序"""
    blocked_set = set(blocked_ids)
    blocked_cargo = [c for c in cargo_list if c.cargo_id in blocked_set]
    return sort_cargo_by_priority(blocked_cargo)
