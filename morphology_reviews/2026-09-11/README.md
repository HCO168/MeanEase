# 2026-09-11 人工构词审校记录

此目录保存人工逐词审校的 JSONL 输出，不是程序自动生成的数据。每一行都对应固定词库快照中的一个词，记录面向学习者的中文构词/词源短注、来源 URL、许可证和中文人工核对摘要。

本批次属于旧 `etymology*` 数据结构的历史归档。当前正式词库已改用 `morphology*` 和 v5 拆解规则；这些响应、旧校验器与其输出都不能直接合入或覆盖当前 CSV。历史快照若不可用，应只阅读和审计归档记录，不要用当前 CSV 重新生成批次。

## 输入快照

- 文件：`us_core_7000_authentic.csv`
- SHA-256：`ba42235ea625976aea72e238b2a4f9f98c9e57cfe441b2dde43a3e0579b0ad28`
- 批次大小：最初每批 100 词；从第 6 批开始，为保证逐词核对，拆为四份各 25 词。

## 使用方式

仅当上述 SHA-256 对应的旧输入快照仍可验证取得时，才能重新生成相应输入批次：

```bash
python3 morphology_review_pipeline.py prepare --input us_core_7000_authentic.csv --output-dir tmp/morphology-review-20260911 --batch-size 100
```

把本目录的 `responses/` 作为 `merge --responses-dir` 的输入。合并器会拒绝输入 SHA-256 不一致、词项缺失/重复、未经允许的来源、格式不合格或不完整的批次。解释文本只能由审校员撰写；详见 [`../../morphology_review_guide.md`](../../morphology_review_guide.md)。

本目录只保存已经通过该轮结构和来源检查的批次。进行中的临时响应仍保存在 `tmp/`，待验证后才复制到这里。

本归档固化了第 1–83 批、共 8,300 个词的人工审校记录。第 83 批含 95 条 `accepted` 说明和 5 条 `needs_review` 记录；非 `accepted` 记录不发布词源文字。该历史批次状态不代表当前正式词库的覆盖率或发布状态。
