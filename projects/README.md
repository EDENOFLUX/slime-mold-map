# projects/

图谱规格放这里，一个文件一张图。

- 命名：`<slug>.json`（小写、连字符）
- 每张图一个 `seed.projects[0]`
- 边必须有 `why`
- 渲染：`python ../build_workbench.py --spec <slug>.json --out ../out/<slug>.html`
