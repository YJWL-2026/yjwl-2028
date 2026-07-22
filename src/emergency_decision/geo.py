"""
地理工具 - 距离计算与位置判断
"""

import math


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """计算两点之间的球面距离 (Haversine公式), 单位: 千米"""
    R = 6371.0  # 地球半径(千米)

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(R * c, 2)


def is_in_radius(lat: float, lng: float,
                 center_lat: float, center_lng: float,
                 radius_km: float) -> bool:
    """判断点是否在给定半径范围内"""
    return haversine_distance(lat, lng, center_lat, center_lng) <= radius_km


def distance_to_center(lat: float, lng: float,
                       center_lat: float, center_lng: float) -> float:
    """计算点到中心的距离(千米)"""
    return haversine_distance(lat, lng, center_lat, center_lng)


def road_midpoint_distance(road_mid_lat: float, road_mid_lng: float,
                            center_lat: float, center_lng: float) -> float:
    """计算路段中点到震中的距离(千米)"""
    return haversine_distance(road_mid_lat, road_mid_lng, center_lat, center_lng)
