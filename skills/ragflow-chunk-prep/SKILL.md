---
name: ragflow-chunk-prep
description: 为 RAG 知识库准备 PDF/DOCX 源文档，在判断出的最佳切块边界处插入 <<<CHUNK>>> 分隔标记段落，产出一份 .docx；表格按行数/话题特征自动决定保留成真表格还是拆成独立文本段落，以获得最佳检索召回率和准确率。当用户想要对文档进行切块/预切块，或想为知识库上传做准备，或提到人工切块边界、RAG 召回率优化时使用。
---

## 目标

给定一份 PDF 或 DOCX 源文档，产出一份新的 `.docx`：在最佳切块边界处插入独立成行的 `<<<CHUNK>>>` 标记段落，表格根据自身特征保留为真表格或拆成文本。输出格式固定是 `.docx`；不要输出 markdown 或纯文本。

质量把关不依赖用户自己判断——用户大多数情况下无法判断切块边界或表格分类是否合理。凡是能写成机械检查的正确性问题，必须用脚本强制校验、失败就自己修；需要理解力的判断，由 Claude 自己对照下面的判断清单二次自查。用户默认只收到一份处理结果摘要，只有当校验或自查发现了自己解决不了的问题时才需要打断流程去问用户，并且要说清楚具体是哪里出的问题。

## 阶段 0：输入判断

拿到源文件路径，按扩展名判断是 `.docx` 还是其他（当作 PDF 处理）。

## 阶段 1：选择路径

- `.docx` 源文件 → 路径 A（增量编辑，不重新誊写已有内容）。
- 其他（`.pdf` 等）→ 路径 B（从零重建）。

## 阶段 2A：路径 A（DOCX 输入）

1. 运行 `python3 ~/.claude/skills/ragflow-chunk-prep/scripts/inspect_docx.py <input.docx>`，完整阅读输出的 JSON（不要只看摘要，每段文字、每张表格的完整数据都要看）。
2. 套用下面的「切块判断清单」和「表格处理规则」，把结果写成 `plan.json`：
   ```json
   {
     "insert_marker_after": [3, 7, 12],
     "flatten_tables": {"9": ["拆分后第1段陈述句", "拆分后第2段陈述句"]},
     "label_prefix": {"8": "开业前两天·"}
   }
   ```
   `label_prefix` 是可选字段：key 必须是某个 chunk 起始段落的 index（0，或紧跟在某个 `insert_marker_after` 索引之后），value 是要拼接到该段落原文字前面的前缀，约定前缀自带「·」分隔符。只能用于 chunk 起始段落，不能用于 chunk 中间的段落，也不能指向 `flatten_tables` 新生成的段落。
3. 运行 `python3 ~/.claude/skills/ragflow-chunk-prep/scripts/verify_plan_completeness.py <inspect_docx.py的输出存成的json文件> plan.json`。有 `FAIL` 就回去改 `plan.json` 直到没有 `FAIL`；每条 `WARN` 都要逐条核实是否真的遗漏了内容。
4. 对照「切块判断清单」重新自查一遍 `plan.json`：chunk 有没有过长、表格分类是否符合规则、每个 chunk 单独拿出来读是否说得通（层级深的 chunk 是否需要用 `label_prefix` 补标题前缀）。发现问题自己改，回到第 3 步重新校验。
5. 运行 `python3 ~/.claude/skills/ragflow-chunk-prep/scripts/apply_plan_docx.py <input.docx> <output.docx> plan.json`，确认输出里有 `SELF-CHECK: PASS`。如果是 `FAIL`，排查原因后重试，不允许在 `FAIL` 状态下汇报完成。
6. 给用户一份摘要：分了几块、哪些表格保留成了真表格、哪些被拆分、校验过程中有没有需要注意的地方。只有第 3-5 步出现解决不了的问题时才需要中断去问用户，并说明具体是哪个位置、什么问题。

## 阶段 2B：路径 B（PDF 输入）

1. 用 Read 工具读 PDF（篇幅长就分页读）。**表格务必依据渲染出来的版式重建行列关系，不要相信任何线性文本抽取给出的顺序**——PDF 的文本抽取顺序经常和表格实际的行列对应关系对不上。
2. 按 `inspect_docx.py` 同款 schema（`{"total_elements": N, "elements": [...]}`），把读到的全部内容手写成一份 `elements.json`，作为后续完整性校验的比对基准——这一步不能省略。
3. 套用「切块判断清单」和「表格处理规则」，写出 `plan.json`：
   ```json
   {
     "chunk_groups": [
       {"elements": [
         {"type": "paragraph", "style": "Heading 1", "text": "..."},
         {"type": "paragraph", "text": "..."},
         {"type": "table", "rows": [["a", "b"], ["c", "d"]]}
       ]},
       {"elements": [{"type": "paragraph", "text": "..."}]}
     ]
   }
   ```
   表格要跟引出它的说明段落放在同一个 `elements` 里。
4. 运行 `verify_plan_completeness.py elements.json plan.json`，处理方式同阶段2A 第3步。
5. 对照「切块判断清单」自查 `plan.json`，同阶段2A 第4步。
6. 运行 `python3 ~/.claude/skills/ragflow-chunk-prep/scripts/build_docx_from_plan.py plan.json <output.docx>`，确认 `SELF-CHECK: PASS`；`FAIL` 就排查重试。
7. 给用户摘要，同阶段2A 第6步。

## 切块判断清单

- 默认一个自然的标题/小节边界对应一个 chunk。
- 琐碎的、紧挨着的短小前言段落合并成一个 chunk，不留碎片状的独立小 chunk。
- 一节内容如果罗列了多个可以被独立查询的条目，拆成一个条目一个 chunk。
- 举例说明要跟它演示的步骤放在同一个 chunk 里，拆开会丢失举例的意义。
- 每个 chunk 要能单独拿出来读懂——如果一个大节被多个 marker 切成了几个 chunk，后面几个 chunk 的正文里往往读不出自己属于哪个大节（例如"3.5 开业前两天"被拆成 3 个 chunk，第 2、3 个分别以"社群验收""新店开业审核申请"开头，完全没有"开业前两天"字样，检索时容易漏召回）。遇到这种情况，用 plan.json 的 `label_prefix` 字段给该 chunk 起始段落的文字前面拼接最近的标题/标签词作为前缀，前缀和原文字之间用「·」分隔。
  - **是否需要打标签、标签具体写什么内容，由 Claude 在步骤4自查时凭理解力判断，不是自动检测项**。`verify_plan_completeness.py` 只做机械校验（index 确实是段落、确实是 chunk 起始位置、前缀非空、前缀文字确实能在文档更早处逐字找到、没有明显和原文重复），不会替你判断"这段是不是该打标签的深层级内容"，也不保证你挂的是"哪一个"更早的标题——那部分仍然是理解力判断。
  - **只对判断为真正孤立（深层级、正文读不出所属大节）的少数 chunk 打标签，不要对全部 chunk 无差别套用**——多数 chunk 本身有清晰标题不需要标签，无差别套用等于让额外生成的内容混进正文、偏离原文措辞。
- 长度上限：软上限约 500 token，硬上限约 800 token；超限时在最近的自然句子/段落边界处拆分，不要在句子中间硬切（没有任何下游机制会替你兜底截断）。

## 表格处理规则

按表格自身特征自动判断，不用每次都问用户：

- **数据行数少（约 8 行以内）且所有行都在回答同一个问题**（每行只是同一套字段的不同取值，比如"档位→分数"这种单一维度对照）→ **保留成真表格**。
- **数据行数较多，或者每一行代表不同的子话题/子指标**（每行字段结构不同，内容彼此不构成同一维度上的可比较关系）→ **按行或按话题拆成独立的陈述句段落**，不用表格形式。
- 无论哪种处理方式，表格（或拆分后的文本块）前面都要保留一段引出它的说明文字。
- 行数阈值是经验值，可以根据具体文档内容酌情调整。


## Supporting Files

| 文件 | 作用 | 何时使用 |
|---|---|---|
| `scripts/inspect_docx.py` | 按文档顺序枚举 docx 正文，导出完整段落文字+完整表格数据的 JSON | 路径A 步骤1——通过 Bash 运行 |
| `scripts/verify_plan_completeness.py` | 校验 plan.json 有没有相对源文档漏内容/漏数字 | 两条路径都要用，写完 plan.json 之后——通过 Bash 运行 |
| `scripts/apply_plan_docx.py` | 按增量方案插入标记、替换表格、给深层 chunk 起始段落拼接标题前缀（`label_prefix`），其余内容原样保留，自带结构自检 | 路径A 步骤5——通过 Bash 运行 |
| `scripts/build_docx_from_plan.py` | 按完整方案从零组装一份新 docx，自带结构自检 | 路径B 步骤6——通过 Bash 运行 |
