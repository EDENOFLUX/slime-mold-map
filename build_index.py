# -*- coding: utf-8 -*-
"""图谱总索引生成器 —— 扫描 projects/*.json，产出 _图谱总索引.md / .json。

设计要点
- 每张图有一个 namespace（= spec 文件名 slug），拼接时节点 id 变成 `<ns>/<id>`，避免 n01 撞车。
- 关系分两类：
    **已声明**：集合级元数据，集中在 `projects/_relations.json`（锚点=本图节点标题→对方节点标题，
               供未来 merge 工具定位接缝），是人确认的断言。
    **候选**：脚本按标题词面重叠自动算出的线索，只列出来、不写入事实。
- 候选关系永不被当成事实：共享的只是字面，是否同一件事要人确认。

用法：
    python build_index.py                 # 生成 projects/_图谱总索引.{md,json}
    python build_index.py --check         # 只报统计，不写文件
"""
import argparse, json, io, os, re, glob, datetime

PROJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects")
ROOT = os.path.dirname(os.path.abspath(__file__))

# 通用词：出现在任何图里都不算「共享主题」
STOP_TITLE = {"后续", "其他", "待定", "备注", "总计", "小结", "问题", "目标", "现状"}

REL_KIND = {
    "shares": "共享主题",
    "feeds": "输出即输入",
    "derived": "由它拆出",
    "contradicts": "结论冲突",
    "same-as": "同一件事的两个视角",
}


def load(p):
    with io.open(p, encoding="utf-8-sig") as f:
        return json.load(f)


def walk(n, out):
    out.append(n)
    for c in n.get("children") or []:
        walk(c, out)


def norm(s):
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", s or "")


def bigrams(s):
    s = norm(s)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def overlap(a, b):
    A, B = bigrams(a), bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / min(len(A), len(B))


def collect(path):
    d = load(path)
    slug = os.path.splitext(os.path.basename(path))[0]
    projects = (d.get("seed") or {}).get("projects") or []
    nodes, edges = [], []
    for p in projects:
        root = p.get("root")
        if root:
            walk(root, nodes)
        edges.extend(p.get("edges") or [])
    titles = [(n.get("title") or "").strip() for n in nodes if (n.get("title") or "").strip()]
    tags = set()
    for n in nodes:
        for t in re.split(r"[,，\s]+", (n.get("tags") or "")):
            t = t.strip()
            if t:
                tags.add(t)
    return {
        "slug": slug,
        "namespace": slug,
        "id": d.get("id") or slug,
        "title": d.get("title") or slug,
        "root": (titles[0] if titles else ""),
        "nodes": len(nodes),
        "edges": len(edges),
        "titles": titles,
        "tags": sorted(tags),
        "spec": os.path.basename(path),
        "archive": os.path.join("projects", slug + "·地图存档.md").replace("\\", "/"),
        "layout": d.get("layout") or "web",
    }


def candidates(graphs):
    """两两比对标题：重叠度 >= 0.62 且标题长度 >= 4 的节点对，作为「可能的接缝」。"""
    out = []
    for i in range(len(graphs)):
        for j in range(i + 1, len(graphs)):
            a, b = graphs[i], graphs[j]
            pairs = []
            for ta in set(a["titles"]):
                if len(norm(ta)) < 4 or norm(ta) in STOP_TITLE:
                    continue
                for tb in set(b["titles"]):
                    if len(norm(tb)) < 4 or norm(tb) in STOP_TITLE:
                        continue
                    ov = overlap(ta, tb)
                    if ov >= 0.62:
                        pairs.append((round(ov, 2), ta, tb))
            if pairs:
                pairs.sort(reverse=True)
                # 同一概念只留最像的一条，上限 6 条，避免噪声
                seen, keep = set(), []
                for ov, ta, tb in pairs:
                    key = norm(ta)[:6]
                    if key in seen:
                        continue
                    seen.add(key)
                    keep.append({"score": ov, "a": ta, "b": tb})
                    if len(keep) >= 6:
                        break
                out.append({"a": a["slug"], "b": b["slug"], "anchors": keep})
    return out


def load_relations(path, graphs):
    """从集合级 _relations.json 读已声明关系；spec 顶层不再存 relations（避免污染/重复）。"""
    known = {g["slug"] for g in graphs}
    if not os.path.exists(path):
        return [], []
    data = json.load(io.open(path, encoding="utf-8-sig"))
    clusters = data.get("clusters") or []
    rels = []
    for r in data.get("relations") or []:
        frm = (r.get("from") or "").strip()
        to = (r.get("to") or "").strip()
        dangling = (frm not in known) or (to not in known)
        anchors = r.get("anchors") or []
        # 兼容两种锚点写法：对象 {"from","to"} 或 字符串对 [a,b]
        norm_anchors = []
        for a in anchors:
            if isinstance(a, dict):
                norm_anchors.append({"from": a.get("from", ""), "to": a.get("to", "")})
            elif isinstance(a, (list, tuple)) and len(a) == 2:
                norm_anchors.append({"from": a[0], "to": a[1]})
            else:
                norm_anchors.append({"from": str(a), "to": ""})
        rels.append({"from": frm, "to": to, "kind": r.get("kind") or "shares",
                     "why": r.get("why") or "", "anchors": norm_anchors,
                     "dangling": dangling})
    return clusters, rels


def render_md(graphs, cands, clusters, rels, now):
    L = []
    L.append("---")
    L.append("title: 图谱总索引")
    L.append("generatedAt: %s" % now)
    L.append("graphs: %d" % len(graphs))
    L.append("generator: 黏菌图谱/build_index.py")
    L.append("---")
    L.append("")
    L.append("# 图谱总索引")
    L.append("")
    L.append("> **自动生成，别手改。** 重建：`python build_index.py`（跨图关系改 `projects/_relations.json`）。")
    L.append("> 这一页回答三件事：有哪些图、它们之间什么关系、将来怎么拼成一张大的。")
    L.append("")
    L.append("## 一览")
    L.append("")
    L.append("| 图谱 | 命名空间 | 节点 | 跨分支 | 根 | 布局 | 存档 |")
    L.append("|---|---|---|---|---|---|---|")
    for g in sorted(graphs, key=lambda x: -x["nodes"]):
        L.append("| %s | `%s/` | %d | %d | %s | %s | [%s](%s) |" % (
            g["title"], g["namespace"], g["nodes"], g["edges"],
            (g["root"] or "—").replace("|", "／"), g["layout"],
            g["slug"], g["archive"]))
    L.append("")

    L.append("## 关系")
    L.append("")
    L.append("### 簇（建议一起拼的图）")
    L.append("")
    if clusters:
        for c in clusters:
            gs = "、".join("`%s`" % x for x in c.get("graphs", []))
            L.append("- **%s**：%s —— %s" % (c.get("name", ""), gs, c.get("why", "")))
    else:
        L.append("还没定义簇。在 `projects/_relations.json` 的 `clusters` 里加。")
    L.append("")

    L.append("### 已声明（人确认过的）")
    L.append("")
    if rels:
        L.append("| 从 | 类型 | 到 | 理由 | 接缝锚点（本图 → 对方图） |")
        L.append("|---|---|---|---|---|")
        for r in rels:
            kind = REL_KIND.get(r["kind"], r["kind"])
            flag = " ⚠️ 目标不存在" if r["dangling"] else ""
            if r["anchors"]:
                anc = "；".join("%s → %s" % (a["from"], a["to"]) for a in r["anchors"])
            else:
                anc = "—"
            L.append("| `%s` | %s | `%s`%s | %s | %s |" % (
                r["from"], kind, r["to"], flag, (r["why"] or "—").replace("|", "／"), anc.replace("|", "／")))
    else:
        L.append("还没有声明任何跨图关系。加到 `projects/_relations.json` 的 `relations`：")
        L.append("")
        L.append("```json")
        L.append('{"from":"<本图 slug>","to":"<对方 slug>","kind":"shares",')
        L.append(' "why":"为什么这两张图有关",')
        L.append(' "anchors":[{"from":"本图节点标题","to":"对方节点标题"}]}')
        L.append("```")
    L.append("")

    L.append("### 候选接缝（词面重叠，**未确认**）")
    L.append("")
    if cands:
        L.append("> 只是字面像，不是「同一件事」。确认后写进 `_relations.json`，才会出现在上面那张表。")
        L.append("")
        L.append("| 图谱 A | 图谱 B | 可能共享的概念 | 重叠 |")
        L.append("|---|---|---|---|")
        for c in cands:
            for a in c["anchors"][:4]:
                L.append("| `%s` | `%s` | %s ⇄ %s | %.2f |" % (
                    c["a"], c["b"],
                    a["a"].replace("|", "／")[:26], a["b"].replace("|", "／")[:26], a["score"]))
    else:
        L.append("当前没有「未被声明的词面重叠」——所有字面像的图对都已在上面『已声明』。")
        L.append("新增图谱后出现新的字面重叠，会自动列在这里等你确认。")
    L.append("")

    L.append("## 拼接协议（将来合并成大图时按这个来）")
    L.append("")
    L.append("1. **命名空间**：合并时每个节点 id 变成 `<命名空间>/<原 id>`，例如 `career_planning/n07`。")
    L.append("   现在各图的 id 都是 `n01…`，不加前缀必然撞车。")
    L.append("2. **接缝**：只合并「已声明」关系里 `anchors` 指向的两个节点；候选接缝要先确认。")
    L.append("3. **跨图的边**：合并后原图的 `edges` 保留；图与图之间的新边要写进合并后的 spec，")
    L.append("   `from/to` 用带命名空间的 id，并照旧填 `why`（没有理由不画）。")
    L.append("4. **根**：不做「单根统领」，保留多簇（`seed.projects` 是多项目结构，本来就是为此留的）。")
    L.append("5. **可回溯**：合并产物仍是 spec，原图 spec 不动；索引里记下「合并自哪些 namespace」。")
    L.append("6. **簇是合并的单元**：先按 `_relations.json` 的 `clusters` 把图分组，同簇内用 `anchors` 做接缝，")
    L.append("   跨簇的弱关系（如 #理论 标签）暂不做硬接缝。")
    L.append("")

    L.append("## 共享标签")
    L.append("")
    tagmap = {}
    for g in graphs:
        for t in g["tags"]:
            tagmap.setdefault(t, []).append(g["slug"])
    shared = {t: v for t, v in tagmap.items() if len(v) > 1}
    if shared:
        L.append("| 标签 | 出现在 |")
        L.append("|---|---|")
        for t, v in sorted(shared.items(), key=lambda kv: -len(kv[1]))[:20]:
            L.append("| #%s | %s |" % (t, "、".join("`%s`" % x for x in v)))
    else:
        L.append("没有跨图共享的标签。")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dir", default=ROOT, help="spec 所在目录（默认 skill 根）")
    ap.add_argument("--out-dir", default=PROJ, help="索引输出目录")
    a = ap.parse_args()

    files = sorted(p for p in glob.glob(os.path.join(a.dir, "*.json"))
                   if not os.path.basename(p).startswith("_"))
    graphs = [collect(p) for p in files]
    cands = candidates(graphs)
    rel_path = os.path.join(a.out_dir, "_relations.json")
    clusters, rels = load_relations(rel_path, graphs)
    # 已声明关系的图对，从候选接缝里剔除（避免同一对图既在"已声明"又在"候选"）
    declared_pairs = {(r["from"], r["to"]) for r in rels} | {(r["to"], r["from"]) for r in rels}
    cands = [c for c in cands if (c["a"], c["b"]) not in declared_pairs]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    if a.check:
        print("[CHECK] graphs=%d  declared=%d  candidate-pairs=%d  clusters=%d" % (
            len(graphs), len(rels), len(cands), len(clusters)))
        for g in graphs:
            print("  %-26s nodes=%-4d edges=%-4d ns=%s/" % (g["slug"], g["nodes"], g["edges"], g["namespace"]))
        return

    md = render_md(graphs, cands, clusters, rels, now)
    mdp = os.path.join(a.out_dir, "_图谱总索引.md")
    jsp = os.path.join(a.out_dir, "_图谱总索引.json")
    with io.open(mdp, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(md)
    payload = {
        "generatedAt": now,
        "mergeProtocol": {
            "nodeIdPrefix": "<namespace>/<id>",
            "namespace": "spec 文件名（不含 .json）",
            "anchorRule": "only merge anchors declared in relations; candidates need confirmation",
            "multiRoot": True,
        },
        "clusters": clusters,
        "graphs": [{k: v for k, v in g.items() if k != "titles"} for g in graphs],
        "relations": rels,
        "candidateSeams": cands,
    }
    with io.open(jsp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))
    print("[OK] %s" % mdp)
    print("[OK] %s" % jsp)
    print("[STAT] graphs=%d declared=%d candidate-pairs=%d" % (len(graphs), len(rels), len(cands)))


if __name__ == "__main__":
    main()
