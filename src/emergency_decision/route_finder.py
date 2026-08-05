"""
路径搜索 - Dijkstra最短路径算法
对应文档: 03-calculation-logic.md Step 4.1

功能:
  - 在灾后路网中寻找最优绕行路径
  - 支持按"成本最低"和"时效最快"两种模式
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from .models import LogisticsNetwork, Road
from .resources import ResourceInventory


@dataclass
class PathResult:
    """路径搜索结果"""
    found: bool
    route: list[str] = field(default_factory=list)  # 节点序列
    roads: list[Road] = field(default_factory=list)  # 经过的路段
    total_distance_km: float = 0.0
    total_time_min: float = 0.0
    total_toll_cost: float = 0.0
    total_risk: float = 0.0
    path_cost: float = 0.0  # 综合路径成本(用于比较)

    @property
    def is_valid(self) -> bool:
        return self.found and len(self.route) >= 2


class RouteFinder:
    """Dijkstra路径搜索器"""

    def __init__(self, network: LogisticsNetwork):
        self.network = network

    def find_shortest_path(self, start_node: str, end_node: str,
                            mode: str = "cost") -> PathResult:
        """
        寻找最优路径

        Args:
            start_node: 起点节点ID
            end_node: 终点节点ID
            mode: "cost"=成本最低, "time"=时效最快, "risk"=风险最低

        Returns:
            PathResult
        """
        if start_node == end_node:
            return PathResult(found=True, route=[start_node])

        # Dijkstra算法
        # 优先队列: (累计权重, 当前节点, 路径节点列表, 路径路段列表)
        # dist: {node_id: (min_weight, path_nodes, path_roads)}
        dist: dict[str, float] = {start_node: 0.0}
        prev_node: dict[str, str] = {}
        prev_road: dict[str, Road] = {}
        visited: set[str] = set()
        pq: list[tuple[float, str]] = [(0.0, start_node)]

        while pq:
            current_dist, current = heapq.heappop(pq)

            if current in visited:
                continue
            visited.add(current)

            if current == end_node:
                break

            for neighbor_id, road in self.network.get_neighbors(current):
                if not road.is_passable:
                    continue

                edge_weight = self._get_edge_weight(road, mode)
                new_dist = current_dist + edge_weight

                if neighbor_id not in dist or new_dist < dist[neighbor_id]:
                    dist[neighbor_id] = new_dist
                    prev_node[neighbor_id] = current
                    prev_road[neighbor_id] = road
                    heapq.heappush(pq, (new_dist, neighbor_id))

        # 回溯路径
        if end_node not in visited:
            return PathResult(found=False)

        route = []
        roads = []
        node = end_node
        while node != start_node:
            route.append(node)
            roads.append(prev_road[node])
            node = prev_node[node]
        route.append(start_node)
        route.reverse()
        roads.reverse()

        # 计算路径指标
        return self._build_path_result(route, roads)

    def find_best_and_fastest(self, start_node: str,
                                end_node: str) -> tuple[PathResult, PathResult]:
        """同时找成本最低和时效最快的路径"""
        best_cost = self.find_shortest_path(start_node, end_node, "cost")
        fastest = self.find_shortest_path(start_node, end_node, "time")
        return best_cost, fastest

    def _get_edge_weight(self, road: Road, mode: str) -> float:
        """获取路段权重 (越小越好)"""
        if mode == "time":
            return road.actual_travel_time_min
        elif mode == "risk":
            return road.risk_score * 100
        else:  # cost
            # 成本 = 距离*油耗 + 过路费 + 风险惩罚
            fuel = road.distance_km * road.fuel_cost_per_km
            return fuel + road.toll_cost + road.risk_score * 50

    def _build_path_result(self, route: list[str],
                            roads: list[Road]) -> PathResult:
        """构建路径结果"""
        total_dist = sum(r.distance_km for r in roads)
        total_time = sum(r.actual_travel_time_min for r in roads)
        total_toll = sum(r.toll_cost for r in roads)
        total_risk = sum(r.risk_score for r in roads)
        total_fuel = sum(r.distance_km * r.fuel_cost_per_km for r in roads)

        path_cost = total_fuel + total_toll + total_risk * 50

        return PathResult(
            found=True,
            route=route,
            roads=roads,
            total_distance_km=round(total_dist, 1),
            total_time_min=round(total_time, 1),
            total_toll_cost=round(total_toll, 1),
            total_risk=round(total_risk, 2),
            path_cost=round(path_cost, 1),
        )
