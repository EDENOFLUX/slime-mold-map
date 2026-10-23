# slime-mold-map · 黏菌图谱引擎

把一个 **JSON 规格文件**渲染成可交互的黏菌图谱（思维导图 / 关系网络）HTML 快照。

> 引擎本身不含任何个人数据：仓库只有渲染器、模板与一个虚构示例。
> 你的图谱内容留在自己的 vault 里，用 `--spec` 指向它即可。

## 是什么

- **规格是唯一真相**：`*.json` 描述节点树与关系边；HTML 是派生产物。
- **单文件快照**：输出一个自包含 HTML（无外部依赖），可直接双击打开或丢进静态站点。
- **六种分析镜片**：结构、二阶效应、机会成本、精要主义、贝叶斯、复利——按节点属性计算高亮。
- **可扩展**：自己加镜片、加字段、加渲染器。

## 快速开始

```bash
python build_workbench.py --spec examples/hello.json --out hello.html
```

打开 `hello.html` 即可看到图谱。

## 规格格式（最小）

```json
{
  "title": "示例图谱",
  "subtitle": "一句话说明",
  "closureLabel": "结构性闭合度",
  "seed": {
    "projects": [{
      "name": "示例项目",
      "root": {
        "title": "根节点",
        "note": "节点说明",
        "closure": 100,
        "size": "L",
        "children": [
          { "title": "子节点 A", "note": "说明", "closure": 60, "size": "M" }
        ]
      },
      "edges": [
        { "from": "子节点 A", "to": "根节点", "type": "support",
          "valence": "for", "weight": 80, "why": "为什么连这条线", "src": 3 }
      ]
    }]
  }
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `title` / `note` | 节点标题与说明 |
| `closure` | 0–100，结构性闭合度（染圈环用） |
| `size` | `S` / `M` / `L`，控制节点视觉重量 |
| `children` | 子节点数组 |
| `edges[].type` | `support` / `derive` / `same` / `contradict` …（决定连线样式与镜片判定） |
| `edges[].valence` | `for` / `against` |
| `edges[].weight` | 0–100，线宽与信息流强度 |
| `edges[].why` | **必填**：这条关系凭什么成立（渲染时可查看） |

## 命令行

```bash
python build_workbench.py --spec <spec.json> --out <out.html> [--vault <vault根>] [--archive <md路径>]
```

- `--vault`：解析 `doc` 字段（节点关联的 Markdown）时用的仓库根，默认当前目录。
- `--archive`：额外导出一份 Markdown 存档。

## 目录

```
build_workbench.py        渲染器（规格 → HTML）
黏菌图谱.template.html     模板（样式 + 交互）
addr_tool.py              批量补节点编号（addr）
build_index.py            生成图谱索引
verify_docs.js            校验节点引用的文档是否存在
examples/hello.json       虚构示例（10 节点，无个人信息）
```

## 作者

**Luci逻辑喵**（[@EDENOFLUX](https://github.com/EDENOFLUX)）
—— 写东西的人，顺手做了个把想法长成图的东西。

## 许可

见 `LICENSE`。
