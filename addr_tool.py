# -*- coding: utf-8 -*-
"""Luhmann 式可插拔地址工具（黏菌图谱）

地址规则（一次分配，永不重排）：
  - 根 = 1
  - 子节点 = 父地址 + "." + 序号（该父下第 n 个孩子）：1.1、1.2
  - 要在已有序号之间插入 → 取前一个兄弟的地址 + 字母后缀：1.2 → 1.2a → 1.2b
  - 插入节点的孩子照常：1.2a.1
  - 移动节点 = 换地址（挂到新父下取下一号，子树整体换前缀）——因为「地址=位置」比「地址永不改」更有用；
    内部 id 不变，所以连线不会断

用法：
  # 给 spec 里所有缺地址的节点补地址（首次迁移 / 手写 spec 后）
  python addr_tool.py --spec X.json --fill

  # 在某节点末尾追加子节点
  python addr_tool.py --spec X.json --child-of 1.2 --title "新想法"

  # 在某节点之后插入兄弟（不重排后面的编号）
  python addr_tool.py --spec X.json --insert-after 1.2.6 --title "新想法"

  # 把节点（连同子树）移到另一个父下
  python addr_tool.py --spec X.json --move 1.1.3 --to 1.2

  # 只看不写
  python addr_tool.py --spec X.json --child-of 1.2 --title "试" --dry-run

写入后需要重跑 build_workbench.py 才反映到 HTML / 存档。
"""
import argparse
import io
import json
import os
import string
import sys
import hashlib


def load(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, spec):
    with io.open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)


def first_project(spec):
    projs = (spec.get("seed") or {}).get("projects") or []
    if not projs:
        sys.exit("spec 里没有 projects")
    return projs[0]


def iter_nodes(node, parent=None, depth=0):
    yield node, parent, depth
    for c in node.get("children") or []:
        yield from iter_nodes(c, node, depth + 1)


def find_by_addr(root, addr):
    for n, p, _d in iter_nodes(root):
        if n.get("addr") == addr:
            return n, p
    return None, None


def sibling_key(addr):
    """取地址最后一段（用于比较/排序）"""
    return (addr or "").split(".")[-1]


def next_number(parent):
    """该父节点下下一个可用的纯数字序号"""
    pfx = (parent.get("addr") or "") + "."
    used = 0
    for c in parent.get("children") or []:
        seg = sibling_key(c.get("addr"))
        if seg.isdigit():
            used = max(used, int(seg))
    return used + 1


def next_letter_after(addr, siblings):
    """在 addr 之后取一个字母后缀，保证落在 addr 与下一个兄弟之间"""
    siblings = [s for s in siblings if s.get("addr") and s["addr"] != addr]
    # 只跟「同一段」的兄弟比：父地址相同
    parent_addr = addr.rsplit(".", 1)[0] if "." in addr else ""
    same = [s["addr"] for s in siblings
            if (s["addr"].rsplit(".", 1)[0] if "." in s["addr"] else "") == parent_addr]
    for ch in string.ascii_lowercase:
        cand = addr + ch
        if all(not a.startswith(cand) for a in same):
            return cand
    sys.exit("单个位置已经用到 z 后缀，建议换个层级")


def rebase(node, addr):
    """把节点及其子树的地址整体换到 addr 之下"""
    node["addr"] = addr
    for i, c in enumerate(node.get("children") or [], 1):
        rebase(c, addr + "." + str(i))


def is_descendant(anc, node):
    for c in anc.get("children") or []:
        if c is node or is_descendant(c, node):
            return True
    return False


def audit(spec):
    """体检地址：缺失 / 重复 / 与父前缀不符。返回 [(类型, 地址, 细节)]"""
    root = first_project(spec).get("root")
    issues, seen = [], {}

    def walk(n, parent):
        a = n.get("addr")
        title = n.get("title") or "?"
        if not a:
            issues.append(("缺失", "-", title))
        else:
            if a in seen:
                issues.append(("重复", a, "%s ↔ %s" % (seen[a], title)))
            seen[a] = title
            if parent and parent.get("addr"):
                if not a.startswith(parent["addr"] + "."):
                    issues.append(("前缀不符", a, "父=%s · %s" % (parent["addr"], title)))
        for c in n.get("children") or []:
            walk(c, n)

    if root is not None:
        walk(root, None)
    return issues


def fill_addrs(spec):
    """给缺地址的节点补地址，返回补了多少个"""
    root = first_project(spec).get("root")
    if root is None:
        return 0
    filled = [0]

    def walk(n, parent, depth):
        if not n.get("addr"):
            if parent is None:
                n["addr"] = "1"
            else:
                parent.setdefault("addr", "1")
                n["addr"] = "%s.%d" % (parent["addr"], next_number(parent))
            filled[0] += 1
        for c in n.get("children") or []:
            walk(c, n, depth + 1)

    walk(root, None, 0)
    return filled[0]


def make_node(title, addr, note="", closure=0):
    return {
        "id": "n" + hashlib.md5(addr.encode("utf-8")).hexdigest()[:6],
        "addr": addr,
        "title": title,
        "note": note,
        "closure": closure,
        "tags": "",
        "state": "active",
        "children": [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--fill", action="store_true", help="给所有缺地址的节点补地址")
    ap.add_argument("--check", action="store_true", help="审计地址：缺失 / 重复 / 前缀不符")
    ap.add_argument("--child-of", help="父节点地址，追加为该父的最后一个孩子")
    ap.add_argument("--insert-after", help="兄弟节点地址，插在它后面（字母后缀，不重排）")
    ap.add_argument("--move", help="要移动的节点地址（连同子树）")
    ap.add_argument("--to", help="移到哪个父节点下（配合 --move）")
    ap.add_argument("--title", default="新分支")
    ap.add_argument("--note", default="")
    ap.add_argument("--closure", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    spec = load(a.spec)
    proj = first_project(spec)
    root = proj.get("root")
    if root is None:
        sys.exit("spec 里没有 root")

    if a.check:
        issues = audit(spec)
        if not issues:
            print("[CHECK] 地址全部合法（无缺失 / 无重复 / 前缀一致）")
            return
        for kind, addr, detail in issues:
            print("[CHECK][%s] %s · %s" % (kind, addr, detail))
        print("[CHECK] 共 %d 处问题" % len(issues))
        sys.exit(1)

    if a.fill:
        n = fill_addrs(spec)
        if not a.dry_run:
            save(a.spec, spec)
        print("[FILL] 补了 %d 个地址%s" % (n, "（dry-run 未写）" if a.dry_run else ""))
        if not (a.child_of or a.insert_after):
            return

    if a.child_of:
        parent, _pp = find_by_addr(root, a.child_of)
        if parent is None:
            sys.exit("找不到地址 %s" % a.child_of)
        parent.setdefault("addr", "1")
        addr = "%s.%d" % (parent["addr"], next_number(parent))
        node = make_node(a.title, addr, a.note, a.closure)
        parent.setdefault("children", []).append(node)
        if not a.dry_run:
            save(a.spec, spec)
        print("[ADD] %s → 父 %s%s" % (addr, a.child_of, "（dry-run 未写）" if a.dry_run else ""))
        return

    if a.move:
        if not a.to:
            sys.exit("--move 需要配 --to <新父地址>")
        node, oldp = find_by_addr(root, a.move)
        newp, _np = find_by_addr(root, a.to)
        if node is None:
            sys.exit("找不到要移动的地址 %s" % a.move)
        if newp is None:
            sys.exit("找不到目标父地址 %s" % a.to)
        if node is newp or is_descendant(node, newp):
            sys.exit("不能把节点移到它自己的子树里")
        if oldp is None:
            sys.exit("根节点不能移动")
        oldp["children"] = [c for c in oldp["children"] if c is not node]
        newp.setdefault("addr", "1")
        new_addr = "%s.%d" % (newp["addr"], next_number(newp))
        rebase(node, new_addr)
        newp.setdefault("children", []).append(node)
        if not a.dry_run:
            save(a.spec, spec)
        print("[MOVE] %s → %s（子树已换前缀）%s" % (a.move, new_addr, "（dry-run 未写）" if a.dry_run else ""))
        return

    if a.insert_after:
        target, parent = find_by_addr(root, a.insert_after)
        if target is None:
            sys.exit("找不到地址 %s" % a.insert_after)
        sibs = (parent.get("children") if parent else [root]) or []
        addr = next_letter_after(target["addr"], sibs)
        node = make_node(a.title, addr, a.note, a.closure)
        if parent is None:
            # 插在根之前没有意义
            sys.exit("根节点不可插入兄弟")
        # 落在「同一前缀这一串」的末尾：1.1.1 之后已有 1.1.1a 时，新号要排在它后面
        kids = parent["children"]
        last = max(i for i, s in enumerate(kids)
                   if (s.get("addr") or "").startswith(target["addr"]))
        parent["children"].insert(last + 1, node)
        if not a.dry_run:
            save(a.spec, spec)
        print("[INSERT] %s → 在 %s 之后%s" % (addr, a.insert_after, "（dry-run 未写）" if a.dry_run else ""))
        return

    print("没给动作：用 --fill / --child-of / --insert-after")


if __name__ == "__main__":
    main()
