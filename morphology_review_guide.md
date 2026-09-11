# MeanEase 人工构词审校规范

本规范用于人工逐词写入 MeanEase 的中文构词说明。`morphology_review_pipeline.py` 只能分发批次、验证和合并；它不得生成、改写或补全任何构词文字。

## 审校原则

1. 每个输入词必须人工处理一次，且一个输入词只能输出一条 JSONL 记录。
2. 有透明、可验证的派生关系时，写构词拆解；词形只是巧合、存在历史拼写变化、或只是复数/时态变化时，不能硬拆。构词拆解可以由 `engra` 或人工核对的 Wiktionary 支撑，来源字段必须如实记录。
3. 不能透明拆解的借词、核心词、专名、缩写或历史词，人工查看来源后写简短中文词源摘要，不把字母片段伪装成词根。
4. 没有充分证据时使用 `needs_review`，不要猜测；只在人工确认该词不应显示任何说明时使用 `not_decomposable`。
5. 每条 `accepted` 记录都要人工核对来源页面，并用 `evidence_summary` 以中文说明核对依据。它不是面向学习者的文案。

## 面向学习者的两种格式

### 可靠构词拆解

```text
reform / re-form；re-：重新、再次；form：形式、组成；reform：改革、改正。
```

- `/` 后至少有两个词素，拼接后必须与单词完全一致；
- 每个词素都要有中文解释，末尾要有该词的中文释义；
- 不把 `-s`、`-es`、`-ed`、`-ing` 作为构词后缀；
- 不把 `detail` 误写成 `de-tail`，也不把 `program` 误写成 `pro-gram`。

### 人工核对的词源摘要

```text
social：源自拉丁语 socialis；今义：社会的、社交的。
```

或：

```text
ad：截短自 advertisement；今义：广告。
```

已人工核对的缩写也可写成 `PM：英语缩写 p.m.（post meridiem）；今义：下午。`。

- 词源链最多两个节点，例如“源自古法语 X，可追溯至拉丁语 Y”；语言名称使用中文（可精确到“新拉丁语”等），专名来源可写成“源自人名 X”；
- 不重复同一个词项，且只保留本词学习有帮助的来源；
- 中文只写有依据的来源事实，不写“可能”“大概”或泛泛的“印欧词根”。

## JSONL 输出格式

每行是一个对象。已有来源若能支持人工说明，必须原样保留 `source_basis` 与 `source_license`；若旧来源本身不支持新的人工结论，审校员可以人工核对并改为该词对应的 English Wiktionary 页面与 `CC BY-SA 4.0`，同时在 `evidence_summary` 说明替换理由。原来没有来源而人工查到词源时，也只能使用对应的 English Wiktionary 页面和 `CC BY-SA 4.0`。

```json
{"batch_id":"<原 batch_id>","word_key":"reform","word":"reform","status":"accepted","note":"reform / re-form；re-：重新、再次；form：形式、组成；reform：改革、改正。","source_basis":"https://github.com/eslsoft/engra","source_license":"MIT","evidence_summary":"人工核对 engra 的 form 词族与 reform 词条；re- 和 form 的拼接与词义相符。","review_flags":[]}
```

不发布说明时，四个说明/来源字段必须为空：

```json
{"batch_id":"<原 batch_id>","word_key":"example","word":"example","status":"needs_review","note":"","source_basis":"","source_license":"","evidence_summary":"","review_flags":["需要进一步人工核对来源"]}
```

## 批次流程

1. 运行 `prepare` 只生成固定输入快照和 JSONL 批次；它不会生成解释。
2. 审校员人工阅读词条和来源，写入 `responses/` 中同一批次的 JSONL。
3. `merge` 仅接受完整批次，并写到不同于原词库的新 CSV。
4. 先检查批次报告与抽样，再把确认过的新 CSV 作为下一轮的输入快照。

需要审查已完成的一部分时，可在 `merge` 中重复传入 `--batch-id <批次 ID>`。该输出只用于阶段质量检查；若要把它作为下一轮输入，必须重新运行 `prepare`，不能把旧快照的未完成批次混入。

任何代理都不能直接改写 `us_core_7000_authentic.csv`，也不能自行杜撰来源 URL、许可证或构词关系。
