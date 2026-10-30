"""
v2t/distill_prompts.py — 蒸馏管线的固定提示词（方法的"宪法"）

设计原则：
  1. 版本化：PROMPT_VERSION 变了，缓存的旧结果就不该复用（会写进 distill.json）。
  2. 结构化：每个提示词都锁死 JSON schema，字段名不许改，方便下游渲染与校验。
  3. 可溯源：所有结论都必须带证据锚点（video_id + 时间戳 + 原话），
     没有证据就写 null / 空数组，禁止编造。
  4. 分层：单视频（事实层）→ 跨视频（关系层）→ 方法论（规律层）→ 产品（商业层），
     一层一层往上抬，不允许跳层瞎猜。

改这里的字段 = 改方法本身。改完请同步 docs/distill-method.md。
"""

PROMPT_VERSION = "1.0"

# ============================================================
# 通用约束（拼在每个提示词前面）
# ============================================================

COMMON_RULES = """硬性规则（必须遵守）：
1. 只输出 JSON，不要输出任何解释、前言、Markdown 代码块标记。
2. 只能基于给定的材料推断。材料里没有的，不要编。宁可留空数组/ null，也不要猜。
3. 每个结论尽量带证据：用 {"video_id": "...", "time": "mm:ss", "quote": "原话片段"} 的格式。
4. 原话引用必须与逐字稿一致（可截断，不可改写）。
5. 中文输出。专有名词（产品名、功能名、模型名）保留原文写法。
6. 数字（价格、字数、比例、时长）必须原样保留，不要换算成"大约"。
"""

# ============================================================
# S4：单视频深读
# ============================================================

ANALYZE_VIDEO_SCHEMA = {
    "gist": "str 一句话说清这条视频到底在讲什么（不超过 60 字）",
    "video_type": "str 教学演示 / 访谈 / 宣讲 / 纪录片 / 直播切片 / 其它",
    "audience": "str 这条视频是讲给谁听的",
    "premise": "str 它默认观众已经知道什么（前置知识）",
    "sections": [{"title": "str", "start": "mm:ss", "end": "mm:ss", "summary": "str 这一段讲了什么"}],
    "key_points": [{"point": "str 观点", "why": "str 为什么重要", "evidence": "str 原话"}],
    "steps": [{
        "order": "int 第几步",
        "action": "str 具体做什么（动词开头）",
        "where": "str 在哪个界面/菜单/功能里做",
        "detail": "str 参数、选项、注意事项",
        "evidence": "str 原话",
        "time": "mm:ss",
    }],
    "concepts": [{"name": "str 概念/术语", "definition": "str 视频里的定义", "why_it_matters": "str"}],
    "rules_and_numbers": [{"item": "str 规则/数值", "value": "str 具体数值", "note": "str 条件或例外"}],
    "ui_evidence": ["str 画面里出现的界面元素：按钮/字段/面板/提示文案"],
    "quotes": [{"time": "mm:ss", "text": "str 值得记住的原话"}],
    "pitfalls": ["str 讲师明确提醒的坑、限制、失败情况"],
    "claims": ["str 可被验证的主张或承诺（效果/效率/收益）"],
    "open_questions": ["str 视频没讲清、需要外部验证的点"],
    "one_line_takeaway": "str 如果只能记一句话，记哪句",
}

ANALYZE_VIDEO = """你是资深的内容拆解专家，擅长把一段教学/访谈视频拆成可直接执行的知识。

任务：把下面这条视频的逐字稿（和画面线索）拆解成结构化 JSON。

要求：
- "gist" 必须具体：说清"用什么方法解决什么问题"，不要写"介绍了某产品"这种废话。
- "steps" 只收真正的操作步骤（观众可以照着做的），按时间顺序，动词开头。
  如果视频不是操作类，steps 返回空数组。
- "rules_and_numbers" 专门收价格、字数、比例、时长、额度这类硬数字，一个都不要漏。
- "ui_evidence" 从画面线索和口播里提取界面证据（例如"点击右上角设置面板"）。
- "pitfalls" 是讲师亲口说的限制/坑，不是你自己的评价。
- 章节 sections 按内容转折划分，时间戳用材料里的时间。

JSON schema（字段名严格照抄）：
{schema}

视频信息：
- video_id: {video_id}
- 文件名: {name}
- 时长: {duration}

画面线索（可能为空）：
{frames}

逐字稿（带时间戳）：
{transcript}
"""

# ============================================================
# S5：跨视频综合（去重合并 + 主题图谱 + 冲突）
# ============================================================

SYNTHESIZE_SCHEMA = {
    "corpus_gist": "str 这一批视频合起来在讲一件什么事（100 字内）",
    "what_this_is": "str 这批内容的性质：谁的课/什么产品/什么流派",
    "topics": [{
        "name": "str 主题名",
        "weight": "int 1-5 重要度",
        "summary": "str 这个主题被讲清楚了吗，讲到什么程度",
        "covered_by": ["str video_id"],
        "key_insight": "str 这个主题里最值钱的一句话",
        "gaps": ["str 这个主题没讲透的地方"],
    }],
    "knowledge_units": [{
        "unit": "str 一个可复用的知识点（去重合并后的）",
        "detail": "str 完整说明（把多个视频的碎片拼完整）",
        "merged_from": ["str video_id"],
        "conflicts": "str 若不同视频说法不一致，写清分歧；否则 null",
    }],
    "redundancy": {
        "repeated_intros": ["str 反复出现的开场/口播套路"],
        "repeated_content": ["str 被多个视频重复讲的内容（已合并，不必再看）"],
        "unique_value": [{"video_id": "str", "why": "str 只有这条视频才有的信息"}],
    },
    "learning_path": [{"order": "int", "video_id": "str", "why": "str 为什么按这个顺序看"}],
    "conflicts": [{"issue": "str 分歧点", "sides": ["str 说法A（含 video_id）", "str 说法B（含 video_id）"], "resolution": "str 如何判断"}],
    "missing_pieces": ["str 这批视频都没讲、但要做好这件事必须知道的东西"],
    "master_summary": "str 300-600 字的整体综述：讲什么、怎么讲、值不值得学、学完能做什么",
}

SYNTHESIZE = """你是知识库主编。下面是一批视频的单视频拆解结果（已去重）。

任务：把它们合并成一份"这批内容到底讲了什么"的整体认知，并找出重复、冲突、缺口。

要求：
- "knowledge_units" 是核心：把同一个知识点在不同视频里的碎片合并成一条完整的。
  合并后如果还有分歧，写进 conflicts 字段。目标 20-60 条。
- "redundancy.repeated_content" 要具体点名（哪个功能被讲了几遍），这是"不用再看"的依据。
- "topics" 按重要度排序，weight 5 是最核心。
- "master_summary" 要像给同事做的口头汇报：不吹不黑，讲清价值和局限。

JSON schema（字段名严格照抄）：
{schema}

批次信息：
- 视频数（去重后）: {n_videos}
- 总时长: {duration}

单视频拆解结果：
{analyses}
"""

# ============================================================
# S6：方法论抽象（L0 事实 → L1 原则 → L2 流程 → L3 心智模型）
# ============================================================

METHODOLOGY_SCHEMA = {
    "master_method": {
        "name": "str 这套方法的名字（要准确具体，不要用「某某写作法」这种空话）",
        "one_liner": "str 一句话说清这套方法",
        "problem": "str 它解决什么真实痛点",
        "preconditions": ["str 用这套方法的前提条件"],
        "big_picture": "str 200 字以内讲清整体逻辑：为什么这些步骤要这样排",
        "stages": [{
            "stage": "str 阶段名",
            "goal": "str 这个阶段要达成什么",
            "do": ["str 具体动作"],
            "output": "str 产出物",
            "check": "str 怎么判断这一步做对了",
            "failure": "str 做错了会怎样",
        }],
    },
    "method_cards": [{
        "name": "str 子方法名",
        "layer": "str 原则 / 流程 / 技巧 / 心智模型 四选一",
        "trigger": "str 什么场景下用",
        "statement": "str 方法本身的表述（可迁移，脱离原产品也成立）",
        "procedure": [{"step": "str", "why": "str", "verify": "str 怎么验证做对了"}],
        "heuristics": ["str 经验法则 / 判断口诀"],
        "anti_patterns": ["str 反模式：看起来像但其实是错的"],
        "evidence": [{"video_id": "str", "time": "mm:ss", "quote": "str"}],
        "transfer": ["str 迁移到别的领域怎么用"],
    }],
    "mental_models": [{"model": "str 心智模型", "explain": "str 用人话解释", "use_when": "str"}],
    "decision_table": [{"if": "str 遇到什么情况", "then": "str 怎么选", "because": "str 理由"}],
    "quality_bar": ["str 判断产出好坏的硬标准（可检验）"],
    "levels": {
        "L0_facts": ["str 事实层：这批视频里确凿的事实/操作"],
        "L1_rules": ["str 规律层：从事实里归纳出的一般规律"],
        "L2_method": ["str 方法层：可复用的流程"],
        "L3_model": ["str 模型层：底层心智模型/第一性原理"],
    },
}

METHODOLOGY = """你是方法论提炼专家。给你一批视频的拆解结果和合并后的知识单元。

任务：从"这群人具体怎么操作"里，抽象出一套可迁移的方法论。
关键要求：**必须能脱离原产品独立成立**。
  反例："用星月的续写功能写章节" —— 这是操作，不是方法。
  正例："先定章节目标（读者情绪落点）→ 再给约束（人称/节奏/禁忌）→ 再生成 → 只改冲突不全文重写" —— 这是方法。

分层要求（这是本任务的核心）：
- L0 事实层：视频里确凿的操作和数字。
- L1 规律层：从事实归纳的一般规律（"为什么这样做有效"）。
- L2 方法层：可复用的流程（别人照着能做）。
- L3 模型层：底层心智模型（为什么这个领域是这样运作的）。

"method_cards" 出 4-10 张，每张都要有 anti_patterns 和 transfer。
"quality_bar" 要可检验（例如"任意一章都能指出它的冲突点在哪一句"）。

JSON schema（字段名严格照抄）：
{schema}

材料：
{analyses}

知识单元（已去重合并）：
{knowledge_units}
"""

# ============================================================
# S7：产品逆向（架构 + 商业模式）
# ============================================================

PRODUCT_SCHEMA = {
    "is_product": "bool 这批视频是否在讲一个具体产品/工具/服务",
    "confidence": "float 0-1",
    "why": "str 判断依据（列出触发信号）",
    "product_name": "str 产品名（多个用 / 分隔）",
    "positioning": {
        "what": "str 它是什么（一句话）",
        "for_whom": "str 目标用户（越具体越好）",
        "job_to_be_done": "str 用户雇它来完成什么任务",
        "wedge": "str 切入点是哪个高频痛点",
        "substitutes": ["str 用户不用它会用什么替代（含人工方式）"],
    },
    "architecture": {
        "layers": [{
            "layer": "str 层名（接入层/功能层/AI 能力层/数据层/商业层）",
            "modules": [{"name": "str 模块", "function": "str 作用", "evidence": "str 证据"}],
        }],
        "data_objects": [{"entity": "str 数据实体", "fields": ["str 字段"], "relations": "str 与其他实体的关系"}],
        "core_flows": [{"name": "str 流程名", "steps": ["str 步骤"], "pain_removed": "str 这一步省掉了用户什么工作"}],
        "ai_pipeline": [{"stage": "str 环节", "tech_guess": "str 可能的技术/模型", "why": "str 推断依据"}],
        "mermaid": "str 一段 mermaid graph TD 代码，画出模块关系（节点用中文，不要特殊字符）",
    },
    "business_model": {
        "revenue_streams": [{"stream": "str 收入方式", "mechanism": "str 怎么收", "evidence": "str"}],
        "pricing": [{"plan": "str 套餐名", "price": "str 价格原样", "quota": "str 额度", "unit": "str 计量单位"}],
        "metering_unit": "str 核心计量单位（如 字数 / 次数 / token / 席位）",
        "unit_economics": {
            "cost_drivers": ["str 成本项"],
            "margin_hypothesis": "str 毛利结构推测（标明是推测）",
            "leak_points": ["str 会被薅羊毛/亏钱的地方"],
        },
        "growth": {"channels": ["str 获客渠道"], "funnel": ["str 转化路径"], "retention_hook": ["str 留存钩子"]},
        "moat": ["str 护城河（真实的那种，不是「体验好」）"],
        "risks": ["str 风险：平台依赖/合规/被通用模型吃掉等"],
    },
    "clone_playbook": {
        "mvp_weeks": "str 最小可跑版本需要多久（给区间）",
        "must_have": ["str 必须有"],
        "nice_to_have": ["str 可以有"],
        "skip": ["str 第一期别做"],
        "hardest_part": "str 最难的不是功能，是什么",
        "first_10_users": "str 从哪找前 10 个用户",
    },
    "unknowns": ["str 视频里没说、需要外部验证的商业假设"],
}

PRODUCT = """你是产品架构师 + 商业分析师。给你一批视频的拆解结果。

任务：如果这批视频在讲一个产品，就把它逆向工程出来：产品架构 + 商业模式。
如果判定不涉及产品（纯方法论课、纯访谈），把 is_product 设为 false，其余字段给空值，不要硬编。

逆向推理的要求：
- 从"用户能看到的功能"反推"它背后必须有什么模块"。
  例如：能按章节续写 → 必须有章节大纲数据结构 + 上下文裁剪策略 + 长文一致性校验。
- 从"讲师反复强调的卖点"反推"它靠什么收钱"。
  例如：反复讲"字数消耗规则""套餐区别" → 按字数计量的订阅 + 加油包。
- 从"教学里必须教的步骤"反推"产品没做好的地方"（需要教 = 有摩擦）。
- 所有推测必须标注是推测；有原话证据的写 evidence。
- mermaid 只画模块关系，10-18 个节点，不要画太细。

JSON schema（字段名严格照抄）：
{schema}

材料：
{analyses}

知识单元：
{knowledge_units}

硬数字（价格/额度/规则，来自逐字稿）：
{numbers}
"""

# ============================================================
# 辅助：主题命名（可选，用于规则聚类后的人类可读命名）
# ============================================================

TOPIC_NAMING = """下面是从一批视频里用规则聚类得到的若干关键词簇。
请给每一簇起一个准确的中文主题名（4-10 字），并写一句它在讲什么。
只输出 JSON：{"topics": [{"index": 0, "name": "...", "summary": "..."}]}

关键词簇：
{clusters}
"""


SCHEMAS = {
    "analyze_video": ANALYZE_VIDEO_SCHEMA,
    "synthesize": SYNTHESIZE_SCHEMA,
    "methodology": METHODOLOGY_SCHEMA,
    "product": PRODUCT_SCHEMA,
}
