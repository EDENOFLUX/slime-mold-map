#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_workbench.py — 树状思维工作台生成器

把一份「认知模型 / 项目分支」规格（JSON）填进模板，产出单文件离线 HTML 工作台。
用法：
  python build_workbench.py --spec spec.json --out 输出.html
  cat spec.json | python build_workbench.py --spec - --out 输出.html

规格字段（全可选，缺省走默认）：
  title        页面标题（浏览器标签名；不渲染到界面）
  brand        兼容字段，仅作 title 兜底（不再渲染）
  subtitle     副名（收进「?」说明浮层）
  modelHtml    认知模型说明卡 HTML（可含 <b> <br> 等；注入「?」浮层）
  closureLabel 闭合度滑块标签（默认「结构性闭合度」）
  legend       [ {key:'scan'|'closed', text} , ... ]  缺省用通用两态（未闭合/已闭合）
  seed         { projects:[ {name, root:{title,note,closure,tags,trend,doc,children:[...]}, edges:[{from,to,weight}]} ] }  起始样例树；edges 为跨节点连线（端点用节点 title，weight 0-100 = 信息流/确定性）
               节点可选 trend（走向趋势）与 doc（vault 相对路径的 .md）；doc 会在构建期把全文读入 docText，
               使离线单文件也能点开「完整文档」，并从标题层级自动生成「文档导图」。
"""
import argparse, datetime, json, re, sys, os, subprocess, datetime, math, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from addr_tool import fill_addrs, audit    # Luhmann 式地址（可插拔编号）
except Exception:                              # 缺失时退化为运行时计算
    fill_addrs = None
    audit = None
TEMPLATE = os.path.join(HERE, "黏菌图谱.template.html")
DEFAULT_VAULT = os.environ.get("WB_VAULT") or r"."

DEFAULT_LEGEND = [
    {"key": "scan", "text": "未闭合（0–99%）· 模块仍在拼装"},
    {"key": "closed", "text": "已闭合（100%）· 模块咬合完成"},
    {"key": "link", "text": "加权连线 = 信息流/确定性（线宽=权重）｜ 箭头 = 父 → 子（指向子节点）"},
]

def slug(s):
    s = (s or "app").strip().lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", s)
    return s.strip("_") or "app"

def strip_frontmatter(text):
    t = text.lstrip("\ufeff")
    m = re.match(r"^---\r?\n.*?\r?\n---[ \t]*\r?\n?", t, re.S)
    if m:
        t = t[m.end():]
    return t.lstrip("\n")


def build_docs(spec, vault_root):
    """给每个节点挂上一份文档。

    - 节点带 doc（vault 相对路径）→ 读全文进 docs[key]，子节点继承同一个 key；
    - 曾祖链上都没有原文的节点 → 生成「上下文文档」（走向/说明/上级路径/子分支/闭合度）；
    - 根节点 → 生成整合总览。
    文档集中放在 spec["docs"]，节点只存 docKey（避免全文在 74 个节点里重复膨胀）。
    """
    projects = ((spec.get("seed") or {}).get("projects") or [])
    docs = {}
    stats = {"vault": 0, "auto": 0, "missing": [], "nodes": 0}

    def read_doc(rel):
        full = rel if os.path.isabs(rel) else os.path.join(vault_root, rel)
        if not os.path.isfile(full):
            return None
        with open(full, "r", encoding="utf-8-sig") as f:
            return strip_frontmatter(f.read())

    def stub(node, path):
        L = ["# " + (node.get("title") or "未命名"), "",
             "> 自动生成：该节点暂无独立 vault 原文，以下汇总它在整合地图中的上下文。", ""]
        if node.get("trend"):
            L += ["## 走向（从上级延展的方向）", "", node["trend"], ""]
        if node.get("note"):
            L += ["## 说明", "", node["note"], ""]
        if path:
            L += ["## 上级路径", "", " › ".join(path), ""]
        kids = node.get("children") or []
        if kids:
            L += ["## 子分支", ""] + ["- " + (c.get("title") or "") for c in kids] + [""]
        L += ["## 闭合度", "", "%d%%" % int(node.get("closure") or 0), ""]
        return "\n".join(L)

    def overview(node, subtitle):
        L = ["# " + (node.get("title") or "整合地图"), "", subtitle or "", "",
             "> 自动生成：整合地图总览。想看某一块的原文，点对应模块的 📄。", ""]
        for b in node.get("children") or []:
            L += ["## " + (b.get("title") or ""), ""]
            if b.get("trend"):
                L += ["*" + b["trend"] + "*", ""]
            if b.get("note"):
                L += [b["note"], ""]
            for c in b.get("children") or []:
                L.append("- " + (c.get("title") or "") + ("（" + c["note"] + "）" if c.get("note") else ""))
            L.append("")
        return "\n".join(L)

    def walk(node, owner, path):
        rel = node.get("doc")
        if rel:
            text = read_doc(rel)
            if text is None:
                stats["missing"].append("%s -> %s" % (node.get("title", "?"), rel))
            else:
                key = node.get("title") or rel
                docs[key] = {"path": rel.replace("\\", "/"), "text": text, "kind": "vault"}
                node["docKey"] = key
                owner = key
                stats["vault"] += 1
        if owner:
            node["docKey"] = owner
        for c in node.get("children") or []:
            walk(c, owner, path + [node.get("title") or ""])

    def fill(node, path):
        stats["nodes"] += 1
        if not node.get("docKey"):
            key = "auto:" + (node.get("title") or "node")
            docs[key] = {"path": "", "text": stub(node, path), "kind": "auto"}
            node["docKey"] = key
            stats["auto"] += 1
        for c in node.get("children") or []:
            fill(c, path + [node.get("title") or ""])

    for pr in projects:
        root = pr.get("root")
        if not root:
            continue
        # 根节点先占位，避免它被当成普通节点生成 stub
        root["docKey"] = None
        walk(root, None, [])
        if not root.get("docKey"):
            key = "auto:overview"
            docs[key] = {"path": "", "text": overview(root, spec.get("subtitle") or ""), "kind": "auto"}
            root["docKey"] = key
            stats["auto"] += 1
        fill(root, [])

    spec["docs"] = docs
    return stats


TYPE_CN = {"support": "支持", "contradict": "矛盾", "same": "等价", "derive": "衍生"}
STATE_CN = {"active": "活跃", "dormant": "暂搁", "archived": "归档"}
NODETYPE_CN = {"topic": "主题", "option": "选项", "dimension": "维度", "intuition": "直觉"}
VALENCE_CN = {"for": "正向", "against": "负向", "neutral": "中性"}
SIZE_CN = {"S": "小", "M": "中", "L": "大"}

# ---- 决策镜片：三个外挂框架的读数（只呈现，不打总分、不排序）----
LENS_K = 1.2                                  # 单条证据强度系数：log LR = ±K·weight/100
LENS_MED_LR = math.exp(-LENS_K * 0.5)         # 一条「中等」反证的 LR（算「还差几条翻盘」用）
VERDICT_CN = {"pass": "通过", "cut": "归零", "park": "推迟"}
COMP_CN = {"asset": "↗ 资产", "linear": "→ 线性", "drain": "↘ 消耗"}
SIGNAL_CN = {"play": "玩", "pain": "忍痛", "allin": "全押"}

# 证据分级（循证强度）：把「我的直觉」降级成一种等级，而不是唯一来源
#   L1 硬数据/研究结论 · L2 可核对的观察 · L3 个人亲历/判断 · L4 直觉/转述
# 缺 src 的连线按 L3 处理（多数连线本来就是判断），但读数里会标「未分级」
SRC_FACTOR = {1: 1.0, 2: 0.8, 3: 0.55, 4: 0.3}
SRC_CN = {1: "L1 硬数据", 2: "L2 观察", 3: "L3 亲历", 4: "L4 直觉"}


def _src_of(e):
    """读一条连线的证据等级与出处：src 可写成 {level, ref} 或直接写 1–4。"""
    s = e.get("src")
    lv, ref = None, ""
    if isinstance(s, dict):
        lv, ref = s.get("level"), (s.get("ref") or "")
    elif isinstance(s, (int, float)) and not isinstance(s, bool):
        lv = s
    if isinstance(lv, (int, float)) and not isinstance(lv, bool) and 1 <= int(lv) <= 4:
        return int(lv), ref, False
    return 3, ref, True          # 未写 src → 按亲历级，且标「未分级」


def _edge_loglr(e):
    """把一条连线读成一条证据的对数似然比：valence 定向、weight 定强度、src 定证据等级。

    没有 valence（或 neutral）的连线不算证据——它只是「有关系」，没表态支持还是反对。
    """
    v = e.get("valence")
    if v not in ("for", "against"):
        return None
    try:
        w = float(e.get("weight", 60))
    except (TypeError, ValueError):
        w = 60.0
    w = max(0.0, min(100.0, w)) * SRC_FACTOR[_src_of(e)[0]]
    return (1.0 if v == "for" else -1.0) * LENS_K * w / 100.0


def conflicts_of(L):
    """三框架互相打架的地方——不合成总分，只把冲突标出来。

    冲突不是错误，是「这里需要你再想一次」的信号；每条都要能写一句解释。
    """
    out = []
    ess, b, c = L.get("ess"), L.get("bayes"), L.get("comp")
    if ess and b:
        if ess["verdict"] == "pass" and b["posterior"] < 50:
            out.append(("A", "精要过线，但证据不支持（后验 <50）"))
        if ess["verdict"] != "pass" and b["posterior"] >= 70:
            out.append(("C", "精要否决，但证据强烈支持——可能是标准定错了"))
    if b and c:
        if b["posterior"] >= 70 and c["kind"] == "drain":
            out.append(("B", "现在成立，但长期亏损（消耗型）"))
    if ess and c:
        if ess["verdict"] == "pass" and c["kind"] == "drain":
            out.append(("D", "过了 90 线，却是消耗型"))
    return out


def lens_of(node, incident):
    """给单个节点算三镜片读数（缺字段就不出那一行，绝不补零）。"""
    out = {}

    ess = node.get("ess") or {}
    sc = ess.get("score")
    band = str(ess.get("band") or "").strip()
    if isinstance(sc, (int, float)) and not isinstance(sc, bool):
        score = max(0, min(100, int(round(sc))))
        verdict = (ess.get("verdict") or band or ("pass" if score >= 90 else "cut")).strip()
        out["ess"] = {
            "score": score,
            "verdict": verdict,
            # 覆盖 = 判词与分数不一致（<90 却要接 / ≥90 却要拒），这是真实决策，不抹掉
            "override": (verdict == "pass" and score < 90) or (verdict == "cut" and score >= 90),
            "reason": (ess.get("reason") or "").strip(),
            "hole": bool(ess.get("hole")),
        }
    elif band in ("pass", "park", "cut"):
        # 无数值形态：只写判词（pass / park / cut）+ 一句理由。画布照样能压暗，但没有伪精度。
        out["ess"] = {
            "score": None,
            "verdict": band,
            "override": False,
            "reason": (ess.get("reason") or "").strip(),
            "hole": bool(ess.get("hole")),
        }

    b = node.get("bayes") or {}
    pr = b.get("prior")
    if isinstance(pr, (int, float)) and not isinstance(pr, bool):
        prior = max(1.0, min(99.0, float(pr)))
        logs, levels, unrated = [], {}, 0
        for e in incident:
            lr = _edge_loglr(e)
            if lr is None:
                continue
            logs.append(lr)
            lv, _ref, no_src = _src_of(e)
            levels[lv] = levels.get(lv, 0) + 1
            if no_src:
                unrated += 1
        base = prior / (100.0 - prior)
        if logs:
            # 保守衰减：按 √n 而不是 n 累加证据，防朴素贝叶斯把相关证据重复计数成「必然」
            shift = (sum(logs) / len(logs)) * (len(logs) ** 0.5)
        else:
            shift = 0.0
        odds = base * math.exp(shift)
        post = 100.0 * odds / (1.0 + odds)
        # 「再几条反证翻盘」按**显示出来的整数后验**算，避免 76.6→77 却报「2 条」对不上
        pr = max(1, min(99, int(round(post))))
        po = pr / (100.0 - pr)
        flip = int(math.ceil(math.log(po) / math.log(1.0 / LENS_MED_LR))) if po > 1 else 0
        out["bayes"] = {
            "prior": int(round(prior)),
            "posterior": int(round(post)),
            "delta": int(round(post - prior)),
            "n": len(logs),
            "flip": flip,
            "levels": levels,          # {1:2, 3:4} → 证据构成
            "unrated": unrated,        # 其中几条没写 src
        }

    c = node.get("comp") or {}
    kind = (c.get("kind") or "").strip()
    if kind:
        out["comp"] = {
            "kind": kind,
            "horizon": (c.get("horizon") or "").strip(),
            "signal": [s for s in (c.get("signal") or []) if s],
            "note": (c.get("note") or "").strip(),
        }
    conf = conflicts_of(out)
    if conf:
        out["conflicts"] = [{"code": k, "text": t} for k, t in conf]
    return out


def _content_digest(n):
    """节点内容指纹：标题/说明/走向/闭合度/状态/标签/类型/尺寸/置信/兴趣。
    只比这些"人写的东西"，不比运行时字段，也不比 id/addr。"""
    parts = [
        str(n.get("title") or ""), str(n.get("note") or ""), str(n.get("trend") or ""),
        str(n.get("closure", 0)), str(n.get("state") or ""), str(n.get("tags") or ""),
        str(n.get("type") or ""), str(n.get("size") or ""),
        str(n.get("confidence", "")), str(n.get("interest", "")),
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:12]


def track_updates(spec):
    """构建期自动数「AI 交互次数」：与上次构建的交互指纹比，变了的节点 updates +1。

    交互 = 内容改动(A) + 结构移动/换父(B) + 连线增删(B) + 节点新建(B)。
    指纹 = 内容 digest + 父节点 key + 关联连线集合；任一变 = AI 碰过这个节点。
    首次构建（无 digestV2 基线）只建指纹、不计数——别假装知道历史。
    用 digestV2 而非旧 digest，避免新指纹格式把旧基线整批判成「变了」而全员误涨。
    """
    proj = ((spec.get("seed") or {}).get("projects") or [{}])[0]
    prev = spec.get("digestV2") or {}
    has_prev = bool(prev)
    cur, bumped = {}, 0

    # 节点索引：canonical key（id 优先，否则 t:标题）+ 父关系 + 标题映射
    key_of, title_key, parent_key = {}, {}, {}
    def index(n, pk=None):
        k = n.get("id") or ("t:" + str(n.get("title") or ""))
        key_of[id(n)] = k
        t = str(n.get("title") or "")
        if t not in title_key:
            title_key[t] = k
        parent_key[k] = pk
        for c in n.get("children") or []:
            index(c, k)
    if proj.get("root"):
        index(proj["root"])

    # 连线入射：每条边给两端各记一条 (kind, otherKey)
    incident = {}
    for e in proj.get("edges") or []:
        fid = e.get("fromId") or title_key.get(e.get("from"))
        tid = e.get("toId") or title_key.get(e.get("to"))
        if not fid or not tid:
            continue
        kind = e.get("kind") or "rel"
        incident.setdefault(fid, []).append((kind, tid))
        incident.setdefault(tid, []).append((kind, fid))

    def fp(n):
        k = key_of[id(n)]
        parent = parent_key.get(k)
        links = sorted(incident.get(k, []))
        raw = _content_digest(n) + "|P:" + str(parent) + "|L:" + repr(links)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    def walk(n):
        nonlocal bumped
        k = key_of[id(n)]
        d = fp(n)
        cur[k] = d
        if has_prev:
            if k not in prev:
                n["updates"] = int(n.get("updates") or 0) + 1   # 新建
                bumped += 1
            elif prev[k] != d:
                n["updates"] = int(n.get("updates") or 0) + 1   # 改动/移动/连线
                bumped += 1
        for c in n.get("children") or []:
            walk(c)

    if proj.get("root"):
        walk(proj["root"])
    spec["digestV2"] = cur
    return bumped


def _descendants(node):
    """子树里的所有节点（不含自己）。逆向/二阶读数要看下游。"""
    out = []
    for child in node.get("children") or []:
        out.append(child)
        out.extend(_descendants(child))
    return out


def _extra_lenses(root, proj):
    """第二遍读数：逆向（inversion）/ 二阶（second-order）/ 机会成本（opportunity cost）。

    这三个都只用图里已有的东西算——不新增字段、不要求用户填写：
      逆向：指向它的反对/矛盾边（= 被挑战过吗），以及下游未闭环/已暂搁的环节
      二阶：直接子节点的复利性质（资产 / 线性 / 消耗），看一阶收益后面是不是坑
      机会成本：同层 option 之间的分数差（用精要分，没有就用后验）
    全部只出读数，不排序、不打总分。
    """
    by_title = {}

    def index(node):
        by_title[node.get("title")] = node
        for child in node.get("children") or []:
            index(child)

    index(root)

    incident = {}
    for edge in proj.get("edges") or []:
        fid = edge.get("fromId") or (by_title.get(edge.get("from")) or {}).get("id")
        tid = edge.get("toId") or (by_title.get(edge.get("to")) or {}).get("id")
        if fid:
            incident.setdefault(fid, []).append(edge)
        if tid:
            incident.setdefault(tid, []).append(edge)

    options = []

    def collect(node):
        if node.get("type") == "option":
            options.append(node)
        for child in node.get("children") or []:
            collect(child)

    collect(root)

    def score_of(node):
        lens = node.get("_lens") or {}
        if lens.get("ess"):
            return float(lens["ess"]["score"]), "精要"
        if lens.get("bayes"):
            return float(lens["bayes"]["posterior"]), "后验"
        return None, None

    def walk(node):
        lens = node.get("_lens")
        if lens is None:
            lens = {}
        edges = incident.get(node.get("id"), [])
        against = [
            edge
            for edge in edges
            if edge.get("valence") == "against" or (edge.get("type") or "") in ("contradict", "tension")
        ]
        subtree = _descendants(node)
        weak = [child for child in subtree if isinstance(child.get("closure"), (int, float)) and child["closure"] < 50]
        shelved = [child for child in subtree if child.get("state") in ("dormant", "archived")]
        worst = ""
        if against:
            heaviest = max(against, key=lambda edge: float(edge.get("weight") or 0))
            worst = (heaviest.get("why") or "")[:60]

        if node.get("type") == "option" or edges or subtree:
            lens["inv"] = {
                "against": len(against),
                "weak": len(weak),
                "shelved": len(shelved),
                "worst": worst,
                "checked": bool(against),
            }

        bucket = {"asset": 0, "linear": 0, "drain": 0}
        for child in node.get("children") or []:
            kind = ((child.get("_lens") or {}).get("comp") or {}).get("kind")
            if kind in bucket:
                bucket[kind] += 1
        if any(bucket.values()):
            lens["o2"] = {
                "asset": bucket["asset"],
                "linear": bucket["linear"],
                "drain": bucket["drain"],
                "net": bucket["asset"] - bucket["drain"],
            }

        if lens:
            node["_lens"] = lens
        for child in node.get("children") or []:
            walk(child)

    walk(root)

    for option in options:
        mine, unit = score_of(option)
        best = None
        for other in options:
            if other is option:
                continue
            value, other_unit = score_of(other)
            if value is None:
                continue
            if best is None or value > best[0]:
                best = (value, other, other_unit or unit)
        lens = option.get("_lens")
        if lens is None:
            lens = {}
            option["_lens"] = lens
        lens["opp"] = {
            "alt": (best[1].get("title") or "") if best else "",
            "gap": int(round(mine - best[0])) if (best and mine is not None) else None,
            "unit": unit or (best[2] if best else "") or "",
            "options": len(options),
        }


def attach_lens(spec):
    """把三镜片读数挂到每个节点（运行时字段 _lens，写回 spec 时会被剥掉）。"""
    proj = ((spec.get("seed") or {}).get("projects") or [{}])[0]
    root = proj.get("root") or {}
    by_title = {}

    def idx(n):
        by_title[n.get("title")] = n
        for c in n.get("children") or []:
            idx(c)

    idx(root)
    incident = {}
    for e in proj.get("edges") or []:
        fid = e.get("fromId") or (by_title.get(e.get("from")) or {}).get("id")
        tid = e.get("toId") or (by_title.get(e.get("to")) or {}).get("id")
        if fid:
            incident.setdefault(fid, []).append(e)
        if tid:
            incident.setdefault(tid, []).append(e)

    count = [0, 0]      # [有读数的节点数, 分歧条数]

    def apply(n):
        got = lens_of(n, incident.get(n.get("id"), []))
        if got:
            n["_lens"] = got
            count[0] += 1
            count[1] += len(got.get("conflicts") or [])
        for c in n.get("children") or []:
            apply(c)

    apply(root)
    _extra_lenses(root, proj)
    return tuple(count)


def write_archive(spec, path, cfg, out_html=None):
    """把整张图写成一份人可读的 Markdown 存档：层级编号、结构、跨分支关系。

    只读镜像——机器真相仍是 spec JSON。
    编号用**层级地址**（1 / 1.1 / 1.2.3），直接反映节点在树里的位置；
    内部 id（n01…）是不变键，只用于连线与持久化，不显示给用户。
    """
    proj = ((spec.get("seed") or {}).get("projects") or [{}])[0]
    root = proj.get("root") or {}
    title = cfg.get("title") or "地图存档"

    nodes, by_id, parent_of, addr_of = [], {}, {}, {}
    added = [0]

    # ---- 跨图层：namespace + 所属簇 + 本图参与的接缝（对齐 projects/_relations.json）----
    slug = os.path.splitext(os.path.basename(cfg.get("_spec_path") or ""))[0]
    my_clusters, my_rels = [], []
    rel_path = os.path.join(os.path.dirname(os.path.abspath(path)), "_relations.json")
    if os.path.exists(rel_path):
        try:
            with open(rel_path, encoding="utf-8-sig") as _f:
                rj = json.load(_f)
            for _c in rj.get("clusters") or []:
                if slug in (_c.get("graphs") or []):
                    my_clusters.append(_c)
            for _r in rj.get("relations") or []:
                if _r.get("from") == slug or _r.get("to") == slug:
                    my_rels.append(_r)
        except Exception:
            pass

    def walk(n, parent_id=None, depth=0, addr="1"):
        nid = n.get("id")
        if not nid:
            nid = "n%02d" % (len(nodes) + 1)
            n["id"] = nid
            added[0] += 1
        by_id[nid] = n
        parent_of[nid] = parent_id
        addr = n.get("addr") or addr          # 以 spec 里的地址为准（插过字母的不会被重算）
        addr_of[nid] = addr
        nodes.append((nid, n, depth, parent_id, addr))
        k = 0
        for c in n.get("children") or []:
            if c.get("state") == "archived":     # 归档节点不占编号（它不在画布上）
                continue
            k += 1
            walk(c, nid, depth + 1, addr + "." + str(k))

    walk(root)

    # 关系表
    rows = []
    for e in proj.get("edges") or []:
        fid = e.get("fromId")
        tid = e.get("toId")
        if not fid or not tid:
            for nid, n, _d, _p, _a in nodes:
                if n.get("title") == e.get("from"):
                    fid = fid or nid
                if n.get("title") == e.get("to"):
                    tid = tid or nid
        if not fid or not tid:
            continue
        rows.append((fid, tid, e))

    def tag(nid):
        n = by_id.get(nid) or {}
        return "%s %s" % (addr_of.get(nid, "?"), n.get("title", "?"))

    L = []
    L.append("---")
    L.append("title: %s · 地图存档" % title)
    L.append("spec: %s" % os.path.basename(cfg.get("_spec_path") or ""))
    L.append("builtAt: %s" % (cfg.get("builtAt") or ""))
    L.append("nodes: %d" % len(nodes))
    L.append("edges: %d" % len(rows))
    L.append("generator: 黏菌图谱/build_workbench.py")
    L.append("namespace: %s" % slug)
    if my_clusters:
        L.append("clusters: %s" % " / ".join((_c.get("name") or "") for _c in my_clusters))
    L.append("---")
    L.append("")
    L.append("# %s · 地图存档" % title)
    L.append("")
    L.append("> **只读镜像**。机器真相是 spec JSON；这一页由它生成，不要手改。")
    L.append("> 线型语言：层级边=45°折线（建造，顺着展开）；跨分支边=三次贝塞尔曲线（联想，回头连上）。")
    L.append("> 要改图：改 spec（或让 AI 改），然后重跑：")
    L.append("> `python build_workbench.py --spec %s --out <html> --archive 本文件`" %
             os.path.basename(cfg.get("_spec_path") or "spec.json"))
    if out_html:
        L.append(">")
        L.append("> 快照（HTML）：`%s`" % out_html.replace("\\", "/"))
    L.append("")
    L.append("## 结构")
    L.append("")
    for nid, n, depth, _p, addr in nodes:
        mark = addr
        bits = [mark, n.get("title") or "未命名"]
        line = "%s- **%s**" % ("  " * depth, " ".join(bits))
        extra = []
        if n.get("closure") is not None:
            extra.append("%d%%" % n["closure"])
        if n.get("state") and n["state"] != "active":
            extra.append(STATE_CN.get(n["state"], n["state"]))
        if n.get("type"):
            extra.append("【%s】" % NODETYPE_CN.get(n["type"], n["type"]))
        if n.get("size") is not None and str(n.get("size")).strip():
            extra.append("尺寸:%s" % SIZE_CN.get(str(n.get("size")).upper(), str(n.get("size"))))
        if isinstance(n.get("confidence"), (int, float)):
            extra.append("置信:%d%%" % int(n["confidence"]))
        if isinstance(n.get("interest"), (int, float)):
            extra.append("兴趣:%d%%" % int(n["interest"]))
        if isinstance(n.get("hw"), (int, float)) and not isinstance(n.get("hw"), bool):
            extra.append("层级:%d" % int(n["hw"]))
        if isinstance(n.get("updates"), (int, float)) and not isinstance(n.get("updates"), bool) and n["updates"]:
            extra.append("AI碰:%d" % int(n["updates"]))
        if isinstance(n.get("aiMentions"), (int, float)) and not isinstance(n.get("aiMentions"), bool) and n["aiMentions"]:
            extra.append("提:%d" % int(n["aiMentions"]))
        if (n.get("trend") or "").strip():
            extra.append(n["trend"])
        if extra:
            line += " · " + " · ".join(extra)
        L.append(line)
    L.append("")
    if rows:
        L.append("## 关系（跨分支）")
        L.append("")
        L.append("| 从 | 类型 | 到 | 权重 | 证据 | 倾向 | 为什么连 |")
        L.append("|---|---|---|---|---|---|---|")
        any_unrated = False
        for fid, tid, e in rows:
            lv, ref, no_src = _src_of(e)
            any_unrated = any_unrated or no_src
            src_s = "L%d%s" % (lv, "*" if no_src else "")
            if ref:
                src_s += " · " + ref.replace("|", "／")[:24]
            L.append("| %s | %s | %s | %s%% | %s | %s | %s |" % (
                tag(fid),
                TYPE_CN.get(e.get("type") or "support", "支持"),
                tag(tid),
                e.get("weight", 60),
                src_s,
                VALENCE_CN.get(e.get("valence") or "", "—"),
                (e.get("why") or "（未标注）").replace("|", "／"),
            ))
        L.append("")
        if any_unrated:
            L.append("> `L*` = 该连线没写 `src`，按 **L3 亲历** 计（系数 0.55）。要提级就补 `src: {level, ref}`。")
            L.append("")

    # 跨图接缝（从关系层读取——这张图在跨图坐标系里的位置）
    if my_rels:
        L.append("## 跨图接缝")
        L.append("")
        L.append("> 这张图与哪些图「人确认过」有关系，以及将来拼大图时 merge 工具按哪个锚点定位接缝节点。完整索引见 `projects/_图谱总索引.md`。")
        L.append("")
        for _r in my_rels:
            _other = _r.get("to") if _r.get("from") == slug else _r.get("from")
            _arrow = "→" if _r.get("from") == slug else "←"
            L.append("### %s %s `%s`" % (_r.get("kind"), _arrow, _other))
            L.append("")
            L.append("- 关系类型：`%s`" % _r.get("kind"))
            L.append("- 对方图：`%s`" % _other)
            L.append("- 理由：%s" % (_r.get("why") or "").replace("|", "／"))
            if _r.get("anchors"):
                L.append("- 接缝锚点：")
                for _a in _r["anchors"]:
                    if _r.get("from") == slug:
                        L.append("  - 本图 `%s` → 对方 `%s`" % (_a.get("from"), _a.get("to")))
                    else:
                        L.append("  - 对方 `%s` → 本图 `%s`" % (_a.get("from"), _a.get("to")))
            L.append("")
    # 网络体检（卡片笔记法：孤立卡是死的，枢纽卡是入口）
    deg = {}
    for fid, tid, _e in rows:
        deg[fid] = deg.get(fid, 0) + 1
        deg[tid] = deg.get(tid, 0) + 1
    hubs = [nid for nid, _n, _d, _p, _a in nodes if deg.get(nid, 0) >= 3]
    orphans = [nid for nid, n, _d, _p, _a in nodes if deg.get(nid, 0) == 0 and n.get("state") != "archived"]
    singles = [nid for nid, n, _d, _p, _a in nodes if deg.get(nid, 0) == 1 and n.get("state") != "archived"]

    L.append("## 网络体检")
    L.append("")
    L.append("| 指标 | 数量 | 含义 |")
    L.append("|---|---|---|")
    L.append("| 枢纽卡（≥3 条连接） | %d | 别人从这些卡进入整张图 |" % len(hubs))
    L.append("| 单连卡（1 条） | %d | 只挂在一根线上，容易被遗忘 |" % len(singles))
    L.append("| 孤立卡（0 条） | %d | 还没接进网络——要么还没成形，要么该并进别的卡 |" % len(orphans))
    L.append("")
    if hubs:
        L.append("**枢纽卡**：" + "、".join("%s %s（%d）" % (addr_of[h], by_id[h].get("title", ""), deg[h]) for h in hubs))
        L.append("")
    if orphans:
        L.append("**孤立卡**：" + "、".join("%s %s" % (addr_of[o], by_id[o].get("title", "")) for o in orphans[:12]) +
                 ("…（共 %d 张）" % len(orphans) if len(orphans) > 12 else ""))
        L.append("")

    # 决策读数（三镜片：精要 / 贝叶斯 / 复利）——只呈现，不汇总排序
    lensed = [(nid, n, n.get("_lens")) for nid, n, _d, _p, _a in nodes if n.get("_lens")]
    if lensed:
        dec = proj.get("decision") or {}
        L.append("## 决策读数（三镜片）")
        L.append("")
        meta = []
        if (dec.get("std") or "").strip():
            meta.append("单一标准：**%s**" % dec["std"].strip())
        if dec.get("holesTotal"):
            meta.append("孔位：%d / %d" % (int(dec.get("holesUsed") or 0), int(dec["holesTotal"])))
        if meta:
            L.append(" ｜ ".join(meta))
            L.append("")
        L.append("| 编号 | 节点 | 精要（90 线） | 贝叶斯（先验→后验） | 复利 |")
        L.append("|---|---|---|---|---|")
        for nid, n, LZ in lensed:
            e = LZ.get("ess")
            if e:
                cell = "%d 分 · %s" % (e["score"], VERDICT_CN.get(e["verdict"], e["verdict"]))
                if e.get("override"):
                    cell += "（覆盖：%s）" % (e.get("reason") or "未写理由")
                elif e.get("reason"):
                    cell += "（%s）" % e["reason"]
            else:
                cell = "—"
            b = LZ.get("bayes")
            if b:
                bcell = "%d → %d（%+d）· 证据 %d 条" % (b["prior"], b["posterior"], b["delta"], b["n"])
                lv = b.get("levels") or {}
                if lv:
                    bcell += "（" + "/".join("L%d×%d" % (k, lv[k]) for k in sorted(lv)) + "）"
                if b.get("flip"):
                    bcell += " · 再 %d 条反证翻盘" % b["flip"]
            else:
                bcell = "—"
            c = LZ.get("comp")
            if c:
                ccell = COMP_CN.get(c["kind"], c["kind"])
                if c.get("horizon"):
                    ccell += " · " + c["horizon"]
                if c.get("signal"):
                    ccell += " · " + "/".join(SIGNAL_CN.get(s, s) for s in c["signal"])
            else:
                ccell = "—"
            L.append("| %s | %s | %s | %s | %s |" % (
                addr_of.get(nid, "?"), (n.get("title") or "").replace("|", "／"), cell, bcell, ccell))
        L.append("")
        L.append("> 读数不是总分，也不排序——它只回答「单看这个框架，这张卡是什么样」。")
        L.append("> 贝叶斯口径：`log LR = ±1.2 × (weight × 证据系数)/100`（valence 定方向；"
                 "系数按 src 等级 L1=1.0 / L2=0.8 / L3=0.55 / L4=0.3，没写 src 按 L3 并标 `*`），"
                 "按 √n 衰减累加防重复计数；「再 N 条反证翻盘」按中等强度反证（LR≈0.55）估算。")
        L.append("")

    # 分歧报警：三框架互相打架的地方（不合成总分，只把冲突标出来）
    clashes = []
    for nid, n, _d, _p, _a in nodes:
        for c in ((n.get("_lens") or {}).get("conflicts") or []):
            clashes.append((nid, n, c))
    if clashes:
        L.append("## 分歧报警（框架互相打架的地方）")
        L.append("")
        L.append("| 编号 | 节点 | 型 | 冲突 |")
        L.append("|---|---|---|---|")
        CODE_CN = {"A": "标准 vs 证据", "B": "短期 vs 长期", "C": "标准可疑", "D": "过线 vs 消耗"}
        for nid, n, c in clashes:
            L.append("| %s | %s | %s | %s |" % (
                addr_of.get(nid, "?"), (n.get("title") or "").replace("|", "／"),
                CODE_CN.get(c["code"], c["code"]), c["text"]))
        L.append("")
        L.append("> 冲突不是错误，是「这里还没想清」。每条都该能写一句解释——写不出来，说明这条判断现在还不能用。")
        L.append("")

    # 结构笔记（卡片笔记法·Hub 策展）：把带 summary 的节点列成可读叙事
    summ = [(nid, n) for nid, n, _d, _p, _a in nodes if (n.get("summary") or "").strip()]
    if summ:
        L.append("## 结构笔记（AI 策展枢纽）")
        L.append("")
        L.append("> 这些节点是跨分支连接的「策展者」——下面一段是 AI 把它们那簇同构/派生关系讲成的叙事，不是节点的原始说明。")
        L.append("")
        for nid, n in summ:
            L.append("### %s %s" % (addr_of.get(nid, "?"), (n.get("title") or "?").replace("|", "／")))
            L.append("")
            L.append((n.get("summary") or "").strip().replace("|", "／"))
            L.append("")

    hist = (spec.get("history") or [])[-6:]
    if hist:
        L.append("## 轨迹（最近几次构建）")
        L.append("")
        L.append("| 时间 | 节点 | 关系 | 枢纽 | 单连 | 孤立 |")
        L.append("|---|---|---|---|---|---|")
        for h in hist:
            L.append("| %s | %d | %d | %d | %d | %d |" % (
                (h.get("builtAt") or "")[5:16], h.get("nodes", 0), h.get("edges", 0),
                h.get("hubs", 0), h.get("singles", 0), h.get("orphans", 0)))
        L.append("")

    L.append("## 节点表")
    L.append("")
    L.append("| 编号 | 标题 | 类型 | 尺寸 | 置信 | 兴趣 | 父 | 状态 | 成形 | 连线 | 文档 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for nid, n, _d, pid, addr in nodes:
        pn = by_id.get(pid) if pid else None
        conf = n.get("confidence")
        conf_s = ("%d%%" % int(conf)) if isinstance(conf, (int, float)) else "—"
        intr = n.get("interest")
        intr_s = ("%d%%" % int(intr)) if isinstance(intr, (int, float)) else "—"
        size_s = SIZE_CN.get(str(n.get("size") or "").upper(), (n.get("size") or "—"))
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s%% | %d | %s |" % (
            addr,
            (n.get("title") or "").replace("|", "／"),
            NODETYPE_CN.get(n.get("type") or "", "—"),
            size_s,
            conf_s,
            intr_s,
            ("%s %s" % (addr_of.get(pid, ""), pn.get("title", ""))) if pn else "—",
            STATE_CN.get(n.get("state") or "active", "活跃"),
            n.get("closure", 0),
            deg.get(nid, 0),
            (n.get("doc") or "（自动上下文）").replace("|", "／"),
        ))
    L.append("")

    out_dir = os.path.dirname(os.path.abspath(path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    return len(nodes), len(rows), added[0]


RUNTIME_KEYS = ("docKey", "num", "_links", "_x", "_y", "_side", "_w", "_h")


def strip_runtime(spec):
    """写回 spec 前剥掉运行时字段：docKey 是 CONFIG.docs 的下标，落库会让下次构建读不到文档"""
    def walk(n):
        if not isinstance(n, dict):
            return
        for k in list(n.keys()):
            if k in RUNTIME_KEYS or k.startswith("_"):
                n.pop(k, None)
        for c in n.get("children") or []:
            walk(c)

    for pr in (spec.get("seed") or {}).get("projects") or []:
        walk(pr.get("root"))


def dump_spec(spec, path):
    strip_runtime(spec)
    with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)


def net_stats(spec):
    """节点 / 关系 / 枢纽 / 单连 / 孤立 —— 与存档页「网络体检」同一口径"""
    proj = ((spec.get("seed") or {}).get("projects") or [{}])[0]
    nodes, deg = [], {}

    def walk(n):
        if n.get("state") != "archived":
            nodes.append(n)
        for c in n.get("children") or []:
            walk(c)

    if proj.get("root"):
        walk(proj["root"])
    for e in proj.get("edges") or []:
        fid, tid = e.get("fromId"), e.get("toId")
        if not fid or not tid:
            for n in nodes:
                if n.get("title") == e.get("from"):
                    fid = fid or n.get("id")
                if n.get("title") == e.get("to"):
                    tid = tid or n.get("id")
        if fid and tid:
            deg[fid] = deg.get(fid, 0) + 1
            deg[tid] = deg.get(tid, 0) + 1
    hubs = sum(1 for n in nodes if deg.get(n.get("id"), 0) >= 3)
    singles = sum(1 for n in nodes if deg.get(n.get("id"), 0) == 1)
    orphans = sum(1 for n in nodes if deg.get(n.get("id"), 0) == 0)
    return {"nodes": len(nodes), "edges": len(proj.get("edges") or []),
            "hubs": hubs, "singles": singles, "orphans": orphans}


def log_net(spec, stats):
    """把这次体检写进 spec.history（上限 50 条），并打印与上次的差异"""
    hist = spec.setdefault("history", [])
    prev = hist[-1] if hist else None
    entry = dict(stats, builtAt=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    hist.append(entry)
    del hist[:-50]

    line = "[NET] 节点 %d · 关系 %d · 枢纽 %d · 单连 %d · 孤立 %d" % (
        stats["nodes"], stats["edges"], stats["hubs"], stats["singles"], stats["orphans"])
    if prev:
        parts = []
        for k, label in (("nodes", "节点"), ("edges", "关系"), ("hubs", "枢纽"),
                         ("singles", "单连"), ("orphans", "孤立")):
            dv = stats[k] - prev.get(k, 0)
            if dv:
                parts.append("%s %+d" % (label, dv))
        line += "（较上次：" + ("、".join(parts) if parts else "无变化") + "）"
    else:
        line += "（首次记录）"
    print(line)
    return entry


def build_config(spec):
    title = spec.get("title") or spec.get("brand") or "树状思维工作台"
    edges = ((spec.get("seed") or {}).get("projects") or [{}])[0].get("edges") or []
    for e in edges:
        if not str(e.get("why") or "").strip():
            print("[WARN] 连线缺 why（不会被画出来）：%s -> %s" % (e.get("from"), e.get("to")), file=sys.stderr)

    cfg = {
        "id": slug(spec.get("id") or title),
        # 版本戳：本地存档与它不一致时，页面顶部提示「有新版本」
        "builtAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "title": title,
        "brand": spec.get("brand") or title,
        "subtitle": spec.get("subtitle") or "",
        "modelHtml": spec.get("modelHtml") or spec.get("model_html") or "",
        "closureLabel": spec.get("closureLabel") or spec.get("closure_label") or "结构性闭合度",
        "layout": spec.get("layout") or "web",
        "legend": spec.get("legend") or DEFAULT_LEGEND,
        "seed": spec.get("seed") or None,
        "docs": spec.get("docs") or {},
    }
    return cfg

def fill(template, cfg):
    # 安全：防止 modelHtml 内的 </script> 截断脚本
    js = json.dumps(cfg, ensure_ascii=False)
    js = js.replace("</", "<\\/")
    marker = "/*__CONFIG__*/ null"
    assert marker in template, "模板缺少 CONFIG 注入点"
    return template.replace(marker, js, 1)

def validate_js(html):
    m = re.search(r"<script>([\s\S]*?)</script>", html)
    if not m:
        return False, "无 <script>"
    js = m.group(1)
    node = r"./node\22.22.2\node.exe"
    if not os.path.exists(node):
        node = "node"
    try:
        p = subprocess.run([node, "-e", "new Function(require('fs').readFileSync(0,'utf8'))"],
                           input=js.encode("utf-8"), capture_output=True, timeout=30)
        if p.returncode != 0:
            return False, p.stderr.decode("utf-8", "replace")[:500]
        return True, ""
    except FileNotFoundError:
        return None, "node 不可用，跳过语法校验"
    except Exception as e:
        return False, str(e)

def main():
    ap = argparse.ArgumentParser(description="生成树状思维工作台 HTML")
    ap.add_argument("--spec", required=True, help="规格 JSON 文件，或 '-' 读 stdin")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument("--archive", default=None,
                    help="另存一份 Markdown 地图存档（编号/结构/关系表），一般放在 spec 同目录")
    ap.add_argument("--vault", default=DEFAULT_VAULT,
                    help="vault 根目录，doc 相对路径以此为基准（默认 %s）" % DEFAULT_VAULT)
    args = ap.parse_args()

    if args.spec == "-":
        spec = json.load(sys.stdin)
    else:
        with open(args.spec, "r", encoding="utf-8-sig") as f:
            spec = json.load(f)

    doc_stats = build_docs(spec, args.vault)

    with open(TEMPLATE, "r", encoding="utf-8") as f:
        template = f.read()

    addr_added = 0
    if fill_addrs:
        addr_added = fill_addrs(spec)
        print("[ADDR] 补了 %d 个层级地址并写回 spec" % addr_added)
    if audit:
        bad = audit(spec)
        for kind, addr, detail in bad:
            print("[ADDR][%s] %s · %s" % (kind, addr, detail), file=sys.stderr)
        if bad:
            print("[ADDR] 地址有 %d 处问题：编号会显示错乱，先跑 `addr_tool.py --check` 修" % len(bad),
                  file=sys.stderr)

    bumped = track_updates(spec)
    if bumped:
        print("[TRACE] 本构建检测到 %d 个节点内容有更新（计入脉络频率）" % bumped)

    lens_n, conflict_n = attach_lens(spec)
    cfg = build_config(spec)
    cfg["_spec_path"] = args.spec
    out = fill(template, cfg)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out)

    net_entry = log_net(spec, net_stats(spec))

    print("[DOC] 节点 %d 个 · vault 原文 %d 份 · 自动上下文 %d 份"
          % (doc_stats["nodes"], doc_stats["vault"], doc_stats["auto"]))
    if lens_n:
        print("[LENS] 决策读数 %d 个节点（精要 / 贝叶斯 / 复利）" % lens_n)
        if conflict_n:
            print("[LENS] 分歧 %d 处——框架互相打架的地方，见存档「分歧报警」" % conflict_n)
    for m in doc_stats["missing"]:
        print("[WARN] 文档缺失：%s" % m, file=sys.stderr)

    ok, msg = validate_js(out)
    if ok is True:
        print("[OK] 已生成 %s (config.id=%s, 校验通过)" % (args.out, cfg["id"]))
        if args.archive:
            n, m, added = write_archive(spec, args.archive, cfg, args.out)
            print("[MAP] 地图存档 %s（%d 节点 · %d 条关系）" % (args.archive, n, m))
            if added:
                print("[ID] 已把 %d 个新编号写回 spec（编号从此固定）" % added)
    if args.spec not in ("-", ""):
        dump_spec(spec, args.spec)      # 统一写回：剥运行时字段 + 记 history
    elif ok is False:
        print("[FAIL] JS 校验未通过：%s" % msg, file=sys.stderr)
        sys.exit(1)
    else:
        print("[WARN] %s → %s (config.id=%s)" % (ok, msg, cfg["id"]))

if __name__ == "__main__":
    main()
