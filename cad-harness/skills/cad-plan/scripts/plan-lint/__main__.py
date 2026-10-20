#!/usr/bin/env python3
"""plan-lint —— 对 $cad-plan 产出的 plan.md 做机械校验。

只检查「可用字符串模式判定」的项，不理解语义：
  章节完备性 / 骨架 ID 悬空与未引用 / 定位基准列是否填 ID / 类型数与预算区间 /
  自查结论行行数是否等于实际行数 / 数量列模糊词 / 来源标记缺失 /
  实例性列缺失 / 装配顺序基准件与 inspect 命令 / 制造工艺混入第 8 章 /
  公差是否对齐 harness 阈值 / 第 3 章参数格式。

语义正确性（拆得够不够深、参数自不自洽）仍需 agent 自行负责——
本脚本的作用是让「打勾式自检」失效，而不是替代判断。

用法:
    $CAD_PYTHON <cad-plan>/scripts/plan-lint plan.md
    $CAD_PYTHON <cad-plan>/scripts/plan-lint plan.md --format json
    $CAD_PYTHON <cad-plan>/scripts/plan-lint plan.md --strict   # warning 也阻断

退出码: 0 = 无 error;  1 = 有 error(或 --strict 下有 warning);  2 = 用法错误
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --------------------------------------------------------------------------
# 常量：与 SKILL.md / CLAUDE_cad.md 保持一致
# --------------------------------------------------------------------------

REQUIRED_CHAPTERS = {
    0: "范围与规模预算",
    1: "总体构型与技术指标",
    2: "骨架与基准体系",
    3: "全局参数驱动表",
    4: "零件明细表",
    5: "系统布线",
    6: "自由度与耦合",
    7: "限位与过载保护",
    8: "CAD 装配顺序",
    9: "关键配合公差",
}

# LOD 档位 -> (下限, 上限 or None)
LOD_TIERS = {
    "L1": (20, 50),
    "L2": (50, 300),
    "L3": (150, None),
}

# 骨架 ID 前缀
ID_PREFIXES = ("CSYS", "PLN", "AX", "STA")
ID_TOKEN = re.compile(r"\b((?:CSYS|PLN|AX|STA)_[A-Za-z0-9_]*[A-Za-z0-9](?:\.\.\d+)?)")

# 数量列里的「无确定几何」措辞
VAGUE_QTY = ("套", "若干", "多个", "数个", "一批", "适量", "按需", "n/a", "待定", "tbd")
VAGUE_QTY_RE = re.compile(r"^\s*[~约≈]|^\s*\d+\s*套|若干|多个|数个|一批|适量|按需|待定|TBD", re.I)

# 集合名词（出现在零件名称末尾时视为未拆解）
COLLECTIVE_TAIL = (
    "发动机", "涡轮泵", "泵", "电机", "马达", "减速器", "阀组", "控制器",
    "线束", "管路", "电气系统", "液压系统", "冷却系统",
)
GROUP_SUFFIX = ("组", "总成", "系统", "装置", "机构", "单元", "模块")

# 制造工艺词（不得进第 8 章）
PROCESS_WORDS = (
    "焊", "热处理", "探伤", "无损检测", "X 射线", "X射线", "超声", "气密",
    "试压", "点火", "机加工", "喷砂", "阳极氧化", "电镀", "退火", "时效",
    "惰化", "加注", "试运转", "空载", "跑合", "涂装", "清洗", "装订",
)

# 来源标记
SOURCE_TAG_RE = re.compile(r"\[(用户给定|标准件推导|标准件[^\]]*|典型值|派生|推导[^\]]*|基准|公开|⚠️假设-待确认|⚠️假设[^\]]*)\]")

# harness 校验阈值 (mm)
HARNESS_THRESHOLDS = {"face": 0.01, "axis": 0.01, "hole": 0.05}

SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str   # error | warning | info
    code: str
    line: int
    message: str

    def render(self) -> str:
        mark = {"error": "✗", "warning": "!", "info": "·"}[self.severity]
        loc = f"L{self.line}" if self.line else "—"
        return f"  {mark} [{self.code}] {loc}: {self.message}"


@dataclass
class Table:
    """一块连续的 Markdown 表格。"""
    chapter: int | None
    heading: str
    header: list[str]
    rows: list[tuple[int, list[str]]] = field(default_factory=list)  # (行号, 单元格)
    start_line: int = 0
    ignored: bool = False   # 被 <!-- plan-lint: ignore --> 或 ❌反例 标记

    def col(self, *names: str) -> int | None:
        """按关键词模糊定位列下标。"""
        for i, h in enumerate(self.header):
            for n in names:
                if n in h:
                    return i
        return None

    def cell(self, row: list[str], idx: int | None) -> str:
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------

SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
CHAPTER_RE = re.compile(r"^#{1,3}\s+(\d{1,2})[\.\s、]")

# 教学/反例表格标记 —— template 里演示「错误写法」的表不该被当成真数据校验。
# 显式指令优先；自动识别只认「❌ / 反例 / 不要这样写」这类不可能出现在真数据表上方的措辞，
# 其余示意表（✅拆到位、浅层写法对照…）必须写显式指令，避免误放过真表。
IGNORE_DIRECTIVE = re.compile(r"<!--\s*plan-lint:\s*ignore\s*-->")
ILLUSTRATIVE_CUE = re.compile(r"❌|反例|不要这样写")


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def parse(text: str) -> tuple[list[Table], dict[int, int], dict[str, str], list[str]]:
    """返回 (表格列表, {章号: 行号}, {章号->章节正文}, 全部行)。"""
    lines = text.splitlines()
    tables: list[Table] = []
    chapters: dict[int, int] = {}
    chapter_text: dict[str, list[str]] = {}

    cur_ch: int | None = None
    cur_heading = ""
    i = 0
    while i < len(lines):
        line = lines[i]

        m = HEADING_RE.match(line)
        if m:
            cur_heading = m.group(2).strip()
            cm = CHAPTER_RE.match(line)
            if cm:
                ch = int(cm.group(1))
                # 只认第一次出现（避免正文里的引用覆盖）
                chapters.setdefault(ch, i + 1)
                cur_ch = ch
            i += 1
            continue

        if cur_ch is not None:
            chapter_text.setdefault(str(cur_ch), []).append(line)

        # 表格块：header 行 + 分隔行 + 数据行
        if line.lstrip().startswith("|") and i + 1 < len(lines) and SEP_RE.match(lines[i + 1]):
            header = split_row(line)
            # 往上看 3 行找忽略指令 / 反例线索
            lookback = "\n".join(lines[max(0, i - 3):i])
            ignored = bool(IGNORE_DIRECTIVE.search(lookback)
                           or ILLUSTRATIVE_CUE.search(lookback))
            tbl = Table(chapter=cur_ch, heading=cur_heading, header=header,
                        start_line=i + 1, ignored=ignored)
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                cells = split_row(lines[j])
                if not SEP_RE.match(lines[j]):
                    tbl.rows.append((j + 1, cells))
                j += 1
            tables.append(tbl)
            # 表格内容也要进章节正文 —— 「停止点1」「LOD」等常写在表格里
            if cur_ch is not None:
                chapter_text.setdefault(str(cur_ch), []).extend(lines[i:j])
            i = j
            continue

        i += 1

    joined = {k: "\n".join(v) for k, v in chapter_text.items()}
    return tables, chapters, joined, lines


def expand_ids(token: str) -> set[str]:
    """兼容三种写法，返回「这个 token 指代哪些 ID」的**候选并集**。

    `AX_ENG_0..8`   → 区间：AX_ENG_0 … AX_ENG_8
    `STA_3480..39500` → 跨段：两端点 STA_3480 / STA_39500（站位号不是序号，不展开）
    `AX_FIN_*`      → 通配：交给 resolve_ref 用前缀匹配

    区间与跨段无法从字面区分，故两种解释都返回，由 resolve_ref 择一判定。
    """
    m = re.match(r"^(.*?)(\d+)\.\.(\d+)$", token)
    if not m:
        return {token}
    prefix, lo_s, hi_s = m.group(1), m.group(2), m.group(3)
    lo, hi = int(lo_s), int(hi_s)
    out = {f"{prefix}{lo_s}", f"{prefix}{hi_s}"}          # 跨段解释
    if lo <= hi and hi - lo <= 64 and len(lo_s) <= 2:      # 区间解释（仅小序号）
        out |= {f"{prefix}{n}" for n in range(lo, hi + 1)}
    return out


def ids_in(text: str) -> set[str]:
    """抓出文本里所有骨架 ID token（保留原始写法，不展开）。

    `AX_ENG_*` 的通配写法会让正则只吃到 `AX_ENG`，那不是真 ID——
    这里把「紧跟 `_*` / `*`」的残片剔掉，交给 resolve_ref 的通配分支处理。
    """
    out: set[str] = set()
    for m in ID_TOKEN.finditer(text):
        tail = text[m.end():m.end() + 2]
        if tail.startswith("_*") or tail.startswith("*"):
            continue
        out.add(m.group(1))
    return out


def wildcard_prefixes(text: str) -> set[str]:
    """`AX_ENG_*` → {'AX_ENG_'}；用于把通配引用解析成具体 ID 集合。"""
    return {m.group(1) for m in
            re.finditer(r"\b((?:CSYS|PLN|AX|STA)_[A-Za-z0-9_]*?_)\*", text)}


def has_wildcard(text: str, token: str) -> bool:
    """`AX_FIN_*` / `AX_TP_*` 这类通配写法。"""
    return f"{token}_*" in text or f"{token}*" in text


def resolve_ref(text: str, defined: set[str]) -> tuple[set[str], set[str]]:
    """把一段文本里的 ID 引用解析成 (命中的已定义 ID, 悬空 ID)。

    判定顺序：通配前缀 → 跨段两端点 → 区间全展开 → 单个 ID。
    任一解释能在 `defined` 里全部落地即视为合法。
    """
    hit: set[str] = set()
    dangling: set[str] = set()

    # 通配：`CSYS_ENG_LOCAL` / `AX_ENG_*` → 所有该前缀下的已定义 ID
    for pref in wildcard_prefixes(text):
        matched = {d for d in defined if d.startswith(pref)}
        if matched:
            hit |= matched
        else:
            dangling.add(pref + "*")

    for token in ids_in(text):
        if token in defined:
            hit.add(token)
            continue

        m = re.match(r"^(.*?)(\d+)\.\.(\d+)$", token)
        if m:
            prefix, lo_s, hi_s = m.group(1), m.group(2), m.group(3)
            span = {f"{prefix}{lo_s}", f"{prefix}{hi_s}"}
            if span <= defined:                     # 跨段解释成立
                hit |= span
                continue
            rng = expand_ids(token) - span
            if rng and rng <= defined:              # 区间解释成立
                hit |= rng
                continue
            dangling |= span - defined
            continue

        dangling.add(token)
    return hit, dangling


# --------------------------------------------------------------------------
# 检查项
# --------------------------------------------------------------------------

def check_chapters(chapters: dict[int, int], partial: bool, F: list[Finding]) -> None:
    sev = "info" if partial else "error"
    for ch, name in REQUIRED_CHAPTERS.items():
        if ch not in chapters:
            F.append(Finding(sev, "CH-MISSING", 0, f"缺第 {ch} 章「{name}」"))


def detect_lod(text: str) -> str | None:
    m = re.search(r"\bL([123])\b\s*(外观级|功能级|工程级)?", text)
    return f"L{m.group(1)}" if m else None


def parse_budget(ch0_text: str) -> tuple[int | None, int | None]:
    """从第 0 章抓「20–35 类」「≥50，≤300」这类预算区间。"""
    m = re.search(r"(\d+)\s*[–\-~至]\s*(\d+)\s*类", ch0_text)
    if m:
        return int(m.group(1)), int(m.group(2))
    lo = re.search(r"[≥>]=?\s*(\d+)\s*类", ch0_text)
    hi = re.search(r"[≤<]=?\s*(\d+)\s*类", ch0_text)
    return (int(lo.group(1)) if lo else None, int(hi.group(1)) if hi else None)


def part_tables(tables: list[Table]) -> list[Table]:
    """第 4 章里带「零件名称」列的表 = 零件明细表。"""
    out = []
    for t in tables:
        if t.chapter != 4:
            continue
        if t.ignored:
            continue
        if t.col("零件名称", "名称") is None:
            continue
        if t.col("数量") is None:
            continue
        out.append(t)
    return out


def check_parts(tables: list[Table], chapters: dict[int, int],
                ch_text: dict[str, str], skeleton_ids: set[str],
                F: list[Finding]) -> tuple[int, set[str]]:
    """校验第 4 章。返回 (实际类型数, 被引用的骨架 ID)。"""
    ptabs = part_tables(tables)
    if not ptabs:
        F.append(Finding("error", "PARTS-NONE", chapters.get(4, 0),
                         "第 4 章找不到零件明细表（需含「零件名称」与「数量」列）"))
        return 0, set()

    # 先收全部零件名 —— CLAUDE_cad.md 允许「对齐到已装零件的具体面/轴」，
    # 所以定位基准引用另一个零件是合法的，只是不如引用骨架稳。
    part_names: set[str] = set()
    for t in ptabs:
        c = t.col("零件名称", "名称")
        for _ln, row in t.rows:
            nm = t.cell(row, c)
            if nm and not nm.startswith("…"):
                part_names.add(re.sub(r"[（(].*?[)）]|\s*[×x]\s*\d+|[#＃]\d+", "", nm).strip())
    part_names.discard("")

    referenced: set[str] = set()
    n_types = 0
    seen_numbers: list[tuple[int, int]] = []

    for t in ptabs:
        c_name = t.col("零件名称", "名称")
        c_qty = t.col("数量")
        c_inst = t.col("实例性")
        c_datum = t.col("定位基准", "基准")
        c_src = t.col("来源")
        c_lod = t.col("LOD")
        c_num = t.col("#", "序号")

        if c_inst is None:
            F.append(Finding("error", "PARTS-NO-INSTANCE", t.start_line,
                             "零件表缺「实例性」列——无法判断该建 1 个源还是 N 个源"))
        if c_datum is None:
            F.append(Finding("error", "PARTS-NO-DATUM", t.start_line,
                             "零件表缺「定位基准」列——阶段 3 无法取定位来源"))
        if c_src is None:
            F.append(Finding("error", "PARTS-NO-SOURCE", t.start_line,
                             "零件表缺「来源」列——无法区分自建模 / import / 占位"))
        if c_lod is None:
            F.append(Finding("warning", "PARTS-NO-LOD", t.start_line, "零件表缺「LOD」列"))

        for ln, row in t.rows:
            name = t.cell(row, c_name)
            if not name or name.startswith("…") or name in {"——", "—", "..."}:
                continue
            n_types += 1

            num = t.cell(row, c_num)
            # 「14a / 14b」是把原第 14 行拆开后的子号，占用同一个序号槽位。
            # 只记 1 次，否则「14 被 14a/14b 取代」会误报成缺号 14。
            m_num = re.match(r"^(\d+)([a-z])?$", num)
            if m_num:
                n = int(m_num.group(1))
                if not m_num.group(2) or n not in {x for x, _ in seen_numbers}:
                    seen_numbers.append((n, ln))

            # --- 数量列模糊词 ---
            qty = t.cell(row, c_qty)
            if VAGUE_QTY_RE.search(qty) or any(v in qty for v in ("若干", "多个", "数个", "一批")):
                F.append(Finding("error", "QTY-VAGUE", ln,
                                 f"「{name}」数量写作「{qty}」——无确定几何，"
                                 f"须拆成具体件给出整数，或移出零件表"))

            # --- 定位基准：优先骨架 ID，其次已装零件的具体面/轴 ---
            datum = t.cell(row, c_datum)
            if c_datum is not None:
                hit, dangling = resolve_ref(datum, skeleton_ids)
                referenced |= hit
                if dangling and skeleton_ids:
                    F.append(Finding("error", "DATUM-DANGLING", ln,
                                     f"「{name}」引用了第 2 章未定义的 ID: "
                                     f"{', '.join(sorted(dangling)[:4])}"))
                elif not hit:
                    # 无 ID —— 是否引用了另一个零件的面/轴？
                    refs_part = any(p and p in datum for p in part_names if len(p) >= 2)
                    sev = "warning" if refs_part else "error"
                    tail = ("引用零件而非骨架——改那个零件会连锁影响本件，"
                            "建议在第 2 章补一个局部基准"
                            if refs_part else
                            "须填第 2 章 ID（CSYS_*/PLN_*/AX_*/STA_*），"
                            "或引用已装零件的具体面/轴")
                    F.append(Finding(sev, "DATUM-NOT-ID", ln,
                                     f"「{name}」定位基准写作「{datum or '空'}」——{tail}"))

            # --- 实例性 vs 数量 ---
            inst = t.cell(row, c_inst)
            qn = re.match(r"^\s*(\d+)", qty)
            if qn and int(qn.group(1)) > 1 and "独立件" in inst:
                F.append(Finding("warning", "INST-SUSPECT", ln,
                                 f"「{name}」数量 {qn.group(1)} 却标「独立件」——"
                                 f"同参数重复件应标「1 源 + N 实例」"))

            # --- 集合名词 / 总成后缀 ---
            bare = re.sub(r"[（(].*?[)）]", "", name).strip()
            bare = re.sub(r"\s*[×x]\s*\d+$", "", bare).strip()
            for w in COLLECTIVE_TAIL:
                if bare.endswith(w) and len(bare) <= len(w) + 6:
                    F.append(Finding("error", "TOY-COLLECTIVE", ln,
                                     f"「{name}」是集合名词——一个词代表整个子系统，"
                                     f"须拆成壳体/转子/轴/轴承/密封/接口法兰等"))
                    break
            else:
                for s in GROUP_SUFFIX:
                    if bare.endswith(s):
                        prefix = bare[: -len(s)]
                        has_child = any(
                            prefix and prefix in t2.cell(r2, t2.col("零件名称", "名称") or 0)
                            and r2ln != ln
                            for t2 in ptabs for r2ln, r2 in t2.rows
                        )
                        if not has_child:
                            F.append(Finding("warning", "TOY-GROUP", ln,
                                             f"「{name}」带「{s}」后缀但无下级零件——"
                                             f"总成必然可拆"))
                        break

    # --- 序号连续性 ---
    if len(seen_numbers) >= 3:
        nums = [n for n, _ in seen_numbers]
        expect = list(range(min(nums), min(nums) + len(nums)))
        if nums != expect:
            missing = sorted(set(expect) - set(nums))
            dup = sorted({n for n in nums if nums.count(n) > 1})
            msg = []
            if missing:
                msg.append(f"缺号 {missing[:8]}")
            if dup:
                msg.append(f"重号 {dup[:8]}")
            if msg:
                F.append(Finding("warning", "PARTS-NUMBERING", ptabs[0].start_line,
                                 "零件表序号不连续：" + "；".join(msg)))

    return n_types, referenced


def check_selfcheck_line(ch4_text: str, n_types: int, chapters: dict[int, int],
                         F: list[Finding]) -> None:
    """自查结论行：必须写「扫描 N 行」，且 N == 实际类型数；必须写命中行号或明确 0。"""
    m = re.search(r"扫描\s*(\d+)\s*行", ch4_text)
    if not m:
        F.append(Finding("error", "SELFCHECK-MISSING", chapters.get(4, 0),
                         "第 4 章末尾缺 toy 架构自查结论行"
                         "（格式：扫描 N 行，命中 M 行（第 X/Y/Z 行），已拆解为 K 个子零件）"))
        return
    claimed = int(m.group(1))
    if n_types and claimed != n_types:
        F.append(Finding("error", "SELFCHECK-COUNT", chapters.get(4, 0),
                         f"自查结论声称扫描 {claimed} 行，但零件表实际 {n_types} 行"
                         f"——未逐行扫描"))
    hit = re.search(r"命中\s*(\d+)\s*行", ch4_text)
    if not hit:
        F.append(Finding("error", "SELFCHECK-NOHIT", chapters.get(4, 0),
                         "自查结论未写「命中 M 行」"))
    elif int(hit.group(1)) > 0 and not re.search(r"第\s*[\d/、,，\s]+\s*行", ch4_text):
        F.append(Finding("error", "SELFCHECK-NOLINES", chapters.get(4, 0),
                         f"自查结论称命中 {hit.group(1)} 行却未列出具体行号"))


def check_skeleton(tables: list[Table], chapters: dict[int, int],
                   ch_text: dict[str, str], F: list[Finding]) -> set[str]:
    """校验第 2 章，返回已定义的骨架 ID 全集（含区间展开）。"""
    defined: set[str] = set()
    has_ref_col = False
    ch2 = ch_text.get("2", "")

    def register(raw: str) -> bool:
        nonlocal defined
        got = ids_in(raw)
        if not got:
            return False
        for tok in got:
            defined.add(tok)
            defined |= expand_ids(tok)   # AX_ENG_1..8 → 展开每个实例
        return True

    for t in tables:
        if t.chapter != 2:
            continue
        if t.ignored:
            continue
        c_id = t.col("ID", "子骨架")
        if t.col("被引用", "引用零件") is not None:
            has_ref_col = True
        for ln, row in t.rows:
            raw = t.cell(row, c_id) if c_id is not None else (row[0] if row else "")
            if register(raw):
                continue
            if raw and c_id is not None and not raw.startswith("…"):
                F.append(Finding("warning", "SKEL-BAD-ID", ln,
                                 f"第 2 章条目「{raw}」不符合 ID 规范"
                                 f"（CSYS_*/PLN_*/AX_*/STA_*）"))
    register(ch2)   # 代码块里的 CSYS 定义也算

    if not defined:
        F.append(Finding("error", "SKEL-EMPTY", chapters.get(2, 0),
                         "第 2 章没有任何合规骨架 ID——阶段 3 只能拍绝对坐标"))
    if not any(d.startswith("CSYS_") for d in defined):
        F.append(Finding("error", "SKEL-NO-CSYS", chapters.get(2, 0),
                         "第 2 章缺全局 CSYS（须写原点物理位置 + 三轴指向）"))
    if not has_ref_col:
        F.append(Finding("warning", "SKEL-NO-REFCOL", chapters.get(2, 0),
                         "第 2 章骨架表缺「被引用零件」列——"
                         "改骨架 ID 时无法反查影响面（见 SKILL.md「修订」）"))
    return defined


def check_params(tables: list[Table], chapters: dict[int, int], F: list[Finding]) -> None:
    found = False
    for t in tables:
        if t.chapter != 3:
            continue
        if t.ignored:
            continue
        c_n = t.col("参数名")
        if c_n is None:
            continue
        found = True
        c_u = t.col("单位")
        c_s = t.col("来源")
        c_r = t.col("被引用")
        c_v = t.col("值")
        if c_u is None:
            F.append(Finding("error", "PARAM-NO-UNIT", t.start_line, "第 3 章缺「单位」列"))
        if c_s is None:
            F.append(Finding("error", "PARAM-NO-SOURCE", t.start_line, "第 3 章缺「来源」列"))
        if c_r is None:
            F.append(Finding("error", "PARAM-NO-REFCOL", t.start_line,
                             "第 3 章缺「被引用于」列——改参数时无法反查受影响零件"))
        for ln, row in t.rows:
            name = t.cell(row, c_n).strip("`*_ ")
            if not name or name.startswith("…"):
                continue
            if not SNAKE_CASE_RE.match(name):
                F.append(Finding("error", "PARAM-NOT-SNAKE", ln,
                                 f"参数名「{name}」不是 snake_case"))
            if c_r is not None and not t.cell(row, c_r):
                F.append(Finding("error", "PARAM-NO-REF", ln,
                                 f"参数「{name}」未写被引用零件"))
            src = t.cell(row, c_s) if c_s is not None else ""
            if c_s is not None and not SOURCE_TAG_RE.search(src):
                F.append(Finding("error", "PARAM-NO-TAG", ln,
                                 f"参数「{name}」来源列「{src or '空'}」缺来源标记"))
            # 派生参数须写公式
            if "派生" in src or "推导" in src:
                val = t.cell(row, c_v) if c_v is not None else ""
                if "=" not in val and not re.search(r"[+\-*/·×]", val):
                    F.append(Finding("warning", "PARAM-NO-FORMULA", ln,
                                     f"派生参数「{name}」只写了结果没写公式——改上游不会联动"))
    if not found:
        F.append(Finding("error", "PARAM-TABLE-NONE", chapters.get(3, 0),
                         "第 3 章找不到参数表（需含「参数名」列）"))


def check_dof(tables: list[Table], chapters: dict[int, int],
              skeleton_ids: set[str], F: list[Finding]) -> None:
    JOINTS = ("revolute", "prismatic", "spherical", "cylindrical", "fixed", "gimbal", "planar")
    found = False
    for t in tables:
        if t.chapter != 6:
            continue
        if t.ignored:
            continue
        c_j = t.col("joint")
        if c_j is None:
            continue
        found = True
        c_ax = t.col("轴线")
        c_d = t.col("驱动")
        c_r = t.col("范围")
        for ln, row in t.rows:
            j = t.cell(row, c_j).lower()
            if not j or j.startswith("…"):
                continue
            if not any(k in j for k in JOINTS):
                F.append(Finding("error", "DOF-BAD-JOINT", ln,
                                 f"joint 类型「{j}」不在 "
                                 f"revolute/prismatic/spherical/cylindrical/fixed 之内"))
            ax = t.cell(row, c_ax) if c_ax is not None else ""
            if "fixed" not in j:
                hit, dangling = resolve_ref(ax, skeleton_ids)
                if dangling and skeleton_ids:
                    F.append(Finding("error", "DOF-DANGLING-AXIS", ln,
                                     f"轴线 {', '.join(sorted(dangling)[:3])} 未在第 2 章定义"))
                elif not hit:
                    # 锁销/缓冲这类局部轴允许挂在子骨架上，但必须点名子骨架
                    if re.search(r"CSYS_\w+_LOCAL|子骨架", ax):
                        F.append(Finding("warning", "DOF-LOCAL-AXIS", ln,
                                         f"活动副（{j}）轴线「{ax}」只到子骨架级——"
                                         f"在第 2 章子骨架里给该轴一个 ID"))
                    else:
                        F.append(Finding("error", "DOF-NO-AXIS", ln,
                                         f"活动副（{j}）轴线「{ax or '空'}」不是 ID——"
                                         f"阶段 3 落不成约束"))
                if c_r is not None and not t.cell(row, c_r):
                    F.append(Finding("error", "DOF-NO-RANGE", ln, f"活动副（{j}）未给范围"))
                if c_d is not None and not t.cell(row, c_d):
                    F.append(Finding("error", "DOF-NO-DRIVER", ln, f"活动副（{j}）未给驱动源"))
    if not found:
        F.append(Finding("warning", "DOF-TABLE-NONE", chapters.get(6, 0),
                         "第 6 章找不到自由度表（需含「joint 类型」列）；"
                         "全静态对象请显式写明「无活动自由度」"))


def check_assembly(tables: list[Table], chapters: dict[int, int],
                   ch_text: dict[str, str], skeleton_ids: set[str],
                   F: list[Finding]) -> None:
    found = False
    for t in tables:
        if t.chapter != 8:
            continue
        if t.ignored:
            continue
        c_step = t.col("步骤")
        c_add = t.col("加入")
        if c_step is None or c_add is None:
            continue
        found = True
        c_to = t.col("对齐到")
        c_chk = t.col("校验")
        c_thr = t.col("阈值")
        if c_chk is None:
            F.append(Finding("error", "ASM-NO-CHECK-COL", t.start_line,
                             "装配顺序表缺「校验命令」列"))
        if c_thr is None:
            F.append(Finding("error", "ASM-NO-THRESHOLD-COL", t.start_line,
                             "装配顺序表缺「阈值」列"))

        for idx, (ln, row) in enumerate(t.rows):
            add = t.cell(row, c_add)
            if not add or add.startswith("…"):
                continue
            to = t.cell(row, c_to) if c_to is not None else ""
            chk = t.cell(row, c_chk) if c_chk is not None else ""

            if idx == 0:
                _h, _d = resolve_ref(to, skeleton_ids)
                if not any(x.startswith("CSYS_") for x in ids_in(to)):
                    F.append(Finding("error", "ASM-STEP1-NOT-BASE", ln,
                                     f"第 1 步「{add}」未直接约束到全局 CSYS——"
                                     f"基准件必须挂全局坐标系"))
            if c_chk is not None and not chk:
                F.append(Finding("error", "ASM-NO-INSPECT", ln,
                                 f"步骤「{add}」缺校验命令"))
            elif c_chk is not None and "inspect" not in chk and "—" not in chk:
                F.append(Finding("warning", "ASM-NO-INSPECT", ln,
                                 f"步骤「{add}」校验列未给 inspect 命令"))
            _hit, dangling = resolve_ref(to, skeleton_ids)
            if dangling and skeleton_ids:
                F.append(Finding("error", "ASM-DANGLING", ln,
                                 f"步骤「{add}」对齐到未定义 ID: "
                                 f"{', '.join(sorted(dangling)[:3])}"))

    if not found:
        F.append(Finding("error", "ASM-TABLE-NONE", chapters.get(8, 0),
                         "第 8 章找不到装配顺序表（需含「步骤」与「加入零件」列）"))

    # 制造工艺混入
    ch8 = ch_text.get("8", "")
    for raw_line in ch8.splitlines():
        # 反例区、附录引用不算
        if raw_line.lstrip().startswith(("- ❌", "> ❌", "❌")) or "反例" in raw_line:
            continue
        if not raw_line.lstrip().startswith("|"):
            continue
        for w in PROCESS_WORDS:
            if w in raw_line:
                F.append(Finding("error", "ASM-PROCESS", 0,
                                 f"第 8 章出现制造工艺「{w}」——不产生 CAD 几何，"
                                 f"移到「附录：制造工艺参考」：{raw_line.strip()[:60]}"))
                break


def check_tolerance(tables: list[Table], chapters: dict[int, int],
                    lod: str | None, F: list[Finding]) -> None:
    found = False
    n_items = 0
    for t in tables:
        if t.chapter != 9:
            continue
        if t.ignored:
            continue
        c_p = t.col("配合部位", "部位")
        if c_p is None:
            continue
        found = True
        c_i = t.col("inspect", "校验")
        c_t = t.col("阈值")
        c_s = t.col("来源")
        if c_i is None:
            F.append(Finding("error", "TOL-NO-INSPECT-COL", t.start_line,
                             "第 9 章缺「inspect 校验项」列——写了但验不了的公差等于没写"))
        if c_t is None:
            F.append(Finding("error", "TOL-NO-THRESHOLD-COL", t.start_line,
                             "第 9 章缺「阈值」列"))
        for ln, row in t.rows:
            part = t.cell(row, c_p)
            if not part or part.startswith("…"):
                continue
            n_items += 1
            thr = t.cell(row, c_t) if c_t is not None else ""
            chk = (t.cell(row, c_i) if c_i is not None else "").lower()
            if c_i is not None and not chk:
                F.append(Finding("error", "TOL-NO-INSPECT", ln,
                                 f"「{part}」未映射到 inspect 校验项"))
            m = re.search(r"[≤<]=?\s*([\d.]+)", thr)
            if m:
                v = float(m.group(1))
                kind = ("face" if ("面" in chk or "face" in chk)
                        else "hole" if ("孔" in chk or "hole" in chk)
                        else "axis")
                limit = HARNESS_THRESHOLDS[kind]
                if v < limit and "理由" not in row and not re.search(r"因|为了|需|理由", " ".join(row)):
                    F.append(Finding("warning", "TOL-STRICTER", ln,
                                     f"「{part}」阈值 {v} 严于 harness 的 {limit}——"
                                     f"须写明理由，否则下游无法验收"))
            if c_s is not None and not SOURCE_TAG_RE.search(t.cell(row, c_s)):
                F.append(Finding("warning", "TOL-NO-TAG", ln, f"「{part}」缺来源标记"))

    if not found:
        if lod == "L1":
            F.append(Finding("info", "TOL-SKIP", chapters.get(9, 0), "L1 免公差表"))
        else:
            F.append(Finding("error", "TOL-TABLE-NONE", chapters.get(9, 0),
                             "第 9 章找不到公差表（需含「配合部位」列）"))
    elif lod == "L2" and n_items > 15:
        F.append(Finding("warning", "TOL-TOO-MANY", chapters.get(9, 0),
                         f"L2 档公差表 {n_items} 项，超过 15 项上限"))


def check_source_tags(tables: list[Table], F: list[Finding]) -> None:
    """任何带「来源」列的表，数据行都必须填来源标记。"""
    for t in tables:
        if t.chapter not in (1, 2, 4) or t.ignored:
            continue
        c_s = t.col("来源")
        if c_s is None:
            continue
        # 第 4 章的「来源」是 自建模/import/占位，不是数据出处
        if t.chapter == 4:
            for ln, row in t.rows:
                v = t.cell(row, c_s)
                if not v or v.startswith("…"):
                    continue
                if not re.search(r"自建模|import|占位|复用|镜像", v, re.I):
                    F.append(Finding("warning", "SRC-BAD", ln,
                                     f"来源「{v}」应为 自建模 / import:<path> / 占位"))
            continue
        for ln, row in t.rows:
            v = t.cell(row, c_s)
            first = row[0] if row else ""
            if not first or first.startswith("…") or not v:
                if first and not first.startswith("…") and not v:
                    F.append(Finding("error", "SRC-MISSING", ln,
                                     f"「{first}」缺来源标记"))
                continue
            if not SOURCE_TAG_RE.search(v):
                F.append(Finding("error", "SRC-MISSING", ln,
                                 f"「{first}」来源「{v}」不是合规标记"
                                 f"（[用户给定]/[标准件推导]/[典型值]/[⚠️假设-待确认]）"))


def check_budget(ch0_text: str, lod: str | None, n_types: int,
                 chapters: dict[int, int], F: list[Finding]) -> None:
    ln0 = chapters.get(0, 0)
    if lod is None:
        F.append(Finding("error", "LOD-MISSING", ln0, "第 0 章未声明 LOD 等级"))
        return
    lo_decl, hi_decl = parse_budget(ch0_text)
    if lo_decl is None and hi_decl is None:
        F.append(Finding("error", "BUDGET-MISSING", ln0,
                         "第 0 章未写类型数预算区间（下限与上限都要写）"))
    tier_lo, tier_hi = LOD_TIERS[lod]

    if not n_types:
        return

    # 与声明区间比
    if lo_decl is not None and n_types < lo_decl:
        F.append(Finding("error", "BUDGET-UNDER-DECL", ln0,
                         f"实际 {n_types} 类低于第 0 章自己声明的下限 {lo_decl}"))
    if hi_decl is not None and n_types > hi_decl:
        F.append(Finding("warning", "BUDGET-OVER-DECL", ln0,
                         f"实际 {n_types} 类超过声明上限 {hi_decl}——"
                         f"须在第 0 章写归并/降级取舍"))

    # 与 LOD 档位比
    exempt = bool(re.search(r"下限豁免|豁免声明", ch0_text))
    if n_types < tier_lo:
        if exempt:
            missing = [w for w in ("集合名词", "1 套", "≥2 个功能",
                                   "总成", "可动机构", "数量级")
                       if w not in ch0_text]
            if missing:
                F.append(Finding("error", "EXEMPT-INCOMPLETE", ln0,
                                 f"下限豁免声明未逐条回应 6 个危险信号，"
                                 f"缺：{', '.join(missing)}"))
            else:
                F.append(Finding("info", "BUDGET-EXEMPT", ln0,
                                 f"{n_types} 类低于 {lod} 下限 {tier_lo}，"
                                 f"已提供下限豁免声明"))
        else:
            F.append(Finding("error", "BUDGET-UNDER-TIER", ln0,
                             f"实际 {n_types} 类低于 {lod} 下限 {tier_lo}——"
                             f"按第 4 章 toy 自查表逐行再拆一层，"
                             f"或在第 0 章写「下限豁免声明」（逐条回应 6 个危险信号）"))
    if tier_hi and n_types > tier_hi:
        F.append(Finding("warning", "BUDGET-OVER-TIER", ln0,
                         f"实际 {n_types} 类超过 {lod} 上限 {tier_hi}"))


def check_stop_points(ch0_text: str, chapters: dict[int, int], F: list[Finding]) -> None:
    for i in (1, 2, 3):
        if not re.search(rf"停止点\s*{i}", ch0_text):
            F.append(Finding("error", "STOP-MISSING", chapters.get(0, 0),
                             f"第 0 章缺停止点{i}"))
    if "拆解深度" not in ch0_text and "拆到几层" not in ch0_text:
        F.append(Finding("warning", "DEPTH-TABLE-MISSING", chapters.get(0, 0),
                         "第 0 章缺子系统拆解深度表——防拆浅的主要手段"))


def check_unused_skeleton(defined: set[str], referenced: set[str],
                          text: str, chapters: dict[int, int], F: list[Finding]) -> None:
    """只查「字面写了但全文没人引用」的骨架 ID。

    区间展开出来的虚拟 ID（AX_ENG_3）不算——它们只出现在 `AX_ENG_0..8` 里。
    """
    literal = ids_in(text)
    for sid in sorted(defined & literal):
        occurrences = len(re.findall(re.escape(sid) + r"(?![A-Za-z0-9_])", text))
        if occurrences <= 1 and sid not in referenced:
            F.append(Finding("warning", "SKEL-UNUSED", 0,
                             f"骨架 ID `{sid}` 全文只出现 1 次（仅定义未被引用）——"
                             f"删掉或补上引用它的零件"))


def check_revision(text: str, F: list[Finding]) -> None:
    if not re.search(r"修订记录|修订历史", text):
        F.append(Finding("warning", "NO-REVISION", 0,
                         "plan.md 顶部缺「修订记录」表——"
                         "阶段 1–4 回流改动无法追溯（见 SKILL.md「修订」）"))


def check_disclaimer(text: str, F: list[Finding]) -> None:
    n_assume = len(re.findall(r"⚠️假设", text))
    if n_assume >= 5 and not re.search(r"免责|不代表任何真实产品|推测", text):
        F.append(Finding("warning", "NO-DISCLAIMER", 0,
                         f"有 {n_assume} 处 [⚠️假设-待确认] 却无数据免责声明——"
                         f"复刻真实产品时第 0 章须加"))


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def lint(path: Path, partial: bool = False) -> tuple[list[Finding], dict]:
    text = path.read_text(encoding="utf-8")
    tables, chapters, ch_text, _lines = parse(text)
    F: list[Finding] = []

    check_chapters(chapters, partial, F)

    ch0 = ch_text.get("0", "")
    lod = detect_lod(ch0) or detect_lod(text[:4000])

    skeleton_ids = check_skeleton(tables, chapters, ch_text, F)
    n_types, referenced = check_parts(tables, chapters, ch_text, skeleton_ids, F)

    check_selfcheck_line(ch_text.get("4", ""), n_types, chapters, F)
    check_budget(ch0, lod, n_types, chapters, F)
    check_stop_points(ch0, chapters, F)
    check_params(tables, chapters, F)
    check_dof(tables, chapters, skeleton_ids, F)
    check_assembly(tables, chapters, ch_text, skeleton_ids, F)
    check_tolerance(tables, chapters, lod, F)
    check_source_tags(tables, F)
    check_unused_skeleton(skeleton_ids, referenced, text, chapters, F)
    check_revision(text, F)
    check_disclaimer(text, F)

    if partial:
        # 节选模式：缺章导致的连带缺表降为 info，只留「已写部分写得对不对」
        absent = {c for c in REQUIRED_CHAPTERS if c not in chapters}
        gated = {0: ("BUDGET-MISSING", "STOP-MISSING", "DEPTH-TABLE-MISSING",
                     "LOD-MISSING", "BUDGET-UNDER-TIER", "BUDGET-UNDER-DECL"),
                 3: ("PARAM-TABLE-NONE",), 4: ("PARTS-NONE", "SELFCHECK-MISSING",
                     "SELFCHECK-NOHIT", "SELFCHECK-NOLINES"),
                 6: ("DOF-TABLE-NONE",), 8: ("ASM-TABLE-NONE",),
                 9: ("TOL-TABLE-NONE",)}
        soften = {code for ch, codes in gated.items() if ch in absent for code in codes}
        soften |= {"NO-REVISION"}
        for f in F:
            if f.code in soften:
                f.severity = "info"

    stats = {
        "file": str(path),
        "partial": partial,
        "lod": lod,
        "part_types": n_types,
        "skeleton_ids": len(skeleton_ids),
        "chapters_found": sorted(chapters),
        "tables": len(tables),
        "errors": sum(1 for f in F if f.severity == "error"),
        "warnings": sum(1 for f in F if f.severity == "warning"),
    }
    return F, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="plan-lint",
        description="机械校验 $cad-plan 产出的 plan.md（章节/骨架 ID/类型数/自查留痕/公差阈值）",
    )
    ap.add_argument("plan", nargs="+", help="plan.md 路径")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--strict", action="store_true", help="warning 也视为失败")
    ap.add_argument("--partial", action="store_true",
                    help="节选模式：不要求 11 章齐全（用于校验 reference 样板）")
    args = ap.parse_args(argv)

    all_out = []
    worst = 0
    for p in args.plan:
        path = Path(p)
        if not path.is_file():
            print(f"plan-lint: 找不到文件 {p}", file=sys.stderr)
            return 2
        F, stats = lint(path, partial=args.partial)
        all_out.append({"stats": stats, "findings": [asdict(f) for f in F]})

        if args.format == "text":
            order = {"error": 0, "warning": 1, "info": 2}
            F.sort(key=lambda f: (order[f.severity], f.line))
            print(f"\n=== {path} ===")
            print(f"LOD={stats['lod'] or '未声明'}  零件类型数={stats['part_types']}  "
                  f"骨架 ID={stats['skeleton_ids']}  表格={stats['tables']}")
            missing = [c for c in REQUIRED_CHAPTERS if c not in stats["chapters_found"]]
            if missing:
                print(f"缺失章节: {missing}")
            if not F:
                print("  ✓ 全部检查通过")
            else:
                for f in F:
                    print(f.render())
            print(f"\n  → {stats['errors']} error, {stats['warnings']} warning")

        fail = stats["errors"] > 0 or (args.strict and stats["warnings"] > 0)
        worst = max(worst, 1 if fail else 0)

    if args.format == "json":
        print(json.dumps(all_out if len(all_out) > 1 else all_out[0],
                         ensure_ascii=False, indent=2))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
