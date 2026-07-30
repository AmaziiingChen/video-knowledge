from __future__ import annotations

import json
import re
from hashlib import sha256
from collections.abc import Callable
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from urllib.parse import quote

from config import settings
from services.ai_call_logger import ai_call_usage_for_task, attach_ai_calls_to_content
from services.database import connect, ensure_database_initialized, initialize_database, utc_now_iso
from services.markdown_sync import save_markdown_draft_and_sync
from services.content_source_text import load_content_source_text
from services.content_index import ensure_managed_folder
from services.repository import ContentRepository, new_id
from services.campus_sources import CAMPUS_SOURCES
from services.campus_source_settings import load_campus_source_settings
from services.group_report_pipeline import (
    GROUP_REPORT_MODEL_CHAIN,
    OVERVIEW_TASK,
    SECTION_PLAN_TASK,
    SECTION_WRITER_TASK,
    GroupReportContext,
    GroupReportSource,
    generate_group_report,
    _source_footnote,
)
from services.prompt_file_store import remove_report_prompt_files, sync_report_prompt_files, write_report_prompt_file


REPORT_PROMPT_TYPE = "group_context"
LEGACY_REPORT_PROMPT_TYPE = "range"
REPORT_STAGE_TYPES = (
    SECTION_PLAN_TASK,
    SECTION_WRITER_TASK,
    OVERVIEW_TASK,
)
REPORT_TYPES = (REPORT_PROMPT_TYPE, *REPORT_STAGE_TYPES)
GENERATABLE_REPORT_TYPES = ("daily", "weekly", LEGACY_REPORT_PROMPT_TYPE)
DEFAULT_REPORT_PROMPT_VERSION = "group-report-editorial-v17"
CUSTOM_REPORT_PROMPT_VERSION = "custom"
ReportProgressCallback = Callable[[dict[str, object]], None]


def _record_report_prompt_version(
    connection,
    prompt_id: str,
    change_kind: str,
) -> None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wechat_report_prompt_versions'"
    ).fetchone()
    if table is None:
        return
    row = connection.execute(
        "SELECT * FROM wechat_report_prompts WHERE id=?",
        (prompt_id,),
    ).fetchone()
    if row is None:
        return
    template = str(row["template"])
    connection.execute(
        """INSERT OR IGNORE INTO wechat_report_prompt_versions
           (id,prompt_id,group_id,report_type,template,template_hash,
            template_version,display_name,change_kind,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            new_id(),
            row["id"],
            row["group_id"],
            row["report_type"],
            template,
            sha256(template.encode("utf-8")).hexdigest(),
            str(row["template_version"] or ""),
            row["display_name"],
            change_kind,
            utc_now_iso(),
        ),
    )


def _default_report_prompt(report_type: str = REPORT_PROMPT_TYPE) -> str:
    defaults = {
        REPORT_PROMPT_TYPE: """说明这个分组覆盖的主题、主要读者、阅读目标和长期的判断边界。这里不重复通用的证据、引用和 Markdown 规则；它会作为所有阶段的领域语境。

尚未添加分组特定要求时：按来源材料的实际主题自然组织，不预设固定栏目，也不以读者相关性为由静默删除宏观信息。""",
        SECTION_PLAN_TASK: """补充该分组在“栏目规划”阶段的规则：哪些信息维度应优先阅读、适合如何自然分栏、何时应拆分独立主题。不要预设所有时期都必须出现的固定栏目。""",
        SECTION_WRITER_TASK: """补充该分组在“栏目写作”阶段的呈现规则：何时使用短段、无序列表、有序列表或 Markdown 子标题；各类材料应保留到什么颗粒度。不要重复通用的来源覆盖和引用格式。""",
        OVERVIEW_TASK: """补充该分组在“本期概览”阶段的读者视角、语气和应突出的整体脉络。概览只提供阅读线索，不替代任何栏目或来源。""",
    }
    return defaults.get(report_type, defaults[REPORT_PROMPT_TYPE])


def _campus_report_prompts(report_type: str) -> str:
    prompts = {
        REPORT_PROMPT_TYPE: """分组主题：校园生活。这里的“校园生活”指学校及其各单位公开发布、会影响校内成员认知、判断或行动的校园公共信息，不仅包括衣食住行和学生活动，也包括教学教务、招生就业、科研学术、学校治理、校企合作、国际交流、党建团学、社会实践、人物与校园文化。

潜在读者包括本科生、研究生、毕业生、教职工、科研人员、考生家长和社会公众。写作时必须根据材料识别实际适用对象，不得默认所有信息都面向全体学生。

报告的目标是呈现本期校园发生了什么变化、哪些安排被发布、哪些结果已经形成，以及不同信息之间的实际联系。每篇非广告材料都应被处理；处理全部来源不等于复述来源中的全部细节。重复稿不重复写正文，而是在合并事件末尾共同引用。混合材料只删除商业促销和与校园事实无关的内容。

来源篇幅、宣传口吻和发布层级不等于事件重要程度。详略应根据影响范围、变化程度、结果价值、当前新增信息和材料可信度判断。长期指南、经验问答与常规规则只保留本期新发布、新变化及理解当前事项所必需的内容；其余细节由读者查看原文。

区分学校及其单位确认的规则、来源主体的陈述和社区个人经验。不得把非官方建议或个人意见写成普遍规则，也不得为增加可读性放大个人债务、家庭矛盾、感情纠纷等敏感细节。""",
        SECTION_PLAN_TASK: """先识别事件关系，再规划栏目。不要直接根据文章来源、发布部门或标题关键词分栏。

1. 将同一事件的原稿、转载、补充报道和不同渠道发布合并为一个事件簇；后续共同引用。仅重复已有事实的来源可以只作为 supporting_sources，不必强行获得主栏目。更新通知以最新有效规则为主，必要时说明变化。
2. 相同标题不必然是重复稿。不同日期、期次、适用对象或条件的周期性内容应视为不同事项。
3. 同类但不同事件的招聘、申报、讲座、竞赛、实践团队和服务事项可以组成一个信息块，每项保留自身差异。
4. 一篇来源包含多个独立事项时，主栏目只作为调度归属；其他独立事项可以通过 supporting_sources 跨栏使用，并明确 use_scope，不得因唯一主归属丢失内容。同一事件只能安排在一个写作栏目中；重复稿和只补充同一事件证据的来源必须留在该事件所在栏目，不得借 supporting_sources 在另一栏目再次展开。
5. 栏目按照本期真实信息脉络、适用对象和读者任务自然形成，不按来源逐篇排列，也不预设栏目数、事件数或篇幅配额。每个栏目必须能够用共同事实关系、共同适用对象或共同读者任务解释其边界；不得用空泛的“动态”“要闻”“综合”等容器拼接互不相关的低量事项。确无关联的内容可以形成简短独立栏目，不得为了减少栏目数牺牲栏目内聚性。排序时优先安排直接影响学生行动、学习与发展的内容，包括安全与服务变化、教学培养、招生就业、竞赛机会与结果、校园生活和学生实践；其中有明确时间、规则变化或办理要求的事项先于一般回顾。主要面向教师科研人员或少数岗位的例行申报、内部行政事项后置；党建思政、例行会议和宣传性活动默认精简置后。若后置类型确实包含影响广泛的规则变化、学生办理事项或重要结果，仍按实际影响提升位置，不得机械套用固定顺序。来源数量、发布频率和原文总长度不能决定栏目位置或篇幅；同一高频主体存在多个独立事件时可以分别归入准确栏目，但 report_strategy 必须按实际影响和新增事实控制其全篇总占比，不能让发布频率自动转化为跨栏目的重复展开。
6. 对每个事件判断其适用对象和写作层级。详略根据影响范围、本期新增或变化、结果价值、代表性和理解成本决定。行动型事项在 writing_brief 中要求保留材料给出的对象、绝对日期、入口、条件和明确变化；系统与分组提示词中的事实、时间和引用规则是硬约束，writing_brief 不得要求保留“正在进行中”“即将截止”“目前有效”等相对状态，即使这些词出现在来源标题或正文中，也不得根据报告生成时刻重新计算。
7. 信息密集时主动合并同类事件并建立清晰 H3、列表或表格；信息稀疏时不填充、不扩写背景。同一事件连续发布的日志、日更、阶段报道、筹备记录和进展通报，应先识别最终进展、关键变化、累计结果、代表性节点与实际影响，再合并成一条事实线。不改变事件状态的仪式性环节、常规准备、一般交流和重复检查等过程细节应压缩或省略。除非时间顺序直接决定因果关系、规则变化或读者行动，writing_brief 本身也不得按发布日期枚举正文提纲；需要保留时间线时须说明原因。source_ids 的完整覆盖只决定事实与引用不能遗漏，不能据此要求逐篇、逐日或逐人展示；同一连续过程中的材料应在 writing_brief 中明确为共同支撑来源。长期指南、经验问答和常规规则不得规划成完整手册。
8. report_strategy 说明本期主要脉络、栏目顺序、各栏相对于全篇的详略层级及栏目之间的篇幅平衡。每个 writing_brief 必须写明本栏面向谁、包含哪些事件簇、哪些来源合并、哪些详细或精简，以及适合段落、H3、列表或表格中的哪种形式。栏目标题使用准确、克制的事实类别或读者任务，不继承来源中的宣传性修饰。
9. 招聘岗位、科研申报、录取批次、系列人物等同构材料数量较多时，writing_brief 必须要求先写共同事实或总体规模，再按对象、方向、绝对日期、条件或代表性差异分组压缩；不得为每篇来源安排等长正文。人物数、项目数、团队数、单位数和事件数按不同实体去重，不得用来源篇数代替；“X篇”必须与去除重复稿、转载稿后的不同原始文章数量一致，“X人”“X个项目”等实体总数必须能够逐项对应到相同数量的不同实体。无法可靠逐项核对时，writing_brief 不得引入精确总数，改用“多篇”“多位”“多个”等表达。推荐表格或列表后，不得再要求正文逐项重复同一组字段。
10. 完全不含校园有效信息的纯商业广告才放入 excluded_source_ids。重复稿、内部通知、宏观信息和覆盖对象较窄的事项不能仅因“不够重要”而排除。""",
        SECTION_WRITER_TASK: """校园生活写作以完整、可扫描、可核对和不过度展开为目标。先在内部判断每个信息单元的事件关系、适用对象、时间关系和详略层级，再开始写作，不输出判断过程，并服从全局 report_strategy 与当前栏 writing_brief。

1. 以事件或信息块为单位写作，不按来源逐篇复述。同一事件的重复稿、转载稿和互补稿合成一条事实线；各来源共同放在事件末尾引用。计划中的辅助来源若只重复同一事件，只追加引用，不另写一个段落或 H3。
2. 行动型信息保留会改变行动的对象、时间、地点、入口、条件、变化和必要例外。不同对象适用不同规则时必须分别写清，不得合成一条模糊规则。
3. 同字段的录取、比赛结果、课程、岗位和服务数据适合使用表格；同类但不同事件适合无序列表；明确步骤或确实影响因果、规则或行动的时间序列才使用有序列表。不要为了整齐强行使用表格；表格或列表已经完整表达的字段，正文只补充共同背景、重要变化和必要例外，不得再逐项复述。
4. 招聘、申报、讲座、竞赛和活动机会重点保留对象、方向、绝对日期、地点、入口和特殊条件；删除机构历史、福利宣传、互动抽奖和冗长主办名单。同一时期多家企业招聘应合成一个信息块。条目较少时可每家公司一个无序列表项；条目很多时先归纳共同条件和总体规模，再按岗位方向、对象、日期或特殊条件分组，只保留有实际差异的信息。
5. 会议、治理、党建、行政和校企合作保留实际决定、制度变化、部署、成果及后续影响。党建思政、主题党日、理论学习和例行组织活动如未带来面向师生的规则变化、办理事项或可验证成果，合并为简讯，只保留主体、主题和实质动作或结果；不得展开学习材料目录、讲话与文件清单、视频片名、仪式流程、人员名单和宣传口号。涉及明确适用对象、绝对日期或办理入口的事务通知，保留这些行动信息，但仍简洁呈现。
6. 社会实践、系列项目和多支团队按共同主题组成信息块，每项保留主体、地点、做什么及代表性成果；只有信息量和成果确实突出的案例才展开。同一事件连续发布的日志、日更、阶段报道、筹备记录和进展通报，按最终进展、关键变化、累计结果、代表性节点与实际影响合并，不按发布日期或每日过程写成流水账。判断某个过程节点是否保留时，检查删除该节点是否会改变事件结论、状态、因果关系、规则或读者行动；不会改变则压缩或省略。只有时间顺序直接决定上述关系时，才保留必要时间线；writing_brief 即使枚举了每日材料，也不能据此恢复成逐日正文。
7. 人物、校友和校园文化稿保留最能说明经历、成果、方法或变化的内容，不复制完整履历、奖项清单和宣传性评价。同一系列人物较多时按升学、就业方向、实践方法或共同经验归纳，不逐人等长复述；代表性案例可以点名，其余来源在对应信息块末尾共同引用。人物总数按不同人物去重，不得把一人多稿或转载篇数当成人数；“X篇”必须与去除重复稿、转载稿后的不同原始文章数量一致，“X人”等实体总数必须能够逐项对应到相同数量的不同实体，无法可靠核对时改用“多篇”“多位”等表达。来源中的“下期预告”“敬请期待”“我们将推出”“欢迎关注”等编辑包装不得继承为报告自身的承诺、预告或号召。非官方攻略、问答和社区讨论必须注明其经验或讨论属性，不得把个体意见写成学校规则；涉及个人债务、家庭矛盾、感情纠纷等内容时只概括讨论主题，不复述可识别或猎奇细节。
8. 面向少数教职工、科研人员或行政部门的例行通知，应先标明适用对象，再简洁说明新增要求、截止时间或流程变化；不要把内部流程写成全校性大事。
9. 同一事项出现更新、补充或冲突时，以发布时间更晚且更接近原始发布部门的材料作为有效规则；不同统计口径无法统一时说明口径，不擅自裁决。
10. 来源发布时间不等于事件发生时间。旧事件必须写明实际时间或使用过去时；长期指南只有在本期出现更新或重新发布时才重点说明新增内容。忠实保留原文给出的绝对日期、时间范围和明确的取消、延期、恢复或规则变化。即使来源标题或正文写有“正在进行中”“即将截止”“当前有效”等表达，也不得根据报告生成时刻沿用或重新计算状态；“今天”“今晚”“明天”等仅在能够可靠换算时改为绝对日期，否则省略相对状态，不猜测。
11. 来源已经公开刊载、且确实影响读者行动的登录方式、初始规则和联系方式可以忠实保留；不得补充来源未公开的信息，也不得无必要地扩写身份证信息、完整名单等个人数据。
12. 原文只有图片、OCR 严重损坏或信息不足时，只写能够确认的核心事项；不能确认时不猜测，也不暴露管线语言。
13. 原文长度、宣传力度、同一主体的发布频率和来源数量不能决定篇幅。优先展开影响范围广、本期新增或变化明确、结果价值高和具有代表性的内容；例行、重复、低新增信息和长期不变的背景规则应压缩。同一主体在多个栏目出现时，每个栏目只保留与该栏目任务直接相关的新增事实，并从全篇视角避免重复背景和重复评价。批量岗位、批量申报、连续进展和系列人物先合并共同信息，再保留必要差异，不得因为来源数量多就逐项等长展开。即使 writing_brief 枚举了多篇材料、日期或人物，也只能将其视为覆盖清单，不能恢复为逐项正文提纲。处理全部来源不等于复述全部事实，未展开的细节由引用指向原文。正文和 H3 使用准确、克制的事实表达，不照搬来源中的宣传性标题。

栏目内有两个以上可独立阅读的方向时使用 H3；H3 表示信息组，不表示文章来源。Markdown 表格的表头、分隔行和全部数据行必须连续，不能在数据行之间插入解释段落；需要补充规则时放在表格前后。引用去重以事件或信息块为作用域，不以全文、栏目或来源为作用域。写作前在内部建立“事件或信息块—全部支撑来源”的对应关系：事件内部的段落、列表或表格尚未写完时不落引用，完成后只在最后一个有效句子或对应的最后一个列表项、表格行末尾一次性列出全部支撑来源，然后再进入下一事件。同一来源确实包含多个相互独立的事件或主题时，可以在各事件末尾分别引用，不得为追求来源编号全文唯一而删除必要引用。不同列表项或表格行实际代表不同事件且来源不同时，应分别在对应项末尾引用，不能在整张表或整组列表之后放置无法对应事实的笼统引用。不得输出只有引用标记的独立一行。

输出前在内部自检但不输出检查过程：删除相对状态判断和来源编辑口吻；核对总数与不同实体数；合并不影响因果、规则或行动的逐日过程；删除同一事件内的重复来源标记并保留事件末尾的完整引用；删除表格、列表与相邻正文之间的重复事实。""",
        OVERVIEW_TASK: """校园生活概览应从本期正文的实际占比和变化中提炼一条主状态及必要的并行脉络，不预设每期都必须同时出现“校园运行”和“学校发展”两条主线。开头直接写本期校园实际发生的变化、形成的结果或并行存在的事实，不从“这份报告收集、整理、涵盖了什么”起笔。

概览按对校园生活主要读者的实际影响组织，不按栏目顺序或正文篇幅分配句子。直接影响学生行动、学习与发展的安全服务、教学培养、招生就业、竞赛机会与结果、校园生活和学生实践优先形成主要脉络；主要面向教师科研人员或少数岗位的例行科研申报、内部行政事项，以及常规党建思政和宣传性活动，可以使用准确的上位概念简短合并，或只留在正文。若这些后置类型确实包含影响广泛的规则变化、学生办理事项或重要结果，则按实际影响纳入主要脉络。科研项目申报属于科研脉络，不得并入“就业与升学”；招生录取、教学培养、就业招聘和科研申报等性质不同的事项应分别使用准确类别承接。

概览不承担逐栏覆盖。信息脉络集中时使用短段；并行脉络较多、需要三个以上自然段才能交代时，必须使用一个短引导段配合无序列表，不得把概览写成连续多段的压缩目录。列表项必须概括跨栏目的读者脉络，不得一栏对应一项。涉及时间敏感事项时，只客观概括正文确认的绝对日期、安排和来源明确说明的变化，不根据报告生成时刻添加“目前仍在”“即将截止”“已经结束”等实时判断。正文只确认“发布、启动、进入公示期、计划、预计”时，概览不得改写为“已完成、已结束、已经落实”；涉及人物、项目、团队、单位或事件总数时，必须与正文中去重后的实际实体数量一致，无法核对时不写总数。

概览中的每个句子都应提供实质事实、共同变化或内容之间的真实联系；只说明文章结构、制作过程、来源用途或阅读方式的句子应删除。不得统计栏目数或主题数，不得复制栏目标题组成“涵盖……等主题”的清单，不得出现“下文按……展开”“保留来源以便核对”“正文分为……”等元叙述。不同脉络没有事实联系时可以并列陈述，不为追求一句总括而强行归因或归类。

采用校园资讯报告的平实、克制语体，既不写成行政公文，也不写成面向学生的口语推荐。避免直接称呼“你”“同学们”，避免“学生必看”“建议先浏览”“值得一看”等表达。""",
    }
    return prompts[report_type]


def _ensure_default_prompts(connection, group_id: str) -> None:
    """Keep one context prompt and three active stage adapters for every report group."""
    existing_types = {
        str(row["report_type"])
        for row in connection.execute(
            "SELECT report_type FROM wechat_report_prompts WHERE group_id=?",
            (group_id,),
        ).fetchall()
    }
    missing_types = [
        prompt_type for prompt_type in REPORT_TYPES if prompt_type not in existing_types
    ]
    if not missing_types:
        return
    now = utc_now_iso()
    group = connection.execute(
        "SELECT name FROM wechat_subscription_groups WHERE id=?", (group_id,)
    ).fetchone()
    group_name = str(group["name"]) if group else ""
    for prompt_type in missing_types:
        template = _campus_report_prompts(prompt_type) if group_name == "校园生活" else _default_report_prompt(prompt_type)
        connection.execute(
            """INSERT OR IGNORE INTO wechat_report_prompts
               (id, group_id, report_type, template, template_version, display_name, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), group_id, prompt_type, template, DEFAULT_REPORT_PROMPT_VERSION, _report_prompt_display_name(prompt_type), now, now),
        )
    rows = connection.execute(
        "SELECT id FROM wechat_report_prompts WHERE group_id=? AND report_type IN ({})".format(
            ",".join("?" for _ in missing_types)
        ),
        (group_id, *missing_types),
    ).fetchall()
    for row in rows:
        _record_report_prompt_version(connection, str(row["id"]), "ensure_default")


def _report_prompt_display_name(report_type: str) -> str:
    return {
        REPORT_PROMPT_TYPE: "组别说明",
        SECTION_PLAN_TASK: "栏目规划",
        SECTION_WRITER_TASK: "栏目写作",
        OVERVIEW_TASK: "概览写作",
    }.get(report_type, "分组报告提示词")


def sync_builtin_report_prompt_definitions(connection) -> None:
    """Publish changed group-adapter defaults once without replacing UI edits."""
    for prompt_type in REPORT_TYPES:
        key = f"builtin:wechat_reports:{prompt_type}"
        # Campus rules are a shipped starting point; other groups receive the
        # neutral adapter until their owner writes a domain-specific one.
        fingerprint = sha256((prompt_type + _default_report_prompt(prompt_type) + _campus_report_prompts(prompt_type)).encode("utf-8")).hexdigest()
        state = connection.execute(
            "SELECT template_hash FROM prompt_code_sync_state WHERE default_key=?", (key,)
        ).fetchone()
        legacy = connection.execute(
            """SELECT 1 FROM wechat_report_prompts
               WHERE report_type=? AND template_version IN ('', 'group-report-editorial-v1', 'group-report-editorial-v2', 'group-report-editorial-v3')
               LIMIT 1""",
            (prompt_type,),
        ).fetchone()
        if state is not None and str(state["template_hash"]) == fingerprint and legacy is None:
            continue
        now = utc_now_iso()
        rows = connection.execute(
            """SELECT p.id, p.group_id, p.report_type, p.template, p.template_version,
                      COALESCE(NULLIF(p.display_name, ''), '分组报告提示词') AS display_name,
                      p.updated_at, g.name AS group_name
               FROM wechat_report_prompts p
               JOIN wechat_subscription_groups g ON g.id=p.group_id
               WHERE p.report_type=? AND p.template_version != ?""",
            (prompt_type, CUSTOM_REPORT_PROMPT_VERSION),
        ).fetchall()
        for row in rows:
            template = _campus_report_prompts(prompt_type) if str(row["group_name"]) == "校园生活" else _default_report_prompt(prompt_type)
            connection.execute(
                "UPDATE wechat_report_prompts SET template=?, template_version=?, updated_at=? WHERE id=?",
                (template, DEFAULT_REPORT_PROMPT_VERSION, now, row["id"]),
            )
            _record_report_prompt_version(connection, str(row["id"]), "builtin_sync")
            updated = dict(row)
            updated.update(template=template, template_version=DEFAULT_REPORT_PROMPT_VERSION, updated_at=now)
            write_report_prompt_file(updated)
        connection.execute(
            """INSERT INTO prompt_code_sync_state(default_key, template_hash, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(default_key) DO UPDATE SET
                 template_hash=excluded.template_hash, updated_at=excluded.updated_at""",
            (key, fingerprint, now),
        )


def list_groups() -> list[dict]:
    ensure_database_initialized()
    with connect() as connection:
        rows = connection.execute(
            """SELECT
                 g.*, COUNT(m.subscription_id) AS subscription_count,
                 (
                   SELECT r.content_item_id FROM wechat_reports r
                   WHERE r.group_id = g.id
                   ORDER BY r.created_at DESC LIMIT 1
                 ) AS latest_report_content_item_id,
                 (
                   SELECT r.report_type FROM wechat_reports r
                   WHERE r.group_id = g.id
                   ORDER BY r.created_at DESC LIMIT 1
                 ) AS latest_report_type,
                 (
                   SELECT r.created_at FROM wechat_reports r
                   WHERE r.group_id = g.id
                   ORDER BY r.created_at DESC LIMIT 1
                 ) AS latest_report_created_at,
                 (
                   SELECT COUNT(*) FROM rss_source_group_memberships rss_membership
                   WHERE rss_membership.group_id = g.id
                 ) AS rss_source_count,
                 COALESCE(s.enabled, 0) AS schedule_enabled,
                 COALESCE(s.report_type, 'weekly') AS schedule_report_type,
                 COALESCE(s.weekdays_json, '[1]') AS schedule_weekdays_json,
                 COALESCE(s.time_of_day, '09:00') AS schedule_time_of_day,
                 COALESCE(s.last_status, 'idle') AS schedule_last_status,
                 COALESCE(s.last_error, '') AS schedule_last_error,
                 s.last_run_at AS schedule_last_run_at
               FROM wechat_subscription_groups g
               LEFT JOIN wechat_subscription_group_memberships m ON m.group_id = g.id
               LEFT JOIN wechat_report_group_schedules s ON s.group_id = g.id
               GROUP BY g.id
               ORDER BY g.sort_order, g.created_at"""
        ).fetchall()

    campus_source_counts: dict[str, int] = {}
    for source in load_campus_source_settings():
        for group_id in source.get("group_ids", []):
            key = str(group_id)
            campus_source_counts[key] = campus_source_counts.get(key, 0) + 1

    groups = []
    for row in rows:
        group = dict(row)
        # Kept only in the database for old installations. Source membership is
        # now the sole authority for a report group's campus content.
        group.pop("include_campus_sources", None)
        group_id = str(group["id"])
        campus_source_count = campus_source_counts.get(group_id, 0)
        group["campus_source_count"] = campus_source_count
        group["rss_source_count"] = int(group.get("rss_source_count") or 0)
        group["schedule_enabled"] = bool(group.get("schedule_enabled"))
        group["schedule_report_type"] = str(group.get("schedule_report_type") or "weekly")
        group["schedule_weekdays"] = _normalize_schedule_weekdays(
            group.pop("schedule_weekdays_json", "[1]")
        )
        group["schedule_time_of_day"] = _normalize_schedule_time(
            group.get("schedule_time_of_day") or "09:00"
        )
        group["source_count"] = (
            int(group.get("subscription_count") or 0)
            + campus_source_count
            + int(group["rss_source_count"])
        )
        groups.append(group)
    return groups


def update_report_schedule(
    group_id: str,
    *,
    enabled: bool,
    report_type: str,
    weekdays: list[int],
    time_of_day: str,
) -> dict:
    """Store a deliberate local schedule without scheduling an immediate run."""
    cleaned_type = str(report_type or "").strip()
    if cleaned_type not in {"daily", "weekly"}:
        raise ValueError("定时生成类型只能是日报或周报")
    cleaned_weekdays = _normalize_schedule_weekdays(weekdays)
    cleaned_time = _normalize_schedule_time(time_of_day)
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        group = connection.execute(
            "SELECT id FROM wechat_subscription_groups WHERE id=?", (group_id,)
        ).fetchone()
        if group is None:
            raise LookupError("报告分组不存在")
        connection.execute(
            """INSERT INTO wechat_report_group_schedules
               (group_id, enabled, report_type, weekdays_json, time_of_day,
                last_run_slot, last_status, last_error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, '', 'idle', '', ?, ?)
               ON CONFLICT(group_id) DO UPDATE SET
                 enabled=excluded.enabled,
                 report_type=excluded.report_type,
                 weekdays_json=excluded.weekdays_json,
                 time_of_day=excluded.time_of_day,
                 updated_at=excluded.updated_at""",
            (
                group_id,
                int(bool(enabled)),
                cleaned_type,
                json.dumps(cleaned_weekdays, ensure_ascii=False),
                cleaned_time,
                now,
                now,
            ),
        )
        connection.commit()
    return get_report_schedule(group_id)


def get_report_schedule(group_id: str) -> dict:
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """SELECT group_id, enabled, report_type, weekdays_json, time_of_day,
                      last_status, last_error, last_run_at
               FROM wechat_report_group_schedules WHERE group_id=?""",
            (group_id,),
        ).fetchone()
    if row is None:
        return {
            "group_id": group_id,
            "enabled": False,
            "report_type": "weekly",
            "weekdays": [1],
            "time_of_day": "09:00",
            "last_status": "idle",
            "last_error": "",
            "last_run_at": None,
        }
    value = dict(row)
    return {
        "group_id": str(value["group_id"]),
        "enabled": bool(value.get("enabled")),
        "report_type": str(value.get("report_type") or "weekly"),
        "weekdays": _normalize_schedule_weekdays(value.get("weekdays_json")),
        "time_of_day": _normalize_schedule_time(value.get("time_of_day") or "09:00"),
        "last_status": str(value.get("last_status") or "idle"),
        "last_error": str(value.get("last_error") or ""),
        "last_run_at": value.get("last_run_at"),
    }


def _normalize_schedule_weekdays(value: object) -> list[int]:
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("定时星期设置无效") from exc
    if not isinstance(raw, list):
        raise ValueError("请至少选择一个执行星期")
    weekdays = sorted({int(item) for item in raw})
    if not weekdays or any(day < 1 or day > 7 for day in weekdays):
        raise ValueError("执行星期必须是周一至周日")
    return weekdays


def _normalize_schedule_time(value: object) -> str:
    cleaned = str(value or "").strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", cleaned):
        raise ValueError("执行时间必须是 HH:MM")
    return cleaned


def create_group(name: str, description: str = "") -> dict:
    initialize_database(); now = utc_now_iso(); group_id = new_id()
    cleaned_name = name.strip()
    prompt_rows: list[dict] = []
    with connect() as connection:
        connection.execute(
            """INSERT INTO wechat_subscription_groups
               (id,name,description,include_campus_sources,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (group_id, cleaned_name, description.strip(), 0, now, now),
        )
        _ensure_default_prompts(connection, group_id)
        connection.commit()
        group = dict(connection.execute("SELECT * FROM wechat_subscription_groups WHERE id=?", (group_id,)).fetchone())
        rows = connection.execute(
            """SELECT p.id, p.group_id, p.report_type, p.template, p.template_version,
                      COALESCE(NULLIF(p.display_name, ''), '分组报告提示词') AS display_name,
                      p.updated_at, g.name AS group_name
               FROM wechat_report_prompts p
               JOIN wechat_subscription_groups g ON g.id=p.group_id
               WHERE p.group_id=? ORDER BY p.report_type""",
            (group_id,),
        ).fetchall()
        prompt_rows = [dict(row) for row in rows]
        group.pop("include_campus_sources", None)
    for prompt_row in prompt_rows:
        write_report_prompt_file(prompt_row)
    return group


def delete_group(group_id: str) -> dict:
    """Delete a report group and remove that label from every subscription."""
    initialize_database()
    prompt_ids: list[str] = []
    with connect() as connection:
        group = connection.execute(
            "SELECT id, name FROM wechat_subscription_groups WHERE id=?",
            (group_id,),
        ).fetchone()
        if not group:
            raise LookupError("公众号分组不存在")
        membership_count = int(connection.execute(
            "SELECT COUNT(*) FROM wechat_subscription_group_memberships WHERE group_id=?",
            (group_id,),
        ).fetchone()[0])
        prompt_ids = [
            str(row["id"])
            for row in connection.execute(
                "SELECT id FROM wechat_report_prompts WHERE group_id=?", (group_id,)
            ).fetchall()
        ]
        # Clear both the current many-to-many relationship and the legacy
        # single-group column so old databases cannot expose a stale tag.
        connection.execute(
            "DELETE FROM wechat_subscription_group_memberships WHERE group_id=?",
            (group_id,),
        )
        connection.execute(
            "UPDATE wechat_subscriptions SET group_id=NULL WHERE group_id=?",
            (group_id,),
        )
        connection.execute("DELETE FROM wechat_subscription_groups WHERE id=?", (group_id,))
        connection.commit()
    remove_report_prompt_files(prompt_ids)
    return {
        "success": True,
        "id": group_id,
        "name": str(group["name"]),
        "affected_subscription_count": membership_count,
    }


def list_report_prompts() -> list[dict]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT p.id, p.group_id, p.report_type, p.template, p.template_version,
                      COALESCE(NULLIF(p.display_name, ''), '区间报告') AS display_name,
                      p.updated_at, g.name AS group_name
               FROM wechat_report_prompts p
               JOIN wechat_subscription_groups g ON g.id = p.group_id
               WHERE p.report_type IN ({})
               ORDER BY g.sort_order, g.created_at,
                        CASE p.report_type
                          WHEN 'group_context' THEN 0
                          WHEN 'group_report_source_summary' THEN 1
                          WHEN 'group_report_section_plan' THEN 2
                          WHEN 'group_report_section_writer' THEN 3
                          WHEN 'group_report_overview' THEN 4 ELSE 9 END""".format(
                ",".join("?" for _ in REPORT_TYPES)
            ),
            REPORT_TYPES,
        ).fetchall()
    return [dict(row) for row in rows]


def update_report_prompt(
    group_id: str,
    report_type: str,
    template: str | None,
    *,
    display_name: str | None = None,
) -> dict:
    cleaned = template.strip() if template is not None else None
    cleaned_name = display_name.strip() if display_name is not None else None
    if report_type not in REPORT_TYPES:
        raise ValueError("报告类型无效")
    if template is not None and not cleaned:
        raise ValueError("提示词不能为空")
    if display_name is not None and not cleaned_name:
        raise ValueError("提示词名称不能为空")
    initialize_database()
    with connect() as connection:
        group = connection.execute("SELECT id FROM wechat_subscription_groups WHERE id=?", (group_id,)).fetchone()
        if not group:
            raise LookupError("公众号分组不存在")
        _ensure_default_prompts(connection, group_id)
        connection.execute(
            """UPDATE wechat_report_prompts
               SET template=COALESCE(?, template),
                   display_name=COALESCE(?, display_name),
                   template_version=CASE WHEN ? IS NULL THEN template_version ELSE ? END,
                   updated_at=?
               WHERE group_id=? AND report_type=?""",
            (
                cleaned,
                cleaned_name,
                cleaned,
                CUSTOM_REPORT_PROMPT_VERSION,
                utc_now_iso(),
                group_id,
                report_type,
            ),
        )
        row = connection.execute(
            """SELECT p.id, p.group_id, p.report_type, p.template, p.template_version,
                      COALESCE(NULLIF(p.display_name, ''), '区间报告') AS display_name,
                      p.updated_at, g.name AS group_name
               FROM wechat_report_prompts p JOIN wechat_subscription_groups g ON g.id=p.group_id
               WHERE p.group_id=? AND p.report_type=?""",
            (group_id, report_type),
        ).fetchone()
        _record_report_prompt_version(connection, str(row["id"]), "user_update")
        connection.commit()
        result = dict(row)
        write_report_prompt_file(result)
        return result


def reset_report_prompt(group_id: str, report_type: str) -> dict:
    """Restore the built-in editorial template and its non-custom version."""
    if report_type not in REPORT_TYPES:
        raise ValueError("报告类型无效")
    initialize_database()
    with connect() as connection:
        group = connection.execute("SELECT name FROM wechat_subscription_groups WHERE id=?", (group_id,)).fetchone()
    template = _campus_report_prompts(report_type) if group and str(group["name"]) == "校园生活" else _default_report_prompt(report_type)
    result = update_report_prompt(group_id, report_type, template)
    initialize_database()
    with connect() as connection:
        connection.execute(
            "UPDATE wechat_report_prompts SET template_version=?, updated_at=? WHERE id=?",
            (DEFAULT_REPORT_PROMPT_VERSION, utc_now_iso(), result["id"]),
        )
        _record_report_prompt_version(connection, str(result["id"]), "reset_builtin")
        connection.commit()
        row = connection.execute(
            """SELECT p.id, p.group_id, p.report_type, p.template, p.template_version,
                      COALESCE(NULLIF(p.display_name, ''), '区间报告') AS display_name,
                      p.updated_at, g.name AS group_name
               FROM wechat_report_prompts p JOIN wechat_subscription_groups g ON g.id=p.group_id WHERE p.id=?""",
            (result["id"],),
        ).fetchone()
    final = dict(row)
    write_report_prompt_file(final)
    return final


def preflight_report(
    group_id: str,
    report_type: str,
    period_end: date | None = None,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    include_external_imports: bool = False,
) -> dict[str, object]:
    """Inspect report scope, summary cache and bounded call shape without invoking a model."""
    if report_type not in GENERATABLE_REPORT_TYPES:
        raise ValueError("报告类型无效")
    initialize_database()
    if (window_start is None) != (window_end is None):
        raise ValueError("报告时间窗口必须同时包含开始时间和结束时间")
    if report_type == "range" and (window_start is None or window_end is None):
        raise ValueError("区间汇总必须提供开始时间和结束时间")
    end = period_end or (
        window_end.date() if window_end is not None else datetime.now().astimezone().date()
    )
    if window_start is None or window_end is None:
        window_start, window_end = _manual_report_window(report_type, end)
    else:
        window_start, window_end = _normalize_report_window(window_start, window_end)
    with connect() as connection:
        group = connection.execute(
            "SELECT * FROM wechat_subscription_groups WHERE id=?",
            (group_id,),
        ).fetchone()
        if not group:
            raise LookupError("公众号分组不存在")
        campus_source_slugs = [
            str(source["slug"])
            for source in load_campus_source_settings()
            if group_id in {str(value) for value in source.get("group_ids", [])}
        ]
    source_rows = _group_report_source_rows(
        group_id,
        window_start=window_start,
        window_end=window_end,
        campus_source_slugs=campus_source_slugs or None,
        include_external_imports=include_external_imports,
    )
    if not source_rows:
        raise ValueError("该分组在所选时间范围内没有可汇总的来源内容")
    return {
        "group_id": group_id,
        "group_name": str(group["name"]),
        "report_type": report_type,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "source_count": len(source_rows),
        # The confirmation dialog must stay a metadata-only operation. Full
        # text loading can trigger OCR recovery, materialization and search
        # indexing, so cache precision belongs to the streamed task stage.
        "material_check_pending": True,
        "model_chain": dict(GROUP_REPORT_MODEL_CHAIN),
        "expected_calls": {
            "summary_calls": None,
            "planner_calls": "固定 1 次；结构问题由代码局部规范化",
            "section_writer_calls": "由规划出的栏目数决定，每栏 1 次",
            "overview_calls": 1,
            "max_citation_repair_calls": 1,
            "minimum_total": None,
        },
    }


def generate_report(
    group_id: str,
    report_type: str,
    period_end: date | None = None,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    generation_trigger: str = "manual",
    include_history_context: bool = True,
    include_external_imports: bool = False,
    file_name: str | None = None,
    progress_callback: ReportProgressCallback | None = None,
) -> dict:
    if report_type not in GENERATABLE_REPORT_TYPES:
        raise ValueError("报告类型无效")
    if not settings.deepseek_api_key:
        raise ValueError("请先在设置 → 处理与 AI 中配置 DeepSeek API Key")
    ensure_database_initialized()
    tracking_task_id = f"report:{new_id()}"
    if (window_start is None) != (window_end is None):
        raise ValueError("报告时间窗口必须同时包含开始时间和结束时间")
    if report_type == "range" and (window_start is None or window_end is None):
        raise ValueError("区间汇总必须提供开始时间和结束时间")
    if window_start is not None and window_end is not None:
        window_start, window_end = _normalize_report_window(window_start, window_end)
        if window_start >= window_end:
            raise ValueError("报告时间窗口无效")
    end = period_end or (window_end.date() if window_end is not None else datetime.now().astimezone().date())
    if period_end is None and window_start is not None:
        start = window_start.date()
    else:
        start = end if report_type == "daily" else end - timedelta(days=6)
    with connect() as connection:
        group = connection.execute(
            "SELECT * FROM wechat_subscription_groups WHERE id=?",
            (group_id,),
        ).fetchone()
        if not group:
            raise LookupError("公众号分组不存在")
        _ensure_default_prompts(connection, group_id)
        # A user may have edited the Markdown file directly since the last UI
        # refresh. Import it immediately before a manual report is generated.
        sync_report_prompt_files(connection)
        prompt_rows = connection.execute(
            """SELECT id, report_type, template, template_version, updated_at
               FROM wechat_report_prompts WHERE group_id=?""",
            (group_id,),
        ).fetchall()
        system_prompt_rows = connection.execute(
            """SELECT id, task_type, version, template, updated_at
               FROM prompt_templates
               WHERE task_type IN (
                 'group_report_source_summary','group_report_section_plan',
                 'group_report_section_writer','group_report_overview',
                 'group_report_citation_repair'
               ) AND is_active=1 AND deleted_at IS NULL"""
        ).fetchall()
        connection.commit()
        prompt_by_type = {str(row["report_type"]): str(row["template"]) for row in prompt_rows}
        template = prompt_by_type.get(REPORT_PROMPT_TYPE, _default_report_prompt(REPORT_PROMPT_TYPE))
        stage_prompts = {
            prompt_type: prompt_by_type.get(prompt_type, _default_report_prompt(prompt_type))
            for prompt_type in REPORT_STAGE_TYPES
        }
        group_name = str(group["name"])
        campus_source_slugs = [
            str(source["slug"])
            for source in load_campus_source_settings()
            if group_id in {str(value) for value in source.get("group_ids", [])}
        ]
        prompt_snapshot = {
            "group_prompts": [
                {
                    "id": str(row["id"]),
                    "report_type": str(row["report_type"]),
                    "template_version": str(row["template_version"]),
                    "template_hash": sha256(str(row["template"]).encode("utf-8")).hexdigest(),
                    "updated_at": str(row["updated_at"]),
                }
                for row in prompt_rows
                if str(row["report_type"]) in REPORT_TYPES
            ],
            "system_prompts": [
                {
                    "id": str(row["id"]),
                    "task_type": str(row["task_type"]),
                    "version": str(row["version"]),
                    "template_hash": sha256(str(row["template"]).encode("utf-8")).hexdigest(),
                    "updated_at": str(row["updated_at"]),
                }
                for row in system_prompt_rows
            ],
        }

    # Daily and weekly are only time-window presets.  Every group now follows
    # the same pipeline; there is no campus-specific embedding, de-duplication
    # or history-context branch.  ``include_history_context`` remains in this
    # public function for API compatibility but is intentionally ignored.
    del include_history_context
    if window_start is None or window_end is None:
        window_start, window_end = _manual_report_window(report_type, end)
    result = _generate_common_group_report(
        group_id,
        group_name,
        report_type,
        template,
        stage_prompts=stage_prompts,
        window_start=window_start,
        window_end=window_end,
        generation_trigger=generation_trigger,
        file_name=file_name,
        title_window=(window_start, window_end) if report_type == "range" else None,
        progress_callback=progress_callback,
        tracking_task_id=tracking_task_id,
        campus_source_slugs=campus_source_slugs or None,
        include_external_imports=include_external_imports,
        prompt_snapshot=prompt_snapshot,
    )
    attach_ai_calls_to_content(tracking_task_id, str(result.get("content_item_id") or ""))
    result["ai_token_usage"] = ai_call_usage_for_task(tracking_task_id)
    _merge_report_generation_metadata(
        str(result.get("content_item_id") or ""),
        {"ai_token_usage": result["ai_token_usage"]},
    )
    return result


def _generate_common_group_report(
    group_id: str,
    group_name: str,
    report_type: str,
    template: str,
    *,
    stage_prompts: dict[str, str],
    window_start: datetime,
    window_end: datetime,
    generation_trigger: str,
    file_name: str | None,
    title_window: tuple[datetime, datetime] | None,
    progress_callback: ReportProgressCallback | None,
    tracking_task_id: str | None,
    campus_source_slugs: list[str] | None,
    include_external_imports: bool = False,
    prompt_snapshot: dict[str, object] | None = None,
) -> dict:
    sources = _load_group_report_sources(
        group_id,
        window_start,
        window_end,
        campus_source_slugs=campus_source_slugs,
        include_external_imports=include_external_imports,
        progress_callback=progress_callback,
    )
    _emit_report_progress(progress_callback, "report_sources", f"已装载 {len(sources)} 篇本期材料，正在核对摘要缓存", 18)
    generation = generate_group_report(
        sources,
        template,
        stage_guidance=stage_prompts,
        progress_callback=progress_callback,
        tracking_task_id=tracking_task_id,
        report_context=GroupReportContext(
            report_type=report_type,
            group_name=group_name,
            window_start=window_start,
            window_end=window_end,
        ),
    )
    start, end = window_start.date(), window_end.date()
    result = _persist_generated_report(
        group_id=group_id,
        group_name=group_name,
        report_type=report_type,
        start=start,
        end=end,
        window_start=window_start,
        window_end=window_end,
        source_count=len(sources),
        cited_source_count=generation.cited_source_count,
        source_coverage=generation.source_coverage,
        report_body=generation.markdown,
        generation_mode="group_section_pipeline",
        generation_trigger=generation_trigger,
        file_name=file_name,
        cover_url=_placeholder_cover_data_url(report_type, end),
        cover_status="placeholder",
        extra_stats={
            "section_count": generation.section_count,
            "summary_cache_hits": generation.summary_cache_hits,
            "classification_retries": generation.classification_retries,
            "repair_call_count": generation.repair_call_count,
        },
        generation_metadata={
            **(prompt_snapshot or {}),
            "models": dict(GROUP_REPORT_MODEL_CHAIN),
            "summary_cache_hits": generation.summary_cache_hits,
            "summary_cache_misses": len(sources) - generation.summary_cache_hits,
            "classification_retries": generation.classification_retries,
            "repair_call_count": generation.repair_call_count,
            "report_strategy": generation.report_strategy,
            "planner_diagnostics": generation.planner_diagnostics or {},
        },
        title_window=title_window,
    )
    _emit_report_progress(progress_callback, "report_save", "报告草稿、引用清单和封面占位已保存", 100, level="success")
    return result


def _load_group_report_sources(
    group_id: str,
    window_start: datetime,
    window_end: datetime,
    *,
    campus_source_slugs: list[str] | None,
    include_external_imports: bool = False,
    progress_callback: ReportProgressCallback | None = None,
) -> list[GroupReportSource]:
    rows = _group_report_source_rows(
        group_id,
        window_start=window_start,
        window_end=window_end,
        campus_source_slugs=campus_source_slugs,
        include_external_imports=include_external_imports,
    )
    if not rows:
        raise ValueError("该分组在所选时间范围内没有可汇总的来源内容")
    rows.sort(key=_group_source_sort_key)
    total = len(rows)
    _emit_report_progress(progress_callback, "report_sources", f"正在装载 {total} 篇本期材料", 2)
    sources: list[GroupReportSource] = []
    for index, row in enumerate(rows, start=1):
        sources.append(GroupReportSource(
            citation_id=f"S{index:03d}",
            content_item_id=str(row["content_item_id"]),
            title=str(row.get("title") or "未命名内容"),
            source_url=str(row.get("source_url") or ""),
            published_at=str(row.get("published_at") or ""),
            publisher=str(row.get("mp_name") or row.get("source_name") or "未知来源"),
            source_kind=str(row.get("source_provider") or "article"),
            material=_source_material(row),
        ))
        if index == total or index == 1 or index % 10 == 0:
            progress = 2 + round(14 * index / total)
            _emit_report_progress(
                progress_callback,
                "report_sources",
                f"正在装载素材与摘要缓存：{index}/{total}",
                progress,
            )
    return sources


def hydrate_legacy_report_footnotes(content_item_id: str, markdown: str) -> str:
    """Enrich legacy report footnotes from their durable source coverage.

    Reports created before canonical footnotes stored only ``publisher｜link``.
    Their coverage JSON still has the referenced content IDs, so recover the
    title, source and publication date at read time without regenerating a
    report or mutating the user's Markdown file.
    """
    source = str(markdown or "")
    if "[^S" not in source:
        return source
    initialize_database()
    with connect() as connection:
        report = connection.execute(
            "SELECT source_coverage_json FROM wechat_reports WHERE content_item_id=?",
            (content_item_id,),
        ).fetchone()
        if report is None:
            return source
        try:
            coverage = json.loads(str(report["source_coverage_json"] or "[]"))
        except json.JSONDecodeError:
            return source
        references = {
            str(entry.get("citation_id") or ""): str(entry.get("content_item_id") or "")
            for entry in coverage
            if isinstance(entry, dict) and str(entry.get("citation_id") or "") and str(entry.get("content_item_id") or "")
        }
        if not references:
            return source
        placeholders = ",".join("?" for _ in set(references.values()))
        rows = connection.execute(
            f"""SELECT c.id, c.title, c.source_url, c.published_at, c.source_provider,
                       COALESCE(NULLIF(c.source_name, ''), ws.mp_name, rss.title, '未知来源') AS publisher
                  FROM content_items c
                  LEFT JOIN wechat_subscription_items wsi ON wsi.content_item_id=c.id
                  LEFT JOIN wechat_subscriptions ws ON ws.id=wsi.subscription_id
                  LEFT JOIN rss_source_items rsi ON rsi.content_item_id=c.id
                  LEFT JOIN rss_sources rss ON rss.id=rsi.source_id
                 WHERE c.id IN ({placeholders})""",
            tuple(set(references.values())),
        ).fetchall()
    by_id = {str(row["id"]): row for row in rows}
    for citation_id, referenced_id in references.items():
        row = by_id.get(referenced_id)
        if row is None:
            continue
        footnote = _source_footnote(GroupReportSource(
            citation_id=citation_id,
            content_item_id=referenced_id,
            title=str(row["title"] or "未命名来源"),
            source_url=str(row["source_url"] or ""),
            published_at=str(row["published_at"] or ""),
            publisher=str(row["publisher"] or "未知来源"),
            source_kind=str(row["source_provider"] or ""),
            material="",
        ))
        source = re.sub(
            rf"(?m)^\[\^{re.escape(citation_id)}\]:[^\n]*$",
            footnote,
            source,
        )
    return source


def _emit_report_progress(
    callback: ReportProgressCallback | None,
    stage: str,
    message: str,
    progress: float,
    *,
    level: str = "info",
) -> None:
    if callback is None:
        return
    callback({
        "stage": stage,
        "message": message,
        "progress": max(0.0, min(100.0, float(progress))),
        "level": level,
    })


def _persist_generated_report(
    *,
    group_id: str,
    group_name: str,
    report_type: str,
    start: date,
    end: date,
    window_start: datetime | None,
    window_end: datetime | None,
    source_count: int,
    cited_source_count: int,
    source_coverage: list[dict[str, str]],
    report_body: str,
    generation_mode: str,
    generation_trigger: str,
    file_name: str | None,
    cover_url: str | None,
    cover_status: str,
    extra_stats: dict[str, object],
    generation_metadata: dict[str, object] | None = None,
    title_window: tuple[datetime, datetime] | None = None,
) -> dict:
    document_name = _report_document_name(
        file_name,
        report_type=report_type,
        start=start,
        end=end,
        group_name=group_name,
        title_window=title_window,
    )
    # The library tree is a projection of the Markdown library.  Keep its
    # title identical to the filename stem; only the on-disk short ID remains
    # hidden from the tree as a collision guard.
    title = document_name
    stats = [f"分组：{group_name}", f"分析文章：{source_count} 篇", f"正文引用：{cited_source_count} 篇"]
    if "section_count" in extra_stats:
        stats.append(f"栏目：{extra_stats['section_count']} 个")
    elif extra_stats:
        stats.extend(
            [
                f"纳入：{extra_stats.get('included_source_count', 0)} 篇",
                f"事件簇：{extra_stats.get('cluster_count', 0)} 个",
            ]
        )
    # A generated report is a first-class document, not a sidebar summary of
    # some other document.  Its report body is rendered in the center, while
    # its durable Q&A section is restored in the sidebar.
    markdown = (
        f"> {' · '.join(stats)}\n\n"
        f"{report_body.strip()}\n\n"
        "## 追问记录\n"
    )
    with connect() as connection:
        root = _ensure_report_folders(connection, report_type, group_id, group_name)
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat_report",
            content_type="report",
            canonical_source_id=f"report:{group_id}:{report_type}:{start}:{end}:{utc_now_iso()}",
            title=title,
            cover_url=cover_url,
            status="to_read",
            library_folder_id=root,
        )
        connection.commit()

    note = settings.obsidian_vault / _report_storage_label(report_type) / group_name / f"{document_name}.md"
    sync = save_markdown_draft_and_sync(
        markdown=markdown,
        title=title,
        obsidian_path=note,
        content_item_id=item.id,
        document_name=document_name,
    )
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO wechat_reports
               (id,group_id,content_item_id,report_type,period_start,period_end,
                source_count,source_coverage_json,window_start,window_end,
                generation_trigger,generation_mode,cover_status,generation_metadata_json,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_id(),
                group_id,
                item.id,
                report_type,
                start.isoformat(),
                end.isoformat(),
                source_count,
                json.dumps(source_coverage, ensure_ascii=False),
                window_start.isoformat() if window_start else None,
                window_end.isoformat() if window_end else None,
                generation_trigger,
                generation_mode,
                cover_status,
                json.dumps(generation_metadata or {}, ensure_ascii=False),
                now,
            ),
        )
        connection.commit()
    return {
        "content_item_id": item.id,
        "markdown": markdown,
        "obsidian_path": sync.obsidian_path,
        "source_count": source_count,
        "cited_source_count": cited_source_count,
        "source_coverage": source_coverage,
        "generation_mode": generation_mode,
        "generation_trigger": generation_trigger,
        "cover_status": cover_status,
        **extra_stats,
    }


def _merge_report_generation_metadata(
    content_item_id: str,
    values: dict[str, object],
) -> None:
    if not content_item_id:
        return
    with connect() as connection:
        row = connection.execute(
            "SELECT generation_metadata_json FROM wechat_reports WHERE content_item_id=?",
            (content_item_id,),
        ).fetchone()
        if row is None:
            return
        try:
            metadata = json.loads(str(row["generation_metadata_json"] or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.update(values)
        connection.execute(
            "UPDATE wechat_reports SET generation_metadata_json=? WHERE content_item_id=?",
            (json.dumps(metadata, ensure_ascii=False), content_item_id),
        )
        connection.commit()


def _report_title(
    report_type: str,
    *,
    start: date,
    end: date,
    group_name: str,
    title_window: tuple[datetime, datetime] | None = None,
) -> str:
    if report_type == "range" and title_window is not None:
        window_start, window_end = title_window
        if window_start.date() == window_end.date():
            period = (
                f"{window_start.date().isoformat()} "
                f"{window_start.strftime('%H时%M分')}至{window_end.strftime('%H时%M分')}区间汇总"
            )
        else:
            period = (
                f"{window_start.strftime('%Y-%m-%d %H时%M分')}至"
                f"{window_end.strftime('%Y-%m-%d %H时%M分')}区间汇总"
            )
        return f"{period}｜{group_name}"
    period = (
        f"{end.isoformat()}日报"
        if report_type == "daily"
        else f"{start.isoformat()}至{end.isoformat()}周报"
    )
    return f"{period}｜{group_name}"


def _report_document_name(
    requested_name: str | None,
    *,
    report_type: str,
    start: date,
    end: date,
    group_name: str,
    title_window: tuple[datetime, datetime] | None,
) -> str:
    """Return a short, user-facing file stem without its ``.md`` suffix."""
    requested = " ".join(str(requested_name or "").replace("\x00", "").split()).strip()
    if requested.lower().endswith(".md"):
        requested = requested[:-3].rstrip()
    if requested:
        return _safe_report_document_name(requested)
    if report_type == "range" and title_window is not None:
        window_start, window_end = title_window
        start_label = window_start.date().isoformat()
        end_label = (
            f"{window_end.month:02d}-{window_end.day:02d}"
            if window_start.year == window_end.year
            else window_end.date().isoformat()
        )
        period = start_label if window_start.date() == window_end.date() else f"{start_label}至{end_label}"
        return _safe_report_document_name(f"{group_name}｜{period}汇总")
    if report_type == "daily":
        return _safe_report_document_name(f"{group_name}｜{end.isoformat()}日报")
    return _safe_report_document_name(f"{group_name}｜{start.isoformat()}至{end.month:02d}-{end.day:02d}周报")


def _safe_report_document_name(value: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "").strip())
    return stem.rstrip(". ")[:96] or "报告"


def _normalize_report_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    local_timezone = datetime.now().astimezone().tzinfo

    def localize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=local_timezone)
        return value.astimezone(local_timezone)

    return localize(start), localize(end)


def _editorial_prompt_type(
    report_type: str,
    window_start: datetime | None,
    window_end: datetime | None,
) -> str:
    # Daily and weekly are only convenient time-window presets. Every group
    # uses the same editable interval-report prompt for all three entry points.
    return REPORT_PROMPT_TYPE


def _group_report_source_rows(
    group_id: str,
    *,
    window_start: datetime,
    window_end: datetime,
    campus_source_slugs: list[str] | None,
    include_external_imports: bool = False,
) -> list[dict]:
    """Collect only sources explicitly assigned to this group.

    This is the common source-adapter boundary. WeChat, campus websites and
    RSS feeds all join here through their existing group memberships, so the
    editorial pipeline remains source-neutral.
    """
    start_date = (window_start.date() - timedelta(days=1)).isoformat()
    end_date = (window_end.date() + timedelta(days=1)).isoformat()
    selected_slugs = {str(value) for value in campus_source_slugs or []}
    selected_names = tuple(
        source.name
        for source in CAMPUS_SOURCES
        if source.slug in selected_slugs and source.slug != "gwt"
    )
    include_gwt = "gwt" in selected_slugs
    with connect() as connection:
        wechat_rows = connection.execute(
            """SELECT i.id AS content_item_id, i.title, i.source_url,
                      COALESCE(w.published_at, i.published_at, i.created_at) AS published_at,
                      s.mp_name, i.source_name, i.source_section, i.source_provider,
                      sync.markdown_draft_path
               FROM wechat_subscription_items w
               JOIN wechat_subscriptions s ON s.id=w.subscription_id
               JOIN wechat_subscription_group_memberships membership ON membership.subscription_id=s.id
               JOIN content_items i ON i.id=w.content_item_id
               LEFT JOIN obsidian_sync sync ON sync.content_item_id=i.id
               WHERE membership.group_id=?
                 AND i.deleted_at IS NULL
                 AND date(COALESCE(w.published_at, i.published_at, i.created_at)) BETWEEN ? AND ?""",
            (group_id, start_date, end_date),
        ).fetchall()
        campus_rows = []
        campus_source_conditions: list[str] = []
        campus_source_params: list[str] = []
        if selected_names:
            placeholders = ",".join("?" for _ in selected_names)
            # GWT stores its publishing department in source_name. Exclude it
            # from ordinary campus-name matching so a department such as
            # "药学院" cannot leak into the college website source.
            campus_source_conditions.append(
                f"(i.source_name IN ({placeholders}) "
                "AND COALESCE(i.source_section, '') != '公文通')"
            )
            campus_source_params.extend(selected_names)
        if include_gwt:
            # source_section is the stable GWT marker already written by both
            # normal sync and snapshot import. source_name is deliberately the
            # publishing department and therefore cannot identify this source.
            campus_source_conditions.append(
                "(i.source_section='公文通' OR i.source_name='公文通')"
            )
        if campus_source_conditions:
            campus_rows = connection.execute(
                f"""SELECT i.id AS content_item_id, i.title, i.source_url,
                          COALESCE(i.published_at, i.created_at) AS published_at,
                          i.source_name AS mp_name, i.source_name, i.source_section, i.source_provider,
                          sync.markdown_draft_path
                   FROM content_items i
                   LEFT JOIN obsidian_sync sync ON sync.content_item_id=i.id
                   WHERE i.deleted_at IS NULL
                     AND i.content_type='article'
                     AND i.source_provider='campus'
                     AND ({' OR '.join(campus_source_conditions)})
                     AND date(COALESCE(i.published_at, i.created_at)) BETWEEN ? AND ?""",
                (*campus_source_params, start_date, end_date),
            ).fetchall()
        rss_rows = connection.execute(
            """SELECT i.id AS content_item_id, i.title, i.source_url,
                      COALESCE(i.published_at, i.created_at) AS published_at,
                      rss.title AS mp_name, i.source_name, i.source_section, i.source_provider,
                      sync.markdown_draft_path
               FROM rss_source_group_memberships membership
               JOIN rss_source_items rss_item ON rss_item.source_id=membership.source_id
               JOIN rss_sources rss ON rss.id=rss_item.source_id
               JOIN content_items i ON i.id=rss_item.content_item_id
               LEFT JOIN obsidian_sync sync ON sync.content_item_id=i.id
               WHERE membership.group_id=?
                 AND i.deleted_at IS NULL
                 AND i.content_type='article'
                 AND i.source_provider='rss'
                 AND date(COALESCE(i.published_at, i.created_at)) BETWEEN ? AND ?""",
            (group_id, start_date, end_date),
        ).fetchall()
        local_rows = []
        if include_external_imports:
            # External imports have no subscription membership by design. They
            # are opt-in for a single report run, and are bounded by the same
            # selected window as the group-owned sources.
            local_rows = connection.execute(
                """SELECT i.id AS content_item_id, i.title, i.source_url,
                          i.created_at AS published_at,
                          '外部导入' AS mp_name, i.source_name, i.source_section, i.source_provider,
                          sync.markdown_draft_path
                   FROM content_items i
                   LEFT JOIN obsidian_sync sync ON sync.content_item_id=i.id
                   WHERE i.deleted_at IS NULL
                     AND i.source_provider IN ('local_markdown', 'local_file')
                     AND i.content_type IN ('document', 'image')
                     AND date(i.created_at) BETWEEN ? AND ?""",
                (start_date, end_date),
            ).fetchall()
    by_id: dict[str, dict] = {}
    for raw in [*wechat_rows, *campus_rows, *rss_rows, *local_rows]:
        row = dict(raw)
        if _in_window(str(row.get("published_at") or ""), window_start, window_end):
            by_id[str(row["content_item_id"])] = row
    return list(by_id.values())


def _group_source_sort_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("published_at") or ""),
        str(row.get("source_name") or row.get("mp_name") or ""),
        str(row.get("content_item_id") or ""),
    )


def _manual_report_window(report_type: str, end: date) -> tuple[datetime, datetime]:
    timezone = datetime.now().astimezone().tzinfo
    start_date = end if report_type == "daily" else end - timedelta(days=6)
    return (
        datetime.combine(start_date, dt_time.min, tzinfo=timezone),
        datetime.combine(end, dt_time.max, tzinfo=timezone),
    )


def _in_window(value: str, start: datetime, end: datetime) -> bool:
    published = _parse_publication_time(value, timezone=start.tzinfo)
    return bool(published and start <= published <= end)


def _parse_publication_time(value: str, *, timezone) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), dt_time(hour=12), tzinfo=timezone)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone)
    except ValueError:
        return None


def _placeholder_cover_data_url(report_type: str, period_end: date) -> str:
    labels = {"daily": "日报", "weekly": "周报", "range": "区间报告"}
    label = labels.get(report_type, "区间报告")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="383" viewBox="0 0 900 383">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#2f6f63"/><stop offset="1" stop-color="#8eb6a5"/></linearGradient></defs>
<rect width="900" height="383" rx="24" fill="url(#g)"/><circle cx="760" cy="72" r="150" fill="#fff" opacity=".09"/><circle cx="830" cy="330" r="210" fill="#fff" opacity=".07"/>
<text x="72" y="174" fill="#fff" font-size="64" font-family="-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif" font-weight="700">{label}</text>
<text x="76" y="232" fill="#fff" opacity=".82" font-size="28" font-family="-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif">{period_end.isoformat()} · 封面占位</text>
</svg>"""
    return "data:image/svg+xml;charset=utf-8," + quote(svg)


def _source_material(source: dict) -> str:
    header = f"## {source['mp_name']}｜{source['title']}\n日期：{source['published_at']}\n链接：{source['source_url']}"
    content_item_id = str(source.get("content_item_id") or "").strip()
    if content_item_id:
        try:
            article = load_content_source_text(content_item_id)
        except Exception:
            article = None
        if article and article.text.strip():
            return f"{header}\n\n原文正文（含图片文字识别结果）：\n{article.text.strip()}"

    draft_path = source.get("markdown_draft_path")
    if not draft_path:
        return header
    try:
        content = Path(str(draft_path)).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return header
    if not content:
        return header
    return f"{header}\n\n原文正文：\n{_original_body_from_markdown(content)}"


def _original_body_from_markdown(markdown: str) -> str:
    marker = "<summary>原文正文</summary>"
    if marker not in markdown:
        return markdown
    body = markdown.split(marker, 1)[1]
    if "</details>" in body:
        body = body.rsplit("</details>", 1)[0]
    return body.strip() or markdown


def _ensure_report_folders(connection, report_type: str, group_id: str, group_name: str) -> str:
    root_id = ensure_managed_folder(
        connection,
        source_type="report_root",
        source_key=report_type,
        name=_report_storage_label(report_type),
        sort_order=40,
    )
    return ensure_managed_folder(
        connection,
        source_type="report_group",
        source_key=f"{report_type}:{group_id}",
        name=group_name,
        parent_folder_id=root_id,
    )


def repair_report_folder_bindings() -> int:
    """Bind existing report folders once so user renames remain durable."""
    initialize_database()
    repaired = 0
    with connect() as connection:
        rows = connection.execute(
            """SELECT report.report_type, report.group_id, item.library_folder_id,
                      folder.parent_folder_id
               FROM wechat_reports report
               JOIN content_items item ON item.id=report.content_item_id AND item.deleted_at IS NULL
               JOIN library_folders folder ON folder.id=item.library_folder_id AND folder.deleted_at IS NULL
               ORDER BY report.created_at DESC"""
        ).fetchall()
        now = utc_now_iso()
        seen: set[tuple[str, str]] = set()
        for row in rows:
            report_type, group_id = str(row["report_type"]), str(row["group_id"])
            group_key = (report_type, group_id)
            if group_key in seen:
                continue
            seen.add(group_key)
            folder_id, root_id = str(row["library_folder_id"]), str(row["parent_folder_id"] or "")
            if not root_id:
                continue
            for source_type, source_key, target_id in (
                ("report_root", report_type, root_id),
                ("report_group", f"{report_type}:{group_id}", folder_id),
            ):
                connection.execute(
                    """INSERT INTO library_source_folder_bindings (source_type, source_key, folder_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(source_type, source_key) DO UPDATE SET folder_id=excluded.folder_id, updated_at=excluded.updated_at""",
                    (source_type, source_key, target_id, now, now),
                )
                repaired += 1
        connection.commit()
    return repaired


def _report_storage_label(report_type: str) -> str:
    return {"daily": "日报", "weekly": "周报", "range": "区间汇总"}.get(report_type, "汇总")
