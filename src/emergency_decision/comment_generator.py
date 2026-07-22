"""
智能评语生成器 - 三段式评语
对应文档: 用户需求文档 4.2.2 智能评语生成器

结构:
  第一段: 总体评价 (根据总得分区间)
  第二段: 亮点与不足 (结合素养画像)
  第三段: 改进建议 (学习资源推荐)
"""

from __future__ import annotations

from .scoring import ScoringEngine


class CommentGenerator:
    """三段式评语生成器"""

    # 总体评价模板
    OVERALL_TEMPLATES = {
        "A": "你在本次{disaster}应急决策中表现出卓越的全局掌控力, 决策果断且兼顾成本。",
        "B": "你的方案整体可行, 但在资源统筹上仍有优化空间。",
        "C": "你基本完成了决策任务, 但在关键环节存在明显不足。",
        "D": "你的决策方案存在较大问题, 需要认真复盘改进。",
        "E": "本次决策未能达到基本要求, 建议重新学习相关案例后再次尝试。",
    }

    # 维度名称映射
    DIMENSION_NAMES = {
        "timeliness": "时效性",
        "economic": "经济性",
        "feasibility": "可行性",
        "compliance": "合规性",
    }

    # 推荐案例
    CASE_RECOMMENDATIONS = {
        "earthquake": {
            "case_id": "CASE-WC512",
            "title": "汶川5·12地震物流应急复盘",
            "focus": "重点关注多节点协同调度和医疗物资优先保障策略"
        },
        "rainstorm": {
            "case_id": "CASE-ZZ720",
            "title": "郑州7·20暴雨物流应急复盘",
            "focus": "重点关注多节点协同调度的策略"
        },
        "typhoon": {
            "case_id": "CASE-LCM",
            "title": "台风梅花物流应急复盘",
            "focus": "重点关注港口关闭与航空停运下的多式联运策略"
        },
    }

    def generate(self, total_score: float, score_breakdown: dict,
                  disaster_type: str = "earthquake",
                  literacy_profile: dict | None = None,
                  comparison: dict | None = None) -> str:
        """
        生成三段式评语

        Args:
            total_score: 总分
            score_breakdown: 四维评分明细 {timeliness: {score, reason}, ...}
            disaster_type: 灾害类型
            literacy_profile: 素养画像 {risk_awareness, system_thinking, decision_resilience}
            comparison: 与最优方案对比结果
        """
        grade, _ = ScoringEngine.get_grade(total_score)
        disaster_name = self._get_disaster_name(disaster_type)

        # 第一段: 总体评价
        overall = self.OVERALL_TEMPLATES.get(grade, self.OVERALL_TEMPLATES["C"])
        paragraph1 = overall.format(disaster=disaster_name)
        paragraph1 = f"【总体评价】{paragraph1} 总分: {total_score:.1f}分 ({grade}级)。"

        # 第二段: 亮点与不足
        paragraph2 = self._gen_strength_weakness(score_breakdown, literacy_profile)

        # 第三段: 改进建议
        paragraph3 = self._gen_recommendation(grade, disaster_type, score_breakdown)

        return f"\n\n".join([paragraph1, paragraph2, paragraph3])

    def _gen_strength_weakness(self, breakdown: dict,
                                literacy: dict | None) -> str:
        """生成亮点与不足段落"""
        lines = ["【亮点与不足】"]

        # 找最高分和最低分维度
        scores = {}
        for dim, name in self.DIMENSION_NAMES.items():
            if dim in breakdown:
                scores[name] = breakdown[dim].get("score", breakdown[dim])

        if not scores:
            lines.append("评分数据缺失。")
            return "\n".join(lines)

        best_dim = max(scores, key=scores.get)
        worst_dim = min(scores, key=scores.get)

        # 亮点
        best_score = scores[best_dim]
        if best_score >= 80:
            lines.append(f"亮点: 你的{best_dim}得分很高 ({best_score:.0f}分)。")
        else:
            lines.append(f"亮点: 各维度表现较为均衡, {best_dim}相对最优 ({best_score:.0f}分)。")

        # 不足
        worst_score = scores[worst_dim]
        if worst_score < 70:
            lines.append(f"不足: {worst_dim}得分偏低 ({worst_score:.0f}分)。")
            # 具体原因
            for dim_key, dim_name in self.DIMENSION_NAMES.items():
                if dim_name == worst_dim and dim_key in breakdown:
                    reason = breakdown[dim_key].get("reason", "")
                    if reason:
                        lines.append(f"  原因: {reason}")
                    break
        else:
            lines.append(f"不足: {worst_dim}仍有提升空间 ({worst_score:.0f}分)。")

        # 素养画像
        if literacy:
            lines.append("")
            for dim, val in literacy.items():
                name_map = {
                    "risk_awareness": "风险意识",
                    "system_thinking": "系统思维",
                    "decision_resilience": "决策韧性"
                }
                dim_name = name_map.get(dim, dim)
                grade_letter = self._score_to_grade(val)
                lines.append(f"素养画像 - {dim_name}: {grade_letter}级 ({val:.0f}分)")

        return "\n".join(lines)

    def _gen_recommendation(self, grade: str, disaster_type: str,
                              breakdown: dict) -> str:
        """生成改进建议段落"""
        lines = ["【改进建议】"]

        case = self.CASE_RECOMMENDATIONS.get(disaster_type,
                                              self.CASE_RECOMMENDATIONS["earthquake"])

        if grade in ("A", "B"):
            lines.append(f"建议: 你的决策能力已经达到较好水平。")
            lines.append(f"可前往'案例库'学习《{case['title']}》案例, "
                         f"{case['focus']}。")
        elif grade == "C":
            lines.append(f"建议: 重点提升经济性和可行性的平衡能力。")
            lines.append(f"前往'案例库'学习《{case['title']}》案例, "
                         f"{case['focus']}。")
        else:
            lines.append(f"建议: 建议重新学习应急决策基础课程, "
                         f"重点理解灾害影响分析和优先级排序逻辑。")
            lines.append(f"之后学习《{case['title']}》案例进行巩固。")

        # 具体维度建议
        worst_dim = None
        worst_score = 100
        for dim_key, dim_name in self.DIMENSION_NAMES.items():
            if dim_key in breakdown:
                s = breakdown[dim_key].get("score", 100)
                if s < worst_score:
                    worst_score = s
                    worst_dim = dim_name

        if worst_dim and worst_score < 70:
            lines.append(f"特别关注{worst_dim}的提升, "
                         f"当前得分{worst_score:.0f}分, 建议针对性练习。")

        return "\n".join(lines)

    def _get_disaster_name(self, disaster_type: str) -> str:
        names = {
            "earthquake": "地震",
            "rainstorm": "暴雨",
            "typhoon": "台风",
            "landslide": "山体滑坡",
            "mudslide": "泥石流",
            "flood": "洪水",
        }
        return names.get(disaster_type, "应急")

    def _score_to_grade(self, score: float) -> str:
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        return "E"
