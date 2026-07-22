# 基础数据需求清单

> 文件编号：EMG-DATA-REQ-02
> 用途：定义应急决策教学系统所需的全部基础数据，可直接作为技术要求文档的数据规格章节
> 对应模块：教（场景创建）、学（决策推演）、育（行为采集）、评（自动评分）

---

## 总览

系统基础数据分为 **七大类**：

| 序号 | 数据类别 | 核心用途 | 数据来源 |
|------|---------|---------|---------|
| 1 | 灾害信息 | 驱动应急决策场景 | 模拟数据源 / 教师配置 |
| 2 | 车辆信息 | 运力资源池，方案生成的基础约束 | 公司车辆台账 |
| 3 | 仓库/网点信息 | 中转与避险资源，就近仓储决策依据 | 公司仓储台账 |
| 4 | 货物/订单信息 | 决策对象，优先级与成本计算依据 | 运营订单系统 |
| 5 | 地图与区域信息 | 地理坐标基础，影响范围计算 | 公开地图服务 |
| 6 | 道路网络信息 | 路径规划基础，通行能力与风险判断 | 公开交通数据 / 地图服务 |
| 7 | 评分配置数据 | 评分基准与规则，支持教/评模块 | 教师配置 |

---

## 1 灾害信息

### 1.1 地震灾害

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| disaster_id | string | EQ-2024-001 | 灾害唯一编号 |
| disaster_type | enum | earthquake | 灾害类型（earthquake/rainstorm/typhoon/landslide/mudslide/flood） |
| epicenter_city | string | 成都市 | 震中城市名称 |
| epicenter_lat | number | 30.5728 | 震中纬度 |
| epicenter_lng | number | 104.0668 | 震中经度 |
| magnitude | number | 6.5 | 里氏震级 |
| depth_km | number | 15 | 震源深度（千米） |
| influence_radius_km | number | 80 | 影响半径范围（千米） |
| occur_time | datetime | 2024-07-15T10:30:00+08:00 | 地震发生/预计发生时间 |
| wave_arrival_times | array | [{node_id:"WH-01",arrival_min:120}] | 地震波到达各物流节点的预计时间（分钟） |
| affected_areas | array | ["成都","德阳","绵阳"] | 受影响地区列表 |
| severity_level | enum | moderate | 破坏程度等级（minor/moderate/severe/extreme） |

### 1.2 暴雨灾害

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| disaster_type | enum | rainstorm | 固定值 rainstorm |
| center_city | string | 郑州市 | 暴雨中心城市 |
| rainfall_mm | number | 280 | 24小时累计降雨量（毫米） |
| waterlogged_roads | array | [{road_id:"R-105",water_depth_cm:40}] | 积水路段列表及积水深度 |
| river_water_level | array | [{river:"贾鲁河",station:"中牟站",level_m:5.2,warning_level_m:4.0}] | 河道水位及警戒水位 |
| affected_duration_hours | number | 36 | 预计影响持续时长（小时） |
| affected_areas | array | ["郑州","开封"] | 受影响地区 |

### 1.3 台风灾害

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| disaster_type | enum | typhoon | 固定值 typhoon |
| typhoon_name | string | "梅花" | 台风名称 |
| wind_force_level | number | 14 | 风力等级（蒲福风级） |
| moving_speed_kmh | number | 25 | 移动速度（千米/小时） |
| moving_direction | string | "西北" | 移动方向 |
| landing_time | datetime | 2024-09-14T22:00:00+08:00 | 预计登陆时间 |
| landing_location | string | "浙江舟山" | 预计登陆地点 |
| influence_radius_km | number | 300 | 影响半径（千米） |
| port_closure | boolean | true | 港口是否关闭 |
| airport_closure | boolean | true | 机场是否停运 |
| affected_areas | array | ["舟山","宁波","台州"] | 受影响地区 |

### 1.4 山体滑坡/泥石流/洪水

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| disaster_type | enum | landslide/mudslide/flood | 灾害类型 |
| location_city | string | 汶川县 | 发生地点 |
| location_lat | number | 31.00 | 发生地纬度 |
| location_lng | number | 103.40 | 发生地经度 |
| blocked_roads | array | ["R-201","R-203"] | 直接阻断的道路ID列表 |
| scale_level | enum | small/medium/large | 规模等级 |
| estimated_clear_hours | number | 48 | 预计恢复通车时长（小时） |
| affected_areas | array | ["汶川","茂县"] | 受影响地区 |

---

## 2 车辆信息

全公司所有车辆的台账数据，作为运力资源池。

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| vehicle_id | string | V-03 | 车辆唯一编号 |
| license_plate | string | 川A·12345 | 车牌号 |
| vehicle_type | enum | box_truck | 车型（box_truck厢式/flatbed平板车/refrigerated冷藏车/container集装箱车） |
| capacity_tons | number | 8.0 | 载重上限（吨） |
| capacity_m3 | number | 45 | 载货容积（立方米） |
| current_location_node | string | NODE-A14 | 当前所在节点ID |
| current_lat | number | 30.65 | 当前位置纬度 |
| current_lng | number | 104.07 | 当前位置经度 |
| status | enum | idle | 当前状态（idle空闲/in_transit运输中/loading装卸中/maintenance维修中） |
| current_cargo_ids | array | ["C-101","C-102"] | 当前已装载的货物ID列表 |
| current_load_tons | number | 5.2 | 当前已装载重量（吨） |
| current_load_m3 | number | 28 | 当前已装载体积（立方米） |
| remaining_capacity_tons | number | 2.8 | 剩余可用载重（吨）= capacity_tons - current_load_tons |
| remaining_capacity_m3 | number | 17 | 剩余可用容积（立方米） |
| driver_name | string | 张师傅 | 驾驶员姓名 |
| driver_phone | string | 138xxxx1234 | 驾驶员电话（模拟场景可省略） |
| home_depot | string | DEPOT-01 | 所属车场/调度中心 |
| cost_per_km | number | 8.5 | 每公里运输成本（元） |
| cost_per_hour | number | 120 | 每小时运营成本（元，含人工+燃油） |
| is_refrigerated | boolean | false | 是否冷藏车（影响可装载货物类型） |
| last_maintenance_date | date | 2024-07-01 | 上次保养日期 |

### 车辆状态字段说明

status 字段是方案生成的关键约束：

| 状态值 | 含义 | 可否调度 |
|--------|------|---------|
| idle | 空闲停场 | ✅ 可立即调度 |
| in_transit | 运输途中 | ⚠️ 需到达下一节点后可改道 |
| loading | 装卸中 | ⚠️ 装卸完成后可调度 |
| maintenance | 维修中 | ❌ 不可调度 |

---

## 3 仓库/网点信息

全公司所有仓储网点数据，作为中转与避险资源。

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| warehouse_id | string | WH-02 | 仓库唯一编号 |
| warehouse_name | string | 成都龙泉驿仓 | 仓库名称 |
| city | string | 成都 | 所在城市 |
| address | string | 龙泉驿区XX路XX号 | 详细地址 |
| lat | number | 30.56 | 纬度 |
| lng | number | 104.15 | 经度 |
| node_id | string | NODE-W02 | 对应物流网络节点ID |
| total_capacity_m3 | number | 5000 | 总库容（立方米） |
| used_capacity_m3 | number | 3200 | 已用库容（立方米） |
| remaining_capacity_m3 | number | 1800 | 剩余可用库容（立方米） |
| storage_cost_per_m3_per_day | number | 2.5 | 仓储单价（元/立方米/天） |
| supported_cargo_types | array | ["normal","refrigerated","hazardous"] | 支持的货物类型 |
| has_cold_chain | boolean | true | 是否具备冷链能力 |
| has_dock | number | 4 | 装卸月台数量（影响并发装卸能力） |
| dock_occupancy | number | 2 | 当前占用月台数 |
| available_docks | number | 2 | 可用月台数 |
| operating_hours | object | {start:"06:00",end:"22:00",is_24h:false} | 营业时间 |
| manager_name | string | 李仓管 | 负责人 |
| is_in_disaster_zone | boolean | false | 是否在灾区范围内（由灾害影响分析自动标记） |
| damage_status | enum | normal | 损坏状态（normal正常/damaged受损/closed关闭） |
| estimated_recovery_hours | number | 0 | 预计恢复时长（受损时填写，正常为0） |

### 仓库损坏状态规则

| 状态值 | 含义 | 可否用于中转 |
|--------|------|-------------|
| normal | 正常运营 | ✅ |
| damaged | 受损但部分可用 | ⚠️ 容量按50%折减 |
| closed | 完全关闭 | ❌ 不可用 |

---

## 4 货物/订单信息

当前所有在途和待发运的订单数据，是决策的核心对象。

### 4.1 订单基础信息

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| cargo_id | string | C-101 | 货物/订单唯一编号 |
| order_no | string | PO-20240715-001 | 关联的业务订单号 |
| cargo_type | enum | medical | 货物类型（medical医疗/supplies民生物资/urgent紧急件/normal普通快递/hazardous危险品/perishable生鲜冷藏） |
| description | string | "急救药品一批" | 货物描述 |
| weight_tons | number | 2.5 | 重量（吨） |
| volume_m3 | number | 8 | 体积（立方米） |
| value_yuan | number | 80000 | 货物声明价值（元） |
| priority_level | enum | P1 | 优先级（P1医疗/民生必须保障，P2紧急，P3普通） |
| requires_cold_chain | boolean | false | 是否需要冷链运输 |
| is_hazardous | boolean | false | 是否危险品（需特殊车辆） |

### 4.2 运输任务信息

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| origin_node | string | NODE-A14 | 发货节点ID |
| origin_name | string | 成都龙泉驿仓 | 发货地点名称 |
| destination_node | string | NODE-B08 | 收货节点ID |
| destination_name | string | 绵阳涪城区 | 收货地点名称 |
| destination_lat | number | 31.45 | 收货地纬度 |
| destination_lng | number | 104.75 | 收货地经度 |
| assigned_vehicle_id | string | V-03 | 原分配车辆ID（已发运的订单有） |
| current_status | enum | in_transit | 运输状态（pending待发运/loading装车中/in_transit运输中/delivered已送达） |
| current_location_node | string | NODE-A15 | 当前所在节点 |
| planned_route | array | ["NODE-A14","NODE-A15","NODE-A16","NODE-B08"] | 原计划路线（节点序列） |
| current_route_index | number | 1 | 当前在路线中的位置索引 |
| departure_time | datetime | 2024-07-15T09:00:00+08:00 | 发车时间 |
| deadline | datetime | 2024-07-15T18:00:00+08:00 | 最晚送达时间（客户要求） |
| contract_penalty_per_hour | number | 500 | 超时违约金（元/小时） |
| customer_id | string | CU-021 | 客户ID |
| customer_name | string | 绵阳中心医院 | 客户名称 |
| customer_type | enum | hospital | 客户类型（hospital医院/supermarket商超/enterprise企业/individual个人/government政府机构） |

### 4.3 优先级判定规则

系统根据以下规则自动判定 priority_level（教师可手动覆盖）：

| 优先级 | 判定条件 | 保障要求 |
|--------|---------|---------|
| P1 | cargo_type 为 medical 或 supplies；或 customer_type 为 hospital/government | **不可放弃，必须优先保障** |
| P2 | deadline 距当前时间 ≤ 6小时；或 value_yuan > 50000；或 cargo_type 为 urgent | 优先保障，资源不足时最后放弃 |
| P3 | 不满足P1/P2条件 | 资源不足时可放弃 |

---

## 5 地图与区域信息

### 5.1 物流网络节点

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| node_id | string | NODE-A14 | 节点唯一编号 |
| node_name | string | 成都龙泉驿枢纽 | 节点名称 |
| node_type | enum | depot | 节点类型（depot车场/warehouse仓库/customer_point客户点/junction路口/transfer_center转运中心） |
| city | string | 成都 | 所在城市 |
| lat | number | 30.56 | 纬度 |
| lng | number | 104.15 | 经度 |
| connected_road_ids | array | ["R-101","R-103"] | 连接该节点的道路ID列表 |

### 5.2 区域信息

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| area_id | string | AREA-SC | 区域唯一编号 |
| area_name | string | 四川 | 区域名称（省/市/区） |
| area_level | enum | province | 层级（province省/city市/district区） |
| center_lat | number | 30.57 | 区域中心纬度 |
| center_lng | number | 104.07 | 区域中心经度 |
| polygon | array | [{lat:30.1,lng:103.8},...] | 区域边界多边形坐标（用于判断节点/道路是否在灾害影响范围内） |

---

## 6 道路网络信息

道路网络数据是路径规划的基础，也是灾害影响分析的关键。

### 6.1 道路（路段）信息

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| road_id | string | R-101 | 道路唯一编号 |
| road_name | string | "成绵高速" | 道路名称 |
| road_type | enum | highway | 道路类型（highway高速/national国道/provincial省道/city_road城市道路/county县乡道） |
| from_node | string | NODE-A14 | 起点节点ID |
| to_node | string | NODE-A15 | 终点节点ID |
| is_bidirectional | boolean | true | 是否双向通行 |
| distance_km | number | 85 | 里程（千米） |
| speed_limit_kmh | number | 100 | 限速（千米/小时） |
| normal_travel_time_min | number | 51 | 正常通行时间（分钟）= distance / speed_limit × 60 |
| current_travel_time_min | number | 68 | 当前实际通行时间（分钟，含拥堵因素） |
| road_condition | enum | clear | 路况（clear畅通/slow缓慢/congested拥堵/blocked中断） |
| has_bridge | boolean | true | 是否含桥梁（桥梁受损风险更高） |
| has_tunnel | boolean | false | 是否含隧道 |
| capacity_per_hour | number | 2000 | 通行能力（辆/小时，反映道路宽度） |
| toll_cost | number | 35 | 过路费（元） |
| fuel_cost_per_km | number | 0.8 | 百公里油耗折算（元/千米，按车型） |

### 6.2 道路灾害影响标记

灾害发生时，系统根据灾害类型自动标记受影响道路，追加以下字段：

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| disaster_affected | boolean | true | 是否受当前灾害影响 |
| affected_type | enum | blocked | 影响类型（blocked完全中断/restricted限行/slow减速通行） |
| delay_factor | number | 2.5 | 延迟系数（实际通行时间 = 正常时间 × delay_factor） |
| estimated_recovery_hours | number | 12 | 预计恢复时间（小时） |
| risk_score | number | 0.8 | 风险评分 [0,1]（0=安全，1=极危险） |
| affected_by_disaster | string | EQ-2024-001 | 关联的灾害ID |

### 6.3 各灾害类型对道路的影响规则

| 灾害类型 | 影响规则 | 标记方式 |
|---------|---------|---------|
| 地震 | 震中半径内道路 → risk_score 随距离递减；含桥梁道路 → 概率性受损标记为 blocked | 按影响半径自动标记 |
| 暴雨 | 积水路段 → delay_factor 根据积水深度计算；积水>50cm → blocked | 按积水数据标记 |
| 台风 | 影响半径内道路 → delay_factor = 2.0；高速/桥梁 → 概率性 blocked | 按风力等级和路径标记 |
| 滑坡/泥石流 | 直接阻断 listed roads → blocked；周边道路 → delay_factor = 1.5 | 按位置直接标记 |

### 6.4 灾害影响半径计算规则

```
对每个道路路段 (from_node → to_node)：
  计算路段中点到震中的距离 d (千米)
  若 d ≤ influence_radius_km:
    risk_score = max(0, 1 - d / influence_radius_km)
    delay_factor = 1 + risk_score × 2    （延迟最多3倍正常时间）
    若含桥梁且 risk_score > 0.6:
      affected_type = "blocked"           （桥梁受损，道路中断）
    否则:
      affected_type = "restricted"
  否则:
    不受影响
```

---

## 7 评分配置数据

### 7.1 评分基准配置

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| config_id | string | EVAL-CFG-001 | 配置编号 |
| scenario_id | string | EQ-2024-001 | 关联场景ID（可为空=全局默认配置） |
| benchmark_cost | number | 40000 | 行业基准成本（元），经济性得分依据 |
| benchmark_delivery_time_hours | number | 24 | 基准送达时长（小时），时效性参照 |
| weights | object | {timeliness:0.3, economic:0.25, feasibility:0.25, compliance:0.2} | 四维评分权重（合计=1.0） |
| bonus_rules | array | [{rule:"first_submit_bonus",score:5}] | 加分规则 |
| penalty_rules | array | [{rule:"timeout_penalty",score:-10}] | 扣分规则 |
| compliance_priority_list | array | ["medical","supplies"] | 必须保障的货物类型清单 |

### 7.2 评分基准来源说明

`benchmark_cost` 的确定方式（三选一，按优先级）：

| 来源 | 说明 | 适用场景 |
|------|------|---------|
| 教师手动设置 | 教师在场景编辑器中直接填写 | 自定义教学场景（推荐） |
| 系统内置参考表 | 按货物量和运输距离自动估算：基准 = 货物总吨数 × 平均运距 × 单位运输成本 | 标准教学场景 |
| 历史最优方案回填 | 系统首次求解后，将最优方案成本 × 1.2 作为基准回填 | 自动生成基准 |

### 7.3 评语模板配置

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| template_id | string | TPL-001 | 模板编号 |
| score_range | object | {min:90, max:100} | 适用分数区间 |
| overall_comment | string | "你在本次应急决策中表现出卓越的全局掌控力" | 总体评语 |
| strength_template | string | "你的{dimension}得分很高（{grade}级），{detail}" | 亮点描述模板 |
| weakness_template | string | "{dimension}得分偏低，原因在于{detail}" | 不足描述模板 |
| recommendation | string | "建议前往案例库学习《XX复盘》案例" | 改进建议 |
| linked_case | string | "CASE-ZZ720" | 关联推荐学习案例ID |

---

## 数据来源汇总

| 数据类别 | 推荐数据源 | 接入方式 | 更新频率 |
|---------|-----------|---------|---------|
| 地震数据 | 中国地震台网中心 API / 模拟数据 | API对接 / 教师手动配置 | 实时（真实）/ 按需（模拟） |
| 车辆信息 | 公司车辆管理台账 | 数据库导入 | 每日同步 |
| 仓库信息 | 公司仓储管理系统 | 数据库导入 | 每日同步 |
| 货物/订单信息 | 运营订单系统 | API实时拉取 | 实时 |
| 地图数据 | 高德/百度地图开放平台 | API调用 | 按需 |
| 道路网络 | 高德路网数据 / 开源OpenStreetMap | 离线导入 + API补充 | 季度更新 |
| 天气/台风 | 中央气象台 / 气象开放数据 | API对接 | 实时（真实）/ 按需（模拟） |
| 评分配置 | 教师管理后台 | 手动配置 | 每场景 |

---

## 数据完整性校验规则

系统在加载场景数据时执行以下校验，校验不通过则拒绝启动推演：

| 校验项 | 规则 | 失败处理 |
|--------|------|---------|
| 车辆引用完整性 | 所有订单的 assigned_vehicle_id 必须在车辆列表中存在 | 报错并定位缺失车辆 |
| 节点引用完整性 | 所有车辆、仓库、订单的 node 引用必须在节点列表中存在 | 报错并定位缺失节点 |
| 道路连续性 | 每条道路的 from_node 和 to_node 必须在节点列表中存在 | 报错并定位断链 |
| 容量非负 | 所有 capacity、remaining 字段 ≥ 0 | 报错 |
| 优先级覆盖 | 所有 cargo_type 为 medical/supplies 的订单 priority_level 必须为 P1 | 自动修正为P1 |
| 仓库可用性 | damage_status 为 closed 的仓库 remaining_capacity_m3 必须为 0 | 自动修正为0 |
| deadline合理性 | 所有订单的 deadline > departure_time | 报错 |
