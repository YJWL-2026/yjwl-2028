# -*- coding: utf-8 -*-
"""
实时灾害数据模块
对接三个公开数据源：
  1. 地震 - 中国地震台网（经 wolfx.jp 中转，JSON格式，无需token）
  2. 台风 - 中央气象台台风网（JSONP格式，无需token）
  3. 天气预警 - 暴雨/洪水/地质灾害/山洪预警（多源降级策略）
"""

import json
import re
import time
import urllib.request
import urllib.parse
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any


# ============================================================
# 数据结构
# ============================================================

@dataclass
class EarthquakeInfo:
    """地震信息"""
    event_id: str
    time: str               # 发震时间
    location: str           # 震源位置
    magnitude: float        # 震级
    depth: float            # 震源深度(km)
    latitude: float         # 纬度
    longitude: float        # 经度
    intensity: str          # 烈度
    eq_type: str = ""       # automatic(自动) / reviewed(正式)
    report_time: str = ""   # 报告时间

    @classmethod
    def from_api(cls, data: dict) -> "EarthquakeInfo":
        return cls(
            event_id=data.get("EventID", ""),
            time=data.get("time", ""),
            location=data.get("location", data.get("placeName", "")),
            magnitude=float(data.get("magnitude", 0) or 0),
            depth=float(data.get("depth", 0) or 0),
            latitude=float(data.get("latitude", 0) or 0),
            longitude=float(data.get("longitude", 0) or 0),
            intensity=str(data.get("intensity", "")),
            eq_type=data.get("type", ""),
            report_time=data.get("ReportTime", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TyphoonInfo:
    """台风信息"""
    typhoon_id: int          # NMC内部ID
    english_name: str        # 英文名
    chinese_name: str        # 中文名
    typhoon_no: str          # 编号
    full_no: str             # 完整编号
    status: str = ""         # start(活跃) / stop(停编)
    name_origin: str = ""    # 名称来源
    detail: Optional[dict] = None  # 路径详情(延迟加载)

    @classmethod
    def from_list_item(cls, item: list) -> "TyphoonInfo":
        return cls(
            typhoon_id=item[0] if len(item) > 0 else 0,
            english_name=item[1] if len(item) > 1 else "",
            chinese_name=item[2] if len(item) > 2 else "",
            typhoon_no=str(item[3]) if len(item) > 3 else "",
            full_no=str(item[4]) if len(item) > 4 else "",
            status=item[7] if len(item) > 7 else "",
            name_origin=item[6] if len(item) > 6 else "",
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class TyphoonTrackPoint:
    """台风路径点"""
    time: str           # 时间
    lat: float          # 纬度
    lon: float          # 经度
    pressure: int       # 中心气压(hPa)
    wind_speed: int     # 最大风速(m/s)
    move_speed: int = 0 # 移速(km/h)
    move_dir: str = ""  # 移向
    level: str = ""     # 强度等级
    is_forecast: bool = False  # 是否预报点


@dataclass
class WeatherAlert:
    """天气预警信息"""
    alert_id: str
    title: str           # 预警标题
    alert_type: str      # 预警类型(暴雨/洪水/地质灾害等)
    level: str           # 预警等级(红/橙/黄/蓝)
    province: str = ""   # 发布省份
    publisher: str = ""   # 发布单位
    publish_time: str = ""  # 发布时间
    effective: str = ""    # 生效时间
    expires: str = ""      # 失效时间
    detail: str = ""       # 预警内容
    lat: float = 0.0       # 纬度
    lng: float = 0.0       # 经度

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# HTTP 工具
# ============================================================

def _http_get(url: str, timeout: int = 10, encoding: str = "utf-8") -> str:
    """发起HTTP GET请求"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        return data.decode(encoding, errors="replace")


def _parse_jsonp(text: str) -> Any:
    """解析JSONP响应，提取其中的JSON数据。
    支持单括号 callback({...}) 和双括号 callback(({...})) 格式。"""
    # 找到第一个 ( 和最后一个 )
    first_brace = text.find("{")
    first_bracket = text.find("[")
    start = -1
    if first_brace >= 0 and (first_bracket < 0 or first_brace < first_bracket):
        start = first_brace
    elif first_bracket >= 0:
        start = first_bracket
    if start < 0:
        raise ValueError("JSONP响应中未找到JSON起始符")

    # 从末尾找最后一个 } 或 ]
    last_brace = text.rfind("}")
    last_bracket = text.rfind("]")
    end = max(last_brace, last_bracket)
    if end < 0:
        raise ValueError("JSONP响应中未找到JSON结束符")

    json_str = text[start:end + 1]
    return json.loads(json_str)


# ============================================================
# 地震数据获取
# ============================================================

class EarthquakeDataFetcher:
    """中国地震台网实时地震数据获取"""

    API_URL = "https://api.wolfx.jp/cenc_eqlist.json"

    # 简单内存缓存
    _cache: Optional[List[EarthquakeInfo]] = None
    _cache_time: float = 0
    CACHE_TTL = 60  # 缓存60秒

    @classmethod
    def fetch(cls, min_magnitude: float = 0.0, limit: int = 50) -> List[EarthquakeInfo]:
        """获取最新地震列表

        Args:
            min_magnitude: 最小震级过滤
            limit: 返回条数上限

        Returns:
            地震信息列表，按时间倒序
        """
        # 检查缓存
        now = time.time()
        if cls._cache and (now - cls._cache_time) < cls.CACHE_TTL:
            results = cls._cache
        else:
            try:
                raw = _http_get(cls.API_URL, timeout=15)
                data = json.loads(raw)
                results = []
                # data 是 {No1: {...}, No2: {...}, ..., md5: "..."}
                for key, val in data.items():
                    if key == "md5" or not isinstance(val, dict):
                        continue
                    if "magnitude" not in val:
                        continue
                    results.append(EarthquakeInfo.from_api(val))
                cls._cache = results
                cls._cache_time = now
            except Exception as e:
                print(f"[EarthquakeDataFetcher] 获取地震数据失败: {e}")
                if cls._cache:
                    results = cls._cache
                else:
                    results = []

        # 按时间倒序排序（最新的排前面）
        results = sorted(results, key=lambda e: e.time, reverse=True)

        # 过滤
        filtered = [e for e in results if e.magnitude >= min_magnitude]
        return filtered[:limit]

    @classmethod
    def fetch_as_dict(cls, min_magnitude: float = 0.0, limit: int = 50) -> List[dict]:
        """获取地震列表(dict格式)"""
        return [e.to_dict() for e in cls.fetch(min_magnitude, limit)]

    @classmethod
    def find_by_id(cls, event_id: str) -> Optional[EarthquakeInfo]:
        """按EventID查找单条地震"""
        for eq in cls.fetch():
            if eq.event_id == event_id:
                return eq
        return None


# ============================================================
# 台风数据获取
# ============================================================

class TyphoonDataFetcher:
    """中央气象台台风网实时台风数据获取"""

    LIST_URL = "http://typhoon.nmc.cn/weatherservice/typhoon/jsons/list_default"
    DETAIL_URL = "http://typhoon.nmc.cn/weatherservice/typhoon/jsons/view_{typhoon_id}"

    _list_cache: Optional[List[TyphoonInfo]] = None
    _list_cache_time: float = 0
    _detail_cache: Dict[int, dict] = {}
    CACHE_TTL = 300  # 列表缓存5分钟

    @classmethod
    def fetch_list(cls, year: Optional[int] = None) -> List[TyphoonInfo]:
        """获取台风列表

        Args:
            year: 年份过滤(如2026)，None则返回全部

        Returns:
            台风信息列表
        """
        now = time.time()
        if cls._list_cache and (now - cls._list_cache_time) < cls.CACHE_TTL:
            results = cls._list_cache
        else:
            try:
                ts = int(time.time() * 1000)
                url = f"{cls.LIST_URL}?t={ts}&callback=typhoon"
                raw = _http_get(url, timeout=15)
                data = _parse_jsonp(raw)
                typhoon_list = data.get("typhoonList", [])
                results = [TyphoonInfo.from_list_item(item) for item in typhoon_list]
                cls._list_cache = results
                cls._list_cache_time = now
            except Exception as e:
                print(f"[TyphoonDataFetcher] 获取台风列表失败: {e}")
                if cls._list_cache:
                    results = cls._list_cache
                else:
                    results = []

        if year:
            results = [t for t in results if str(year) in t.full_no]

        return results

    @classmethod
    def fetch_list_as_dict(cls, year: Optional[int] = None) -> List[dict]:
        """获取台风列表(dict格式)"""
        return [
            {
                "typhoon_id": t.typhoon_id,
                "english_name": t.english_name,
                "chinese_name": t.chinese_name,
                "typhoon_no": t.typhoon_no,
                "full_no": t.full_no,
                "status": t.status,
                "name_origin": t.name_origin[:50] if t.name_origin else "",
            }
            for t in cls.fetch_list(year)
        ]

    @classmethod
    def fetch_detail(cls, typhoon_id: int) -> Optional[dict]:
        """获取台风路径详情

        NMC API返回格式（数组结构）：
        data["typhoon"] = [
            [0] id, [1] en_name, [2] cn_name, [3] typhoon_no, [4] full_no,
            [5] ?, [6] name_origin, [7] status,
            [8] [  # track_points数组
                [
                    [0] point_id, [1] time_str(yyyyMMddHHmm), [2] timestamp_ms,
                    [3] level, [4] lng, [5] lat, [6] pressure, [7] wind_speed,
                    [8] move_dir, [9] move_speed, [10] wind_radii,
                    [11] {  # 预报路径
                        "BABJ": [[hour_offset, time_str, lng, lat, pressure, wind_speed, source, level], ...]
                    }
                ], ...
            ]
        ]

        Returns:
            包含路径点列表的字典
        """
        # 检查缓存
        if typhoon_id in cls._detail_cache:
            return cls._detail_cache[typhoon_id]

        try:
            ts = int(time.time() * 1000)
            url = cls.DETAIL_URL.format(typhoon_id=typhoon_id)
            url = f"{url}?t={ts}&callback=typhoon"
            raw = _http_get(url, timeout=15)
            data = _parse_jsonp(raw)

            typhoon_arr = data.get("typhoon", [])
            if not isinstance(typhoon_arr, list) or len(typhoon_arr) < 9:
                raise ValueError("台风数据格式异常")

            # 基本信息（数组索引）
            en_name = str(typhoon_arr[1]) if len(typhoon_arr) > 1 else ""
            cn_name = str(typhoon_arr[2]) if len(typhoon_arr) > 2 else ""
            status = str(typhoon_arr[7]) if len(typhoon_arr) > 7 else ""

            # 时间格式化：yyyyMMddHHmm → yyyy-MM-dd HH:mm
            def _fmt_time(t_str: str) -> str:
                t_str = str(t_str)
                if len(t_str) >= 12:
                    return f"{t_str[:4]}-{t_str[4:6]}-{t_str[6:8]} {t_str[8:10]}:{t_str[10:12]}"
                return t_str

            # 强度等级中文映射
            LEVEL_MAP = {
                "TS": "热带风暴", "STS": "强热带风暴", "TY": "台风",
                "STY": "强台风", "SuperTY": "超强台风",
                "TD": "热带低压", "EX": "温带气旋", "DB": "热带扰动",
            }

            # 历史路径点
            track_raw = typhoon_arr[8] if len(typhoon_arr) > 8 else []
            track_points = []
            forecast_points = []
            seen_forecast_hours = set()

            for tp in track_raw:
                if not isinstance(tp, list) or len(tp) < 10:
                    continue
                point = TyphoonTrackPoint(
                    time=_fmt_time(tp[1]),
                    lat=float(tp[5] or 0),
                    lon=float(tp[4] or 0),
                    pressure=int(tp[6] or 0),
                    wind_speed=int(tp[7] or 0),
                    move_speed=int(tp[9] or 0),
                    move_dir=str(tp[8] or ""),
                    level=LEVEL_MAP.get(str(tp[3]), str(tp[3] or "")),
                    is_forecast=False,
                )
                track_points.append(point)

                # 解析预报路径（在最后一个元素中，key为预报机构如"BABJ"）
                if len(tp) > 11 and isinstance(tp[-1], dict):
                    for fc_center, fc_list in tp[-1].items():
                        for fp in fc_list:
                            if not isinstance(fp, list) or len(fp) < 8:
                                continue
                            hour_offset = fp[0]
                            # 去重（同一时间点的预报只取第一次出现的）
                            if hour_offset in seen_forecast_hours:
                                continue
                            seen_forecast_hours.add(hour_offset)
                            fc_point = TyphoonTrackPoint(
                                time=_fmt_time(fp[1]),
                                lat=float(fp[3] or 0),
                                lon=float(fp[2] or 0),
                                pressure=int(fp[4] or 0),
                                wind_speed=int(fp[5] or 0),
                                level=LEVEL_MAP.get(str(fp[7]), str(fp[7] or "")),
                                is_forecast=True,
                            )
                            forecast_points.append(fc_point)

            # 最新/当前位置
            current_lat = track_points[-1].lat if track_points else 0
            current_lng = track_points[-1].lon if track_points else 0
            current_level = track_points[-1].level if track_points else ""
            current_wind = track_points[-1].wind_speed if track_points else 0
            current_pressure = track_points[-1].pressure if track_points else 0

            result = {
                "typhoon_id": typhoon_id,
                "english_name": en_name,
                "chinese_name": cn_name,
                "status": status,
                "start_time": track_points[0].time if track_points else "",
                "stop_time": track_points[-1].time if track_points else "",
                "current_lat": current_lat,
                "current_lng": current_lng,
                "current_level": current_level,
                "current_wind_speed": current_wind,
                "current_pressure": current_pressure,
                "track_points": [tp.__dict__ for tp in track_points],
                "forecast_points": [tp.__dict__ for tp in forecast_points],
            }

            cls._detail_cache[typhoon_id] = result
            return result

        except Exception as e:
            print(f"[TyphoonDataFetcher] 获取台风详情失败: {e}")
            import traceback
            traceback.print_exc()
            return None


# ============================================================
# 天气预警数据获取（暴雨/洪水/地质灾害/山洪）
# ============================================================

# 关注的灾害类型关键词
DISASTER_KEYWORDS = {
    "暴雨": ["暴雨"],
    "洪水": ["洪水", "洪涝", "防汛"],
    "地质灾害": ["地质", "山体滑坡", "泥石流", "崩塌"],
    "山洪": ["山洪"],
    "台风": ["台风"],
    "大风": ["大风", "狂风"],
    "雷电": ["雷电", "雷暴"],
    "高温": ["高温"],
    "暴雪": ["暴雪", "雪灾"],
}

# 省会城市坐标(用于预警地图标注)
CITY_COORDS = {
    "北京": (39.90, 116.41), "天津": (39.08, 117.20), "上海": (31.23, 121.47),
    "重庆": (29.56, 106.55), "广州": (23.13, 113.26), "深圳": (22.54, 114.06),
    "成都": (30.67, 104.07), "杭州": (30.27, 120.15), "武汉": (30.59, 114.31),
    "西安": (34.27, 108.95), "南京": (32.06, 118.80), "长沙": (28.23, 112.94),
    "郑州": (34.75, 113.65), "济南": (36.65, 117.00), "合肥": (31.82, 117.23),
    "福州": (26.07, 119.30), "南昌": (28.68, 115.86), "南宁": (22.82, 108.37),
    "贵阳": (26.65, 106.71), "昆明": (25.04, 102.71), "拉萨": (29.65, 91.13),
    "太原": (37.87, 112.55), "石家庄": (38.04, 114.51), "呼和浩特": (40.82, 111.67),
    "哈尔滨": (45.80, 126.53), "长春": (43.82, 125.32), "沈阳": (41.80, 123.43),
    "兰州": (36.06, 103.82), "银川": (38.47, 106.23), "西宁": (36.62, 101.78),
    "乌鲁木齐": (43.83, 87.62), "海口": (20.02, 110.35), "台北": (25.03, 121.57),
    "香港": (22.32, 114.17), "澳门": (22.20, 113.55),
}

def _match_city(text: str) -> tuple:
    """从预警文本中匹配城市坐标"""
    for city, (lat, lng) in CITY_COORDS.items():
        if city in text:
            return lat, lng
    # 尝试匹配省份名
    PROVINCE_MAP = {
        "河北": (38.04, 114.51), "山西": (37.87, 112.55), "辽宁": (41.80, 123.43),
        "吉林": (43.82, 125.32), "黑龙江": (45.80, 126.53), "江苏": (32.06, 118.80),
        "浙江": (30.27, 120.15), "安徽": (31.82, 117.23), "福建": (26.07, 119.30),
        "江西": (28.68, 115.86), "山东": (36.65, 117.00), "河南": (34.75, 113.65),
        "湖北": (30.59, 114.31), "湖南": (28.23, 112.94), "广东": (23.13, 113.26),
        "海南": (20.02, 110.35), "四川": (30.67, 104.07), "贵州": (26.65, 106.71),
        "云南": (25.04, 102.71), "陕西": (34.27, 108.95), "甘肃": (36.06, 103.82),
        "青海": (36.62, 101.78), "广西": (22.82, 108.37), "内蒙古": (40.82, 111.67),
        "西藏": (29.65, 91.13), "宁夏": (38.47, 106.23), "新疆": (43.83, 87.62),
    }
    for prov, (lat, lng) in PROVINCE_MAP.items():
        if prov in text:
            return lat, lng
    return 35.0, 105.0  # 全国中心


# ============================================================
# 省份 → 车牌前缀映射
# ============================================================
PROVINCE_TO_PLATE: dict[str, str] = {
    "北京": "京", "天津": "津", "上海": "沪", "重庆": "渝",
    "河北": "冀", "山西": "晋", "辽宁": "辽", "吉林": "吉", "黑龙江": "黑",
    "江苏": "苏", "浙江": "浙", "安徽": "皖", "福建": "闽", "江西": "赣", "山东": "鲁",
    "河南": "豫", "湖北": "鄂", "湖南": "湘", "广东": "粤", "广西": "桂", "海南": "琼",
    "四川": "川", "贵州": "贵", "云南": "云", "西藏": "藏",
    "陕西": "陕", "甘肃": "甘", "青海": "青", "宁夏": "宁", "新疆": "新",
    "内蒙古": "蒙", "香港": "港", "澳门": "澳", "台湾": "台",
}

# 省份→省会/典型城市坐标（用于从坐标反查省份）
PROVINCE_CAPITAL_COORDS: dict[str, tuple[float, float]] = {
    "北京": (39.90, 116.40), "天津": (39.13, 117.19), "上海": (31.23, 121.47),
    "重庆": (29.56, 106.55), "河北": (38.04, 114.51), "山西": (37.87, 112.55),
    "辽宁": (41.80, 123.43), "吉林": (43.82, 125.32), "黑龙江": (45.80, 126.53),
    "江苏": (32.06, 118.80), "浙江": (30.27, 120.15), "安徽": (31.82, 117.23),
    "福建": (26.07, 119.30), "江西": (28.68, 115.86), "山东": (36.65, 117.00),
    "河南": (34.75, 113.65), "湖北": (30.59, 114.31), "湖南": (28.23, 112.94),
    "广东": (23.13, 113.26), "广西": (22.82, 108.37), "海南": (20.02, 110.35),
    "四川": (30.67, 104.07), "贵州": (26.65, 106.71), "云南": (25.04, 102.71),
    "西藏": (29.65, 91.13), "陕西": (34.27, 108.95), "甘肃": (36.06, 103.82),
    "青海": (36.62, 101.78), "宁夏": (38.47, 106.23), "新疆": (43.83, 87.62),
    "内蒙古": (40.82, 111.67), "香港": (22.32, 114.17), "澳门": (22.20, 113.55),
    "台湾": (25.03, 121.57),
}


def get_license_plate_prefix(province: str) -> str:
    """根据省份名获取车牌前缀（支持简称模糊匹配）

    Args:
        province: 省份名，如 "河南"、"四川"、"闽" 等

    Returns:
        车牌前缀，如 "豫"、"川"、"闽"。未匹配时返回 "豫"
    """
    if not province:
        return "豫"

    # 1. 如果传入的已经是简称（单个字），尝试验证
    if len(province) == 1:
        # 查找该简称是否在映射表中
        for full_name, prefix in PROVINCE_TO_PLATE.items():
            if prefix == province:
                return prefix
        # 也检查是否本身就是全名中的单字缩写
        for full_name in PROVINCE_TO_PLATE:
            if province in full_name:
                return PROVINCE_TO_PLATE[full_name]

    # 2. 精确匹配全名
    if province in PROVINCE_TO_PLATE:
        return PROVINCE_TO_PLATE[province]

    # 3. 模糊匹配：检查省份名是否包含传入的字符串（如 "河南省" 匹配 "河南"）
    for full_name, prefix in PROVINCE_TO_PLATE.items():
        if full_name in province or province in full_name:
            return prefix

    return "豫"


def get_province_from_location(location_text: str) -> str:
    """从位置文本中提取省份名

    Args:
        location_text: 如 "四川阿坝州汶川县"、"云南普洱市墨江县"

    Returns:
        省份名，如 "四川"、"云南"
    """
    if not location_text:
        return ""
    for full_name in PROVINCE_TO_PLATE:
        if full_name in location_text:
            return full_name
    return ""


def get_province_from_coords(lat: float, lng: float) -> str:
    """根据坐标查找最近省份（简易实现：找最近省会）

    Args:
        lat: 纬度
        lng: 经度

    Returns:
        省份名
    """
    import math
    best_prov = ""
    best_dist = float("inf")
    for prov, (p_lat, p_lng) in PROVINCE_CAPITAL_COORDS.items():
        dist = math.sqrt((lat - p_lat) ** 2 + (lng - p_lng) ** 2)
        if dist < best_dist:
            best_dist = dist
            best_prov = prov
    return best_prov


def _parse_alert_level(text: str) -> str:
    """从文本中解析预警等级"""
    if "红色" in text or "红" in text:
        return "红色"
    if "橙色" in text or "橙" in text:
        return "橙色"
    if "黄色" in text or "黄" in text:
        return "黄色"
    if "蓝色" in text or "蓝" in text:
        return "蓝色"
    return ""


def _parse_alert_type(text: str) -> str:
    """从文本中解析预警类型"""
    for category, keywords in DISASTER_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return category
    return "其他"


class WeatherAlertFetcher:
    """天气预警数据获取器

    多源策略：
    1. 尝试从中国天气网预警频道抓取
    2. 降级到内置示例数据（基于真实场景的参考数据）
    """

    # 内置参考预警数据（基于真实气象灾害场景）
    # 日期动态生成，使用当前日期确保时效性
    @staticmethod
    def _build_sample_alerts() -> List["WeatherAlert"]:
        """构建参考预警数据（日期使用当前时间）"""
        today = datetime.now()
        date_str = today.strftime("%Y-%m-%d")
        from datetime import timedelta
        tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")

        return [
            WeatherAlert(
                alert_id="SAMPLE-001",
                title=f"河南省气象台发布暴雨红色预警信号",
                alert_type="暴雨",
                level="红色",
                province="河南",
                publisher="河南省气象台",
                publish_time=f"{date_str} 08:00:00",
                effective=f"{date_str} 08:00:00",
                expires=f"{tomorrow} 08:00:00",
                detail=f"河南省气象台{today.month}月{today.day}日8时发布暴雨红色预警信号：预计未来24小时内，郑州、开封、商丘等地降雨量将达200毫米以上，请注意防范城市内涝、山洪及地质灾害。",
                lat=34.75, lng=113.65,
            ),
            WeatherAlert(
                alert_id="SAMPLE-002",
                title="四川省国土资源厅联合气象局发布地质灾害气象风险预警",
                alert_type="地质灾害",
                level="橙色",
                province="四川",
                publisher="四川省国土资源厅",
                publish_time=f"{date_str} 16:00:00",
                effective=f"{date_str} 16:00:00",
                expires=f"{tomorrow} 16:00:00",
                detail=f"预计未来24小时，阿坝州、甘孜州、凉山州等地发生山体滑坡、泥石流等地质灾害的风险较高(橙色预警)，请加强巡查监测。",
                lat=30.67, lng=104.07,
            ),
            WeatherAlert(
                alert_id="SAMPLE-003",
                title="福建省水利厅发布山洪灾害气象预警",
                alert_type="山洪",
                level="黄色",
                province="福建",
                publisher="福建省水利厅",
                publish_time=f"{date_str} 10:00:00",
                effective=f"{date_str} 10:00:00",
                expires=f"{tomorrow} 10:00:00",
                detail=f"预计未来24小时，南平、三明、龙岩等地可能发生山洪灾害，请注意防范。",
                lat=26.07, lng=119.30,
            ),
            WeatherAlert(
                alert_id="SAMPLE-004",
                title="湖南省气象台发布暴雨橙色预警信号",
                alert_type="暴雨",
                level="橙色",
                province="湖南",
                publisher="湖南省气象台",
                publish_time=f"{date_str} 14:30:00",
                effective=f"{date_str} 14:30:00",
                expires=f"{tomorrow} 14:30:00",
                detail=f"预计未来3小时，长沙、株洲、湘潭降雨量将达50毫米以上，请注意防范城乡积涝及山洪。",
                lat=28.23, lng=112.94,
            ),
            WeatherAlert(
                alert_id="SAMPLE-005",
                title="江西省水文局发布洪水蓝色预警",
                alert_type="洪水",
                level="蓝色",
                province="江西",
                publisher="江西省水文局",
                publish_time=f"{date_str} 09:00:00",
                effective=f"{date_str} 09:00:00",
                expires=f"{tomorrow} 09:00:00",
                detail=f"鄱阳湖水位持续上涨，已接近警戒水位，沿湖地区请注意防汛。",
                lat=28.68, lng=115.86,
            ),
            WeatherAlert(
                alert_id="SAMPLE-006",
                title="广东省气象台发布暴雨黄色预警信号",
                alert_type="暴雨",
                level="黄色",
                province="广东",
                publisher="广东省气象台",
                publish_time=f"{date_str} 11:00:00",
                effective=f"{date_str} 11:00:00",
                expires=f"{tomorrow} 11:00:00",
                detail=f"预计未来6小时，广州、深圳、东莞等地有强降雨，伴有短时大风，请注意防御。",
                lat=23.13, lng=113.26,
            ),
            WeatherAlert(
                alert_id="SAMPLE-007",
                title="云南省自然资源厅发布地质灾害气象风险黄色预警",
                alert_type="地质灾害",
                level="黄色",
                province="云南",
                publisher="云南省自然资源厅",
                publish_time=f"{date_str} 15:00:00",
                effective=f"{date_str} 15:00:00",
                expires=f"{tomorrow} 15:00:00",
                detail=f"受持续降雨影响，昭通、曲靖、昆明等地的地质灾害风险较高，请加强巡查。",
                lat=25.04, lng=102.71,
            ),
            WeatherAlert(
                alert_id="SAMPLE-008",
                title="甘肃省水利厅联合气象局发布山洪灾害气象预警",
                alert_type="山洪",
                level="橙色",
                province="甘肃",
                publisher="甘肃省水利厅",
                publish_time=f"{date_str} 12:00:00",
                effective=f"{date_str} 12:00:00",
                expires=f"{tomorrow} 12:00:00",
                detail=f"预计未来12小时，天水、陇南、定西等地发生山洪灾害可能性大，请做好防范。",
                lat=36.06, lng=103.82,
            ),
        ]

    _cache: Optional[List[WeatherAlert]] = None
    _cache_time: float = 0
    CACHE_TTL = 300

    @classmethod
    def fetch(cls, alert_type: Optional[str] = None) -> List[WeatherAlert]:
        """获取天气预警列表

        Args:
            alert_type: 筛选预警类型(暴雨/洪水/地质灾害/山洪等)，None则返回全部

        Returns:
            天气预警信息列表
        """
        now = time.time()
        if cls._cache and (now - cls._cache_time) < cls.CACHE_TTL:
            results = cls._cache
        else:
            results = cls._fetch_from_sources()
            cls._cache = results
            cls._cache_time = now

        if alert_type:
            results = [a for a in results if a.alert_type == alert_type]

        return results

    @classmethod
    def _fetch_from_sources(cls) -> List[WeatherAlert]:
        """多源数据获取策略"""
        # 源1: 尝试从中国天气网抓取
        alerts = cls._try_weather_com_cn()
        if alerts:
            return alerts

        # 源2: 降级到参考数据
        print("[WeatherAlertFetcher] 使用参考预警数据")
        return cls._build_sample_alerts()

    @classmethod
    def _try_weather_com_cn(cls) -> List[WeatherAlert]:
        """尝试从中国天气网预警频道抓取"""
        try:
            url = "http://www.weather.com.cn/alarm/"
            html = _http_get(url, timeout=10)
            # 尝试从HTML中提取预警信息
            alerts = []
            # 天气网预警页面使用JS动态加载，HTML中可能没有结构化数据
            # 尝试正则匹配预警标题
            pattern = r'发布([^<]*(?:暴雨|洪水|地质|山洪|台风|大风|雷电|高温|暴雪)[^<]*)预警'
            matches = re.findall(pattern, html)
            seen = set()
            for i, match in enumerate(matches):
                title = match.strip()
                if title in seen:
                    continue
                seen.add(title)
                lat, lng = _match_city(title)
                alerts.append(WeatherAlert(
                    alert_id=f"WC-{i:03d}",
                    title=title + "预警信号",
                    alert_type=_parse_alert_type(title),
                    level=_parse_alert_level(title),
                    province="",
                    publisher="",
                    publish_time="",
                    detail=title,
                    lat=lat, lng=lng,
                ))
            if alerts:
                return alerts
        except Exception as e:
            print(f"[WeatherAlertFetcher] 天气网抓取失败: {e}")

        return []

    @classmethod
    def fetch_as_dict(cls, alert_type: Optional[str] = None) -> List[dict]:
        """获取预警列表(dict格式)"""
        return [a.to_dict() for a in cls.fetch(alert_type)]

    @classmethod
    def get_disaster_types(cls) -> List[str]:
        """获取支持的灾害类型列表"""
        return list(DISASTER_KEYWORDS.keys())


# ============================================================
# 真实地震导入为场景
# ============================================================

def earthquake_to_scenario_params(eq: EarthquakeInfo) -> dict:
    """将真实地震信息转换为场景参数(用于生成教学场景)

    根据地震震级自动计算影响半径、生成节点等
    """
    # 震级→影响半径估算(km)
    if eq.magnitude >= 7.0:
        radius = 200
    elif eq.magnitude >= 6.0:
        radius = 120
    elif eq.magnitude >= 5.0:
        radius = 80
    elif eq.magnitude >= 4.0:
        radius = 50
    else:
        radius = 30

    # 震级→预计影响描述
    if eq.magnitude >= 7.0:
        severity = "大地震，影响范围广"
    elif eq.magnitude >= 6.0:
        severity = "强震，影响范围较大"
    elif eq.magnitude >= 5.0:
        severity = "中强震，局部影响明显"
    elif eq.magnitude >= 4.0:
        severity = "中等地震，影响有限"
    else:
        severity = "小震，影响较小"

    # 从震中位置提取省份
    province = get_province_from_location(eq.location) or get_province_from_coords(eq.latitude, eq.longitude)

    return {
        "source": "中国地震台网实时数据",
        "event_id": eq.event_id,
        "epicenter": eq.location,
        "latitude": eq.latitude,
        "longitude": eq.longitude,
        "magnitude": eq.magnitude,
        "depth_km": eq.depth,
        "intensity": eq.intensity,
        "influence_radius_km": radius,
        "severity": severity,
        "time": eq.time,
        "report_time": eq.report_time,
        "eq_type": "正式" if eq.eq_type == "reviewed" else "自动速报",
        "province": province,
    }


def typhoon_to_scenario_params(detail: dict) -> dict:
    """将台风详情转换为场景参数"""
    wind_speed = detail.get("current_wind_speed", 0)
    if wind_speed >= 51:
        radius = 400
        severity = "超强台风，影响范围极广"
    elif wind_speed >= 37:
        radius = 300
        severity = "强台风，影响范围广"
    elif wind_speed >= 25:
        radius = 200
        severity = "台风，影响范围较大"
    else:
        radius = 150
        severity = "热带风暴，局部影响"

    # 根据台风当前位置坐标反查省份
    province = get_province_from_coords(
        detail.get("current_lat", 0),
        detail.get("current_lng", 0),
    )

    return {
        "source": "中央气象台台风网实时数据",
        "typhoon_id": detail.get("typhoon_id"),
        "chinese_name": detail.get("chinese_name", ""),
        "english_name": detail.get("english_name", ""),
        "latitude": detail.get("current_lat", 0),
        "longitude": detail.get("current_lng", 0),
        "wind_speed": wind_speed,
        "pressure": detail.get("current_pressure", 0),
        "influence_radius_km": radius,
        "severity": severity,
        "track_points": len(detail.get("track_points", [])),
        "start_time": detail.get("start_time", ""),
        "stop_time": detail.get("stop_time", ""),
        "current_level": detail.get("current_level", ""),
        "province": province,
    }


def weather_alert_to_scenario_params(alert: dict) -> dict:
    """将天气预警转换为场景参数"""
    alert_type = alert.get("alert_type", "暴雨")
    level = alert.get("level", "")

    # 根据预警类型和等级计算影响范围
    if level == "红色":
        radius = 150
    elif level == "橙色":
        radius = 100
    elif level == "黄色":
        radius = 60
    else:
        radius = 40

    type_map = {
        "暴雨": {"disaster_type": "rainstorm", "severity": "暴雨预警，需防范洪涝和道路积水"},
        "洪水": {"disaster_type": "rainstorm", "severity": "洪水预警，需防范河流泛滥"},
        "地质灾害": {"disaster_type": "landslide", "severity": "地质灾害预警，需防范山体滑坡和泥石流"},
        "山洪": {"disaster_type": "landslide", "severity": "山洪预警，需防范山区洪水"},
        "地震": {"disaster_type": "earthquake", "severity": "地震预警，需防范建筑倒塌和次生灾害"},
        "台风": {"disaster_type": "typhoon", "severity": "台风预警，需防范大风和暴雨"},
        "大风": {"disaster_type": "typhoon", "severity": "大风预警，需防范建筑和设施损坏"},
        "雷电": {"disaster_type": "rainstorm", "severity": "雷电预警，需防范雷击和短时强降水"},
        "山体滑坡": {"disaster_type": "landslide", "severity": "山体滑坡预警，需防范道路阻断和地质灾害"},
        "暴雪": {"disaster_type": "snowstorm", "severity": "暴雪预警，需防范道路积雪和低温"},
        "沙尘暴": {"disaster_type": "sandstorm", "severity": "沙尘暴预警，需防范能见度降低和呼吸道疾病"},
        "森林火灾": {"disaster_type": "wildfire", "severity": "森林火灾预警，需防范火势蔓延和空气污染"},
        "海啸": {"disaster_type": "tsunami", "severity": "海啸预警，需防范沿海地区淹没"},
        "高温": {"disaster_type": "other", "severity": "高温预警，需防范中暑和用电安全"},
    }
    type_info = type_map.get(alert_type, {"disaster_type": "rainstorm", "severity": "灾害预警"})

    return {
        "source": "国家气象预警信息",
        "alert_id": alert.get("alert_id", ""),
        "alert_type": alert_type,
        "level": level,
        "title": alert.get("title", ""),
        "latitude": alert.get("lat", 0),
        "longitude": alert.get("lng", 0),
        "province": alert.get("province", ""),
        "influence_radius_km": radius,
        "severity": type_info["severity"],
        "disaster_type": type_info["disaster_type"],
        "publish_time": alert.get("publish_time", ""),
        "detail": alert.get("detail", ""),
    }


def fetch_latest_disasters(limit: int = 5) -> List[dict]:
    """获取最新灾害汇总（地震+台风+预警），用于预警提示

    Returns:
        灾害列表，按时间倒序
    """
    results = []

    # 获取最新地震
    try:
        for eq in EarthquakeDataFetcher.fetch(min_magnitude=3.0, limit=limit):
            results.append({
                "type": "earthquake",
                "icon": "🌍",
                "title": f"M{eq.magnitude} {eq.location}",
                "time": eq.time,
                "level": f"M{eq.magnitude}",
                "lat": eq.latitude,
                "lng": eq.longitude,
                "detail": f"震源深度{eq.depth}km，烈度{eq.intensity}度",
                "event_id": eq.event_id,
            })
    except Exception as e:
        print(f"[fetch_latest_disasters] 地震获取失败: {e}")

    # 获取最新台风
    try:
        for t in TyphoonDataFetcher.fetch_list()[:limit]:
            results.append({
                "type": "typhoon",
                "icon": "🌀",
                "title": f"台风 {t.chinese_name or t.english_name} ({t.typhoon_no})",
                "time": t.full_no,
                "level": "活跃" if t.status == "start" else "停编",
                "lat": 0,
                "lng": 0,
                "detail": f"编号{t.full_no}",
                "event_id": str(t.typhoon_id),
            })
    except Exception as e:
        print(f"[fetch_latest_disasters] 台风获取失败: {e}")

    # 获取最新预警
    try:
        _alert_icons = {
            "暴雨": "🌧️", "洪水": "🌊", "地质灾害": "⛰️", "山洪": "💧",
            "台风": "🌀", "大风": "💨", "雷电": "⚡", "高温": "🌡️", "其他": "⚠️"
        }
        for a in WeatherAlertFetcher.fetch()[:limit]:
            results.append({
                "type": "alert",
                "icon": _alert_icons.get(a.alert_type, "⚠️"),
                "title": a.title,
                "time": a.publish_time,
                "level": a.level,
                "lat": a.lat,
                "lng": a.lng,
                "detail": a.detail[:60] if a.detail else "",
                "event_id": a.alert_id,
            })
    except Exception as e:
        print(f"[fetch_latest_disasters] 预警获取失败: {e}")

    # 按时间倒序
    results.sort(key=lambda x: x.get("time", ""), reverse=True)
    return results[:limit]
