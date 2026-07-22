# 最优方案引擎技术规格

> 文件编号：EMG-ENG-SPEC-01
> 版本：v1.0
> 依赖：场景参数模板（EMG-SCN-TPL-01）
> 支撑模块：教（最优方案生成）、学（人机对比基准）、评（评分基准方案）

---

## 1 设计目标

最优方案引擎是教/学/评三模块的公共依赖根。它的职责是：

1. **给定一个应急场景 + 当前物流状态**，在资源约束下计算出成本-时效-安全多目标最优的决策方案。
2. 输出不仅包含"最优方案"本身，还包含**方案的评分明细**和**备选方案集**（帕累托前沿），供教学对比使用。
3. 支持三种教学策略的不同配置：人机竞速、智能体对抗、有限预算。
4. 运行时间 ≤ 5秒（教学场景规模），保证"黄金10分钟"倒计时内完成计算。

---

## 2 求解器架构

```
┌─────────────────────────────────────────────────────────┐
│                    ScenarioContext (JSON)                │
│  灾害参数 + 物流网络 + 货物清单 + 车辆/仓库 + 评分配置     │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│              Input Parser (输入解析层)                    │
│  · 校验数据完整性                                        │
│  · 构建网络拓扑图 (有向图)                                │
│  · 标记灾害影响 (阻塞路段、受损仓库、延迟系数)              │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌──────────────────┬──────┴───────┬──────────────────────┐
│  Resource Alloc  │  Route Opt   │  Priority Sorter     │
│  (资源分配子问题)  │  (路径优化)   │  (货物优先级排序)     │
│                  │              │                      │
│  货物→仓库分配    │  车辆路径规划  │  医疗/民生优先保障    │
│  仓库容量约束     │  路况通行约束  │  放弃低价值货物       │
│  MIP求解          │  VRP求解      │  启发式排序            │
└────────┬─────────┴──────┬───────┴──────────┬───────────┘
         └───────────────┼──────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Solution Combiner (方案合成层)               │
│  · 合并三个子问题的解 → 完整决策方案                       │
│  · 计算成本/时效/安全/合规四维得分                          │
│  · 生成帕累托前沿备选方案 (2-3个)                         │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│              Output Formatter (输出格式化层)              │
│  · 生成 DecisionPlan (JSON)                             │
│  · 生成 ScoreBreakdown (评分明细)                        │
│  · 生成 alternatives[] (备选方案)                        │
│  · 生成 explanation (方案说明文本, 供评语引用)             │
└─────────────────────────────────────────────────────────┘
```

### 2.1 技术选型

| 组件 | 推荐方案 | 理由 |
|------|---------|------|
| 路径优化 (VRP) | Google OR-Tools (CP-SAT solver) | 开源、Python/C++/JS多语言绑定、内置VRP求解器、支持时间窗约束 |
| 资源分配 (MIP) | OR-Tools CP-SAT 或 PuLP+CBC | 约束规划适合离散分配问题，CBC免费开源 |
| 货物优先级排序 | 自定义启发式 | 规则明确、计算量小、无需求解器 |
| 方案说明生成 | LLM (可选) | 将求解器输出的结构化方案转为自然语言说明 |
| 运行环境 | Python 3.10+ | OR-Tools原生支持，生态完善 |

> **为什么不用纯LLM做求解器？** LLM在多约束数值优化上不可靠（幻觉、无法保证约束满足）。正确做法是：**求解器算最优解，LLM写说明和评语。**

---

## 3 数学模型

### 3.1 集合与索引

| 符号 | 含义 |
|------|------|
| I = {1,...,n} | 货物订单集合 |
| V = {1,...,m} | 可用车辆集合 |
| W = {1,...,p} | 可用仓库集合 |
| N = {0,1,...,q} | 物流网络节点集合（0 = 车场/调度中心） |
| A ⊆ N×N | 路段（有向弧）集合 |
| P = {1,2,3} | 货物优先级（1=医疗/民生必须保障，2=紧急，3=普通） |
| B ⊆ A | 灾害导致阻塞的路段集合 |

### 3.2 参数（输入数据）

| 符号 | 含义 | 单位 |
|------|------|------|
| cost_{ij} | 路段(i,j)运输成本 | 元 |
| time_{ij} | 路段(i,j)通行时间 | 分钟 |
| risk_{ij} | 路段(i,j)风险评分 [0,1] | 无量纲 |
| cap_v | 车辆v载重上限 | 吨 |
| capw_k | 仓库k剩余容量 | 立方米 |
| store_k | 仓库k仓储单价 | 元/(立方米·小时) |
| deadline_i | 货物i最晚送达时间 | 分钟(从T0起算) |
| priority_i ∈ P | 货物i优先级等级 | 1/2/3 |
| value_i | 货物i价值 | 元 |
| weight_i | 货物i重量 | 吨 |
| volume_i | 货物i体积 | 立方米 |
| M | 充分大常数 | — |
| w_cost, w_time, w_risk, w_comp | 目标函数权重 | 由策略配置决定 |
| budget_limit | 预算上限（策略三启用） | 元 |

### 3.3 决策变量

| 变量 | 类型 | 含义 |
|------|------|------|
| x_{ijvk} | 二值 | 车辆v是否经路段(i,j)运送货物k |
| y_{ik} | 二值 | 货物i是否转存至仓库k |
| z_i | 二值 | 货物i是否超时未送达 |
| u_i | 二值 | 货物i是否被放弃（不配送） |
| t_i | 连续 | 货物i实际送达时间 |

### 3.4 目标函数

$$\min Z = w_{cost} \cdot (C_{transport} + C_{storage} + C_{abandon}) + w_{time} \cdot C_{delay} + w_{risk} \cdot C_{risk} + w_{comp} \cdot C_{compliance}$$

各分项：

| 分项 | 计算式 | 含义 |
|------|--------|------|
| C_transport | Σ cost_{ij} · x_{ijvk} | 运输总成本 |
| C_storage | Σ store_k · volume_i · y_{ik} · duration | 仓储总成本 |
| C_abandon | Σ value_i · u_i | 放弃货物的价值损失 |
| C_delay | Σ max(0, t_i − deadline_i) | 总超时时间(分钟) |
| C_risk | Σ risk_{ij} · x_{ijvk} | 路径风险累计得分 |
| C_compliance | Σ (priority_i == 1) · (z_i + u_i) · PENALTY | 医疗/民生物资未保障的惩罚 |

### 3.5 约束条件

**C1. 路段可行性**：灾害阻塞路段不可通行
```
x_{ijvk} = 0,  ∀(i,j) ∈ B
```

**C2. 车辆载重上限**：
```
Σ weight_k · x_{ijvk} ≤ cap_v,  ∀v, ∀(i,j)
```

**C3. 仓库容量上限**：
```
Σ volume_i · y_{ik} ≤ capw_k,  ∀k
```

**C4. 货物唯一分配**：每件货物只能被分配到一种处置方式
```
Σ_k y_{ik} + Σ_{v} delivered_{iv} + u_i = 1,  ∀i
```
（delivered、stored、abandoned 三者互斥且穷尽）

**C5. 流量守恒**：每个节点对每辆车的进出流量平衡
```
Σ_j x_{jivk} = Σ_j x_{ijvk},  ∀v, ∀i ∈ N \ {origin, destination}
```

**C6. 送达时间约束**：
```
t_i ≥ Σ time_{ij} · x_{ijvk},  ∀i
```

**C7. 超时判定**（big-M 松弛）：
```
t_i ≤ deadline_i + M · z_i,  ∀i
```

**C8. 优先保障约束**：医疗/民生物资不可放弃
```
u_i = 0,  ∀i where priority_i = 1
```

**C9. 预算约束**（策略三启用）：
```
C_transport + C_storage + C_abandon ≤ budget_limit
```

**C10. 车辆出车约束**：总调用车辆不超过可用数量
```
distinct_vehicles_used ≤ available_vehicle_count
```

### 3.6 求解流程

```
Step 1: [预处理] 解析场景JSON → 构建网络图 → 标记阻塞路段 → 计算各路段风险评分
Step 2: [优先级排序] 按 priority_i → value_i/deadline_i 排序，确定保障顺序
Step 3: [资源分配] 求解MIP：货物→仓库/车辆分配方案 (约束C2,C3,C4,C8,C9)
Step 4: [路径优化] 对每组"车辆-货物"分配，求解VRP：最优路径 (约束C1,C5,C6,C7)
Step 5: [方案合成] 合并分配+路径 → 计算四维得分 → 生成备选方案
Step 6: [输出] 格式化为DecisionPlan JSON
```

> **Step 3和Step 4可解耦**：先解决"分配什么给谁"，再解决"怎么走"。这是VRP领域经典的cluster-first/route-second策略，降低问题复杂度。教学场景规模（~50订单、~20车辆、~10仓库）下，OR-Tools在5秒内可解。

---

## 4 数据契约

### 4.1 输入：ScenarioContext（JSON）

引擎的唯一输入入口，由场景参数模板实例化后传入。完整定义见 `02-scenario-template-spec.md`。

核心结构：

```json
{
  "scenario_id": "EQ-2024-001",
  "disaster": { "type": "earthquake", "magnitude": 6.5, ... },
  "logistics_network": { "nodes": [...], "edges": [...] },
  "cargo_manifest": [ { "cargo_id": "C-101", "priority": 1, ... } ],
  "vehicle_fleet": [ { "vehicle_id": "V-03", "capacity_tons": 8, ... } ],
  "warehouses": [ { "warehouse_id": "WH-02", "remaining_capacity_m3": 120, ... } ],
  "evaluation": { "benchmark_cost": 40000, "weights": {...} },
  "strategy_config": { "mode": "time_pressure", "time_limit_sec": 600, ... }
}
```

### 4.2 输出：DecisionPlan（JSON）

这是引擎的唯一输出，教/学/评三个模块都消费这个结构。

```json
{
  "plan_id": "OPT-EQ2024001-v1",
  "scenario_id": "EQ-2024-001",
  "generated_at": "2024-07-15T10:32:00+08:00",
  "solve_time_ms": 3400,

  "total_cost": 45600,
  "total_delay_hours": 3.5,
  "vehicles_used": 4,
  "warehouses_used": 2,
  "cargo_delivered": 18,
  "cargo_abandoned": 2,
  "cargo_stored": 5,

  "actions": [
    {
      "action_id": "ACT-001",
      "type": "reroute",
      "description": "车辆V-03改道经NODE-B07绕行",
      "vehicle_id": "V-03",
      "cargo_ids": ["C-101", "C-102"],
      "new_route": ["NODE-A14", "NODE-B07", "NODE-B08"],
      "original_route": ["NODE-A14", "NODE-A15", "NODE-A16"],
      "extra_cost": 3200,
      "extra_time_min": 45,
      "risk_score": 0.2
    },
    {
      "action_id": "ACT-002",
      "type": "warehouse_transfer",
      "description": "货物C-103就近转存至WH-02",
      "cargo_ids": ["C-103"],
      "warehouse_id": "WH-02",
      "storage_cost": 500,
      "storage_duration_hours": 12
    },
    {
      "action_id": "ACT-003",
      "type": "abandon",
      "description": "因预算限制放弃普通快递C-105",
      "cargo_ids": ["C-105"],
      "reason": "budget_exceeded",
      "value_loss": 2000
    }
  ],

  "score_breakdown": {
    "timeliness": { "score": 85, "reason": "3单超时，平均超时2.1小时" },
    "economic": { "score": 92, "reason": "总成本45600 < 基准40000×1.2" },
    "feasibility": { "score": 100, "reason": "全部方案在可用资源范围内" },
    "compliance": { "score": 90, "reason": "医疗物资全部保障，1单民生延迟" }
  },

  "alternatives": [
    {
      "plan_id": "OPT-EQ2024001-alt1",
      "description": "成本优先方案：放弃更多普通货物，仅保障医疗和紧急件",
      "total_cost": 38000,
      "cargo_abandoned": 5,
      "score_breakdown": { "timeliness": 70, "economic": 98, "feasibility": 100, "compliance": 80 }
    },
    {
      "plan_id": "OPT-EQ2024001-alt2",
      "description": "时效优先方案：调用全部备用车，所有货物按时送达",
      "total_cost": 62000,
      "cargo_abandoned": 0,
      "score_breakdown": { "timeliness": 100, "economic": 65, "feasibility": 100, "compliance": 100 }
    }
  ],

  "explanation": "推荐方案采用混合策略：医疗物资和紧急件通过改道保障时效（3单），普通货物中5单转存就近仓库待灾后配送，2单因预算限制放弃。总成本45600元，较基准成本超支14%，但医疗物资100%保障。"
}
```

### 4.3 字段规格

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| plan_id | string | 是 | 方案唯一标识 |
| scenario_id | string | 是 | 对应场景ID |
| total_cost | number | 是 | 方案总成本（元） |
| actions[] | array | 是 | 决策动作列表 |
| actions[].type | enum | 是 | `reroute` \| `warehouse_transfer` \| `abandon` \| `delay` \| `hold` |
| actions[].cargo_ids | array | 是 | 涉及的货物ID列表 |
| score_breakdown | object | 是 | 四维评分明细（每维含score和reason） |
| alternatives[] | array | 否 | 帕累托备选方案（最多3个） |
| explanation | string | 是 | 方案自然语言说明（供评语引用） |

---

## 5 三教学策略的引擎适配

三种策略不改变求解器本身，而是通过 `strategy_config` 改变求解器的参数和约束。

### 5.1 策略一：人机竞速

```json
{
  "mode": "time_pressure",
  "time_limit_sec": 600,
  "hide_optimal_until_submit": true,
  "solver_config": {
    "objective_weights": { "w_cost": 0.3, "w_time": 0.4, "w_risk": 0.2, "w_comp": 0.1 },
    "generate_alternatives": true,
    "max_alternatives": 2
  }
}
```

**引擎行为**：
- 预先生成最优方案，但暂不返回给学生端（`hide_optimal_until_submit`）
- 学生提交后，引擎同时返回最优方案 + 学生方案 + 对比分析
- 对比分析维度：成本差异、时效差异、安全差异、评分差异

### 5.2 策略二：智能体对抗

```json
{
  "mode": "agent_adversarial",
  "time_limit_sec": 600,
  "hidden_disruptions": [
    {
      "disruption_id": "HD-001",
      "description": "前方国道桥梁受损（信息尚未上报）",
      "affected_roads": ["A-B07-B08"],
      "reveal_to": "student_only",
      "reveal_timing": "immediate"
    }
  ],
  "solver_config": {
    "objective_weights": { "w_cost": 0.25, "w_time": 0.35, "w_risk": 0.25, "w_comp": 0.15 },
    "solver_blind_to": ["hidden_disruptions"],
    "allow_student_override": true
  }
}
```

**引擎行为**：
- 引擎在求解时**看不到** `hidden_disruptions`（模拟AI信息盲区）
- 引擎生成方案后，学生收到额外干扰信息，可以**修正**或**驳回**引擎方案
- 学生修正后，引擎重新评估修正方案的可行性并计分
- 评分增加"纠偏得分"维度：学生成功修正AI错误方案 → 加分

### 5.3 策略三：有限预算

```json
{
  "mode": "budget_constrained",
  "time_limit_sec": 600,
  "student_budget": {
    "available_vehicles": 2,
    "budget_limit": 25000,
    "note": "智能体方案需要5辆车，学生只有2辆"
  },
  "solver_config": {
    "objective_weights": { "w_cost": 0.45, "w_time": 0.25, "w_risk": 0.15, "w_comp": 0.15 },
    "constraint_overrides": {
      "vehicle_count_limit": 2,
      "budget_limit": 25000
    },
    "generate_full_resource_plan": true
  }
}
```

**引擎行为**：
- 引擎生成**两个方案**：①满资源最优方案（参考基准）②学生资源约束下的满意方案
- 学生方案与"满意方案"对比，而非与"最优方案"对比
- 评分中"经济性"权重提高（因为资源约束下经济权衡更关键）
- 增加"放弃决策合理性"子维度：评估学生放弃货物时的优先级判断是否合理

---

## 6 方案模拟器（学生方案评估）

引擎不仅生成最优方案，还需**评估学生提交的方案**。这部分逻辑独立于求解器。

### 6.1 输入

学生提交的方案格式与 DecisionPlan.actions 结构一致，但 plan_id 前缀为 `STU-`。

### 6.2 模拟执行流程

```
Step 1: [可行性校验]
  - 学生选择的路段是否在阻塞集合B中？→ 若是，方案不可行，可行性=0
  - 调用的车辆是否在可用列表中？→ 若否，可行性=0
  - 仓库是否有足够剩余容量？→ 若否，可行性按比例扣分

Step 2: [成本计算]
  - 按学生方案的实际路径计算运输成本
  - 按学生方案的仓储分配计算仓储成本
  - 按放弃的货物计算价值损失

Step 3: [时效计算]
  - 按学生路径的通行时间 + 灾害延迟系数，计算各货物送达时间
  - 与deadline对比，计算超时

Step 4: [风险计算]
  - 按学生路径的风险评分累计

Step 5: [合规计算]
  - 检查医疗/民生物资是否被保障
  - 检查是否违反优先级规则

Step 6: [评分]
  - 按评分矩阵计算四维得分 → 总分
```

### 6.3 对比输出

学生方案评估完成后，引擎输出对比结构：

```json
{
  "comparison_id": "CMP-EQ2024001-stu001",
  "optimal_plan": { "total_cost": 45600, "score": 91, ... },
  "student_plan": { "total_cost": 52000, "score": 78, ... },
  "diff": {
    "cost_delta": 6400,
    "score_delta": -13,
    "timeliness_delta": -10,
    "economic_delta": -8,
    "feasibility_delta": 0,
    "compliance_delta": -5
  },
  "analysis": "你的方案在时效上与最优方案接近，但成本高出6400元，主要原因是你多调用了一辆备用车。建议关注资源利用率。"
}
```

---

## 7 实施路线

| 阶段 | 交付物 | 周期建议 |
|------|--------|---------|
| P0 | 场景参数模板 + JSON Schema校验 | 1周 |
| P1 | 输入解析层 + 网络图构建 | 1周 |
| P2 | 路径优化(VRP)求解器 + 基准测试 | 2周 |
| P3 | 资源分配(MIP)求解器 + 基准测试 | 2周 |
| P4 | 方案合成层 + 评分计算 + 备选方案 | 1周 |
| P5 | 学生方案模拟器 + 对比输出 | 1周 |
| P6 | 三策略配置适配 + 集成测试 | 1周 |

> **关键路径**：P1 → P2 → P4 → P5。P3可与P2并行，P6最后集成。
> **第一个可演示里程碑**：P1+P2完成后，输入一个地震场景JSON，输出一条最优路径方案。这是验证引擎可行性的最小闭环。
