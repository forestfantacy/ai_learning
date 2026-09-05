# mini-kb-robot

文本 FAQ 机器人：用户手写提问，机器人从知识库里确定性地选出唯一匹配条目，
由 LLM 生成自然语言回复，图片 URL 由代码程序化附加。检索用封闭枚举
function-calling 选择，而不是向量相似度 RAG——设计理由和取舍见项目内的
plan 文档。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 Ark 控制台 API Key、聊天模型、以及一个开了图片输入能力的视觉模型
```

`ARK_MODEL` 是运行时对话用的模型；`ARK_VISION_MODEL` 只有 `ingest/build_kb.py` 在给带图片的知识条目生成摘要时才用得到，两个都要去自己的 Ark 控制台确认账号下实际可用的模型名/Endpoint ID（`ep-...`），不能照抄 `examples/hotel_receptionist` 里的值。

## 重建知识库

知识库源头是业务方维护的 Excel（`知识ID`/`分类`/`问题`/`答案` 四列，答案是内嵌图片/链接的富文本）。
服务运行时**不会**解析 Excel，只加载 `data/knowledge_base.json` 这个生成产物。
每次业务方改了 Excel，重新跑一遍构建脚本：

```bash
python ingest/build_kb.py /path/to/【内】C端FAQ.xlsx
```

这一步现在需要 `.env` 配好 `ARK_API_KEY` + `ARK_VISION_MODEL`——只要 Excel 里有任何带图片、且还没被 `data/image_summary_cache.json` 缓存过的条目，脚本就会调视觉模型给它生成一句带图片内容的摘要（比如截图里具体是哪条 APP 路径），缺配置会直接报错而不是静默跳过，避免知识库里混进没生成摘要的条目。已经缓存过的图片不会重复调用，改动跟图片无关的条目不会重新花这份成本。

跑完后**务必看一眼** `data/dedupe_report.json`：
- `high_risk_ambiguous_pairs` 是问法相似但答案不同的候选对，这些 id 会在机器人的工具 schema 里被标 ⚠️，需要机器人反问用户澄清才能作答——如果这里出现了新的、值得补充人工消歧说明的簇，去 `data/overrides.yaml` 的 `disambiguation_hints` 加一条（这条 hint 会直接出现在工具索引里，不用再手动改 `llm/instructions.py`）。
- `likely_true_duplicates` 是问法相似且答案也相似的候选对，可能是真重复，人工看看要不要合并成一条。

`data/overrides.yaml` 是唯一需要人工编辑判断的文件：分类名归一化之外的个别错分类修正、消歧提示文案、手动强制/剔除某对 ambiguous_with 边。改完重跑构建脚本即可生效。

`data/knowledge_base.json` 和 `data/image_summary_cache.json` 都是构建产物，**需要提交进 git**（都不是密钥；前者重新跑构建脚本就能复现，后者是为了避免每次重建都重新花视觉模型的调用成本）。

## 运行

本地命令行调试（不走 HTTP，最快）：
```bash
python cli_chat.py
```

HTTP 服务：
```bash
uvicorn api.server:app --reload
```

```bash
curl -X POST localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "怎么开发票"}'
```

`POST /chat` 请求体 `{session_id?, message}`，返回 `{session_id, reply, image_urls, matched_entry_id, status}`，
`status` 是 `answered` / `clarifying`（机器人在反问）/ `no_match`（知识库里没有能回答的内容）/ `error`。
同一个 `session_id` 延续对话，好让"反问澄清 → 用户回答"这类多轮场景能接上上下文。

`POST /chat/stream` 是同一套逻辑的 SSE 版本：`event: delta` 逐字推送文本，最后一个 `event: done` 带上跟 `/chat` 一样的 `session_id`/`status`/`matched_entry_id`/`image_urls`（这几个字段本来就要等模型的工具调用决议完才知道，没法真正流式）。

浏览器打开 http://localhost:8000/ 是一个内置的手工测试页面（`web/index.html`，走 `/chat/stream`），可以直接多轮追问，回复下面会显示 `status` 徽章、命中的 `matched_entry_id` 和图片缩略图。

## 测试

```bash
pytest tests/test_ingest.py tests/test_kb_tool.py   # 不需要 API key
python scripts/run_scenarios.py                      # 需要真实 .env，跑真实对话场景
```

`scripts/run_scenarios.py` 里第一批场景专门验证"联名周边套餐/商品售罄"这组
易混淆问题不会被答错——这是整套确定性检索 + 反问澄清设计存在的根本原因，改动
`llm/instructions.py` 或 `kb/tool.py` 之后务必重跑一遍确认没有回归。
