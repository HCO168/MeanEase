# 2026-09-11 人工构词审校记录

此目录保存人工逐词审校的 JSONL 输出，不是程序自动生成的数据。每一行都对应固定词库快照中的一个词，记录面向学习者的中文构词/词源短注、来源 URL、许可证和中文人工核对摘要。

## 输入快照

- 文件：`us_core_7000_authentic.csv`
- SHA-256：`ba42235ea625976aea72e238b2a4f9f98c9e57cfe441b2dde43a3e0579b0ad28`
- 批次大小：最初每批 100 词；从第 6 批开始，为保证逐词核对，拆为四份各 25 词。

## 使用方式

重新生成与此快照对应的输入批次：

```bash
python3 morphology_review_pipeline.py prepare --input us_core_7000_authentic.csv --output-dir tmp/morphology-review-20260911 --batch-size 100
```

把本目录的 `responses/` 作为 `merge --responses-dir` 的输入。合并器会拒绝输入 SHA-256 不一致、词项缺失/重复、未经允许的来源、格式不合格或不完整的批次。解释文本只能由审校员撰写；详见 [`../../morphology_review_guide.md`](../../morphology_review_guide.md)。

本目录只保存已经通过该轮结构和来源检查的批次。进行中的临时响应仍保存在 `tmp/`，待验证后才复制到这里。

当前已固化第 1–26 批、共 2,600 个词的人工审校记录；第 27 批及之后仍在逐词复核，未通过完整批次校验前不会写入本目录或正式词库。
