# 英语词汇学习：间隔复习工具

英语词汇学习是一个 local-first、可离线运行的英语词汇学习工具。服务器静态 CSV 是内置词库来源，浏览器 IndexedDB 缓存词典资料并维护实时学习状态；用户也可以在 HCONet 网页版中手动把精简的个人元数据 CSV 保存到 Drive 应用数据区。应用按照学习过的单词数量安排再次出现的位置，并支持键盘操作、浏览器美式英语发音、CSV 词库导入以及完整 JSON 进度备份。

## 主要文件

| 文件 | 用途 |
| --- | --- |
| `vocab_coach.html` | 完整的单文件学习应用 |
| `us_core_7000_authentic.csv` | 20,000 词正式数据文件；历史文件名为兼容旧版一键更新而保留 |
| `启动英语词汇学习.command` | macOS 双击启动入口 |
| `启动英语词汇学习.bat` | Windows 双击启动入口 |
| `更新英语词汇学习.command` | macOS 一键拉取最新版 |
| `更新英语词汇学习.bat` | Windows 一键拉取最新版 |
| `update_vocab.py` | 兼容 Git 克隆与 ZIP 下载版本的安全更新核心 |
| `start_vocab.py` | 自动启动本地服务器并打开浏览器 |
| `build_authentic_7000.py` | 从 ECDICT 重新构建可信核心词库 |
| `apply_cefr_levels.py` | 从 American Oxford 3000/5000 PDF 添加 CEFR 学习难度 |
| `enrich_wiktionary_etymology.py` | 流式筛选 Wiktextract 数据并补充中间英文词源 |
| `enrich_chinese_word_formation.py` | 用 engra 结构关系和 Wiktionary 来源生成中文构词短注 |
| `enrich_tatoeba_examples.py` | 从 Tatoeba 校对语料补充可溯源双语例句 |
| `audit_vocabulary.py` | 检查 CSV 结构、覆盖率、重复词和模板化伪数据 |

## 启动

macOS 直接双击 `启动英语词汇学习.command`，Windows 直接双击 `启动英语词汇学习.bat`。也可以在终端运行：

```bash
python3 start_vocab.py
```

启动器固定使用 `http://127.0.0.1:8765` 并打开浏览器，按回车键或 `Ctrl+C` 停止。IndexedDB 按协议、主机和端口隔离；自动切换到 8766 会表现为一份全新存档。因此重复启动会复用已经运行的 8765 页面，端口被其他程序占用时则明确报错，不会悄悄换端口。

通过 HTTP 打开时，应用会在首次使用时自动读取同目录的 `us_core_7000_authentic.csv`。旧版 7,000 词用户会自动迁移到 20,000 词：已有卡片只更新词典元数据，调度状态保持不变，再追加 13,000 张新卡。直接双击 HTML 也可以运行，但部分浏览器会阻止页面读取相邻文件，此时点击“导入词库”并手动选择 CSV。

## 学习流程

1. 应用不设每日单词上限，优先选取已经到达复习位置的卡片，再持续补充新卡。
2. 卡片正面显示单词、音标和 Oxford 难度参考。可以直接评级，也可以先翻面核对答案。
3. 五种操作决定单词下一次出现的位置，或将其移出学习列表：

| 按键 | 操作 | 下一次出现 |
| --- | --- | --- |
| `1` | 重来 | 大约经过 8 个词 |
| `2` | 困难 | 大约经过 20 个词 |
| `3` | 记得 | 大约经过 100 个词 |
| `4` | 熟练 | 大约经过 1000 个词 |
| `5` | 移出 | 不再进入学习队列 |

每次排期使用正态分布增加轻微随机性，标准差为目标词距的 10%。全局 `studyPosition` 和每张卡的 `duePosition` 都会写入 IndexedDB，因此刷新或重新启动后仍能恢复原来的词距。到达同一优先级的卡片会从队首小窗口中随机抽取，新词也会从频率顺序靠前的 32 个候选中随机选择，避免下一个词永远固定。

选择 1–4 后直接进入下一张卡片，不显示逐次的“约 X 个词后出现”底部提示；排期距离仍可在按钮副标题中查看。选择 5 移出学习列表时仍显示确认提示。

## Placement Test 与分级学习

点击“词汇定级”可以完成 18 道自适应词义题。测试从 B1 难度开始，依次覆盖 A1、A2、B1、B2、C1 和 Beyond C1；答对后提高下一题难度，答错或选择“不知道”后降低难度。能力值使用逐题更新的 logistic 概率模型，不用固定正确率直接套级别。定级题与普通学习词分开筛选：A1-B2 使用 Oxford 核心词，C1 使用 Oxford 与 Octanove C1 核心词，Beyond C1 只使用有 Octanove C2 明确来源的词。C2 阶段约 75% 为 C2 题、25% 为按 C1 难度计分的校准题；干扰选项也只来自合格的 C1/C2 测试池。CEFR-J 单独补充的主题词和 `Unrated` 词不会进入测试题或干扰选项。

每道题作答后，能力值、答题数、正确数、“不知道”数和已用词都会立即写入 IndexedDB。测试中退出或关闭页面后，侧栏会显示已完成题数，下次可继续；第 18 题完成时结果会自动保存，不依赖额外确认按钮。设置和定级弹窗均有可见关闭按钮，测试页另有“退出测试（自动保存进度）”。

分级依据为 Oxford University Press 官方提供的 American Oxford 3000/5000 CEFR 列表：

- Oxford 3000：A1-B2；
- Oxford 5000 新增词：B2-C1；
- Oxford 未覆盖的词先用 CEFR-J 补足 A1-B2，再用 Octanove 补足 C1-C2；只有 Octanove 明确标为 C2 的词才映射为 `Beyond C1`，其余未匹配词保持 `Unrated`。

测试结果是词义识别能力估算，不是正式 CEFR 认证。正式 placement test 通常还会测试阅读、听力、语法和语言运用。

完成测试后，新词约 75% 来自测得级别，25% 来自相邻的更高一级。例如 B1 学习范围为 B1 和 B2。Beyond C1 结果采用约 75% 有明确 C2 来源的词和 25% C1 巩固词，并在结果页提示学习者英语水平较高。此前已经学过的词仍会按记录的词序位置复习。

## 快捷键

| 按键 | 操作 |
| --- | --- |
| `Space` | 翻面 |
| `1` | 重来 |
| `2` | 困难 |
| `3` | 记得 |
| `4` | 熟练 |
| `5` | 移出学习列表 |
| `S` | 朗读单词 |
| `D` | 朗读例句 |

## 数据存储

- 内置 20,000 词资料来自服务器静态文件 `us_core_7000_authentic.csv`；浏览器会把它缓存到 IndexedDB 数据库 `vocab_coach_db`，但不会把词典正文复制进个人云存档。
- 逐卡调度和个人元数据实时保存在 IndexedDB。日常评级、设置变更和定级测试不会自动发送网络请求。
- IndexedDB 属于浏览器用户配置和固定来源 `http://127.0.0.1:8765`，不在项目目录，不会随 Git 提交上传。
- 每日统计以本地日期为键保存，用于当天计数和连续学习天数。
- 主题偏好单独保存在 LocalStorage。
- “备份进度”导出 schema v5 JSON，只包含非默认逐卡词距调度、全局学习位置、设置、每日统计、定级结果和未完成测试；静态词义、音标、例句、难度和构词资料不进入进度文件。
- `.gitignore` 忽略 `vocab-coach-backup-*.json`，避免标准命名的个人备份被误提交。
- 页面底部提供独立的“导入进度”按钮，只接受备份 JSON，并在替换当前状态前明确确认。
- 新版备份带 SHA-256 完整性值；导入前先完整校验元数据和调度字段，再用单个 IndexedDB 事务把个人字段应用到当前词库，失败不会留下半恢复状态。
- 仍兼容 schema v2、v3 和 v4 旧备份。浏览器在本地将旧完整卡片提取为 compact v5 个人记录，旧的按天进度会安全迁移为立即可复习的词距记录；恢复成功后自动下载转换后的 v5 文件，转换过程不访问服务器。
- 自定义词库正文与个人进度明确分离。v5 只保存可按规范化单词键匹配的个人状态；跨设备使用自定义词库时，需要先单独导入相同词库，再导入进度。
- HCONet 网页版设置中的“保存到云端”会按需生成 UTF-8 CSV，只包含变化过的单词调度、设置、统计、定级数据、主题和全局学习位置，然后通过 Drive App Data API 上传；单文件上限为 4 MiB。
- 云存档固定命名为 `meanease_personal_data.csv`，保存在用户专属的 MeanEase 应用数据目录。保存和恢复都必须由用户点击触发，不做后台或定时同步。
- 客户端记录最近一次已知云端 revision。发现云端 revision 不一致时，必须在覆盖前确认；后端仍以原子 revision 检查作为并发写入的最后防线。
- 独立 `127.0.0.1:8765` 版没有 HCONet 域 Cookie，只支持本地进度与 JSON 导入导出；云存档支持 `https://meanease.hconet.com` 和开发域 `http://meanease.hconet.localhost`。

使用 IndexedDB 是必要的。将 20,000 条完整词条连同调度状态写入 LocalStorage 会超过常见容量限制，也不适合频繁的逐卡更新。

## 个人云存档 CSV

个人 CSV 使用 UTF-8 with BOM 和 RFC 4180 引号规则，表头为：

```csv
record_type,key,state,due_position,interval,ease,reps,lapses,last_reviewed,removed_at,value
```

- `record_type=meta` 的行通过 `key/value` 保存 schema 版本、静态词库版本、导出时间、主题、设置、每日统计、定级状态和 `studyPosition`；结构化值使用 JSON 文本。
- `record_type=word` 的行以规范化小写单词作为 `key`，只写入不再处于默认状态的卡片；词义、音标、例句、难度和构词资料仍从静态词库读取。
- 恢复时先验证 schema、重复键、状态、数值范围、日期和定级数据，再按单词键匹配当前静态词库。已经不在当前词库中的记录会被忽略并向用户报告数量。
- 恢复事务先把当前词库的个人字段重置为默认值，再应用 CSV 中的变化记录，因此云存档代表完整的个人状态快照，而不是增量补丁。

## CSV 格式

文件使用 UTF-8 with BOM，标准表头如下：

```csv
word,base_word,phonetic,pos,meaning,level,level_source,placement_eligible,collocation,etymology,etymology_source,etymology_license,example_en,example_zh,example_source,example_license
```

应用的解析器支持 RFC 4180 常用格式，包括：

- 双引号字段；
- 字段内逗号；
- 字段内换行；
- 以两个双引号表示一个字面双引号；
- Windows 与 Unix 换行符；
- UTF-8 BOM。

导入时按不区分大小写的 `word` 去重。资料缺失不会被模板文字自动填满，卡片会明确显示“待可信来源补充”。

`base_word` 用于让 `supposed`、`works` 等词形继承基础词的级别；`level` 可以是 `A1`、`A2`、`B1`、`B2`、`C1`、`Beyond C1` 或 `Unrated`。`level_source` 记录具体判定来源，`placement_eligible` 则把普通学习词与适合能力测试的核心词分开。

## 词库质量策略

默认词库的词频、音标、词性和中文释义来自开源 ECDICT。构建器按 `frq` 当代语料频率顺序选出 20,000 个合法英文词条。只有词典释义明确写出 `vt.` 或 `vi.` 时才保留及物性标记；没有依据时只标为 `v.`，不会猜测。

难度采用保守的多源合并：Oxford 3000/5000 优先，CEFR-J Wordlist 1.5 只补充未匹配的 A1-B2 词，Octanove Vocabulary Profile 1.0 再补充 C1-C2。CEFR-J 数据归东京外国语大学投野研究室所有，可在正确署名下免费用于研究和商业用途；Octanove C1/C2 数据采用 CC BY-SA 4.0。没有任何来源明确分级的词保留为 `Unrated`，不会因为“不在 Oxford 核心词表”就自动升级为 Beyond C1。

构词短注优先使用 MIT 许可的 engra 结构化词根关系，生成 `reform / re-form；re-：重新、再次；form：形式、组成；reform：改革、改正。` 这类中文记忆说明。没有可靠拆解时，只把 Wiktionary 中能明确识别的来源语言压缩成中文短句；无法确定就留空，不猜词根。

双语例句来自 Tatoeba 的英中句对，经 ManyThings 筛选为母语者或已校对内容。构建器只接受目标词的完整单词匹配，优先选择简体、长度适中的句子，并过滤不适合通用学习卡片的敏感内容。每个非空例句保存 Tatoeba 原句页面和 `CC BY 2.0 FR` 许可证。ECDICT 不稳定提供搭配，因此搭配仍保持为空。

重新构建：

```bash
python3 build_authentic_7000.py
python3 apply_cefr_levels.py
python3 enrich_wiktionary_etymology.py
python3 enrich_chinese_word_formation.py
python3 enrich_tatoeba_examples.py
```

若需要保留另一个 CSV 的词序，可显式传入：

```bash
python3 build_authentic_7000.py --input my_word_list.csv --output my_authentic_deck.csv
```

## 数据审计

运行：

```bash
python3 audit_vocabulary.py us_core_7000_authentic.csv
```

审计内容包括：

- 学习字段、`base_word`、`level`、`level_source`、`placement_eligible`、构词与例句来源及许可证；
- 空单词与重复单词；
- 每个字段的有效覆盖率；
- 音标是否只是原词加斜杠；
- `use word`、通用词源、模板例句等伪数据模式。

当前默认词库的构建结果：

- 20,000 行，无重复词；
- 中文释义覆盖率 100%；
- 音标覆盖率约 95.0%；
- 词性覆盖率约 77.4%；
- 9,696 个词获得多源 CEFR 分级，10,304 个词保守地保持未定级；
- Beyond C1 从原先错误兜底的 13,765 个缩减为 548 个有明确 Octanove C2 证据的词；
- 定级测试池为 A1 1,130、A2 1,036、B1 854、B2 1,565、C1 2,130、Beyond C1 548 个核心词；
- 中文构词或来源短注覆盖 13,677 个词，约 68.4%；
- 可溯源 Tatoeba 双语例句覆盖 4,831 个词，约 24.2%；
- 所有非空构词和例句均附来源页面与许可证；
- 未填充任何模板化搭配或程序生成例句。

## 浏览器兼容性

目标为最新版 Chrome、Edge 和 Safari。应用依赖：

- IndexedDB；
- Web Speech API；
- `<dialog>`；
- `structuredClone`；
- CSS `color-mix()`。

语音质量由操作系统安装的英文语音决定。页面优先选择 `en-US`，没有时回退到其他英语语音。

## 验证

开发完成后执行了以下检查：

```bash
node -e "/* 提取并编译 HTML 内联脚本 */"
python3 -m py_compile build_authentic_7000.py apply_cefr_levels.py enrich_wiktionary_etymology.py enrich_chinese_word_formation.py enrich_tatoeba_examples.py audit_vocabulary.py
python3 audit_vocabulary.py us_core_7000_authentic.csv
```

并使用真实 Chromium 浏览器验证了：测试逐题存盘、退出续测、结果自动保存、页面刷新、Python 服务停止后同端口重启、可视化关闭、桌面卡片与评级区布局、只含变化记录的 schema v5 备份下载、SHA-256 校验、篡改拒绝及事务式恢复；另以含静态词典字段的 schema v4 文件验证了本地转换、恢复一条个人记录、自动下载 v5 文件，以及转换结果不会携带旧释义或例句。

## 后续开发建议

1. 继续补充授权清晰的搭配语料，并按来源字段记录许可证和出处。
2. 若要采用 FSRS，应引入官方 `fsrs.js`，同时设计旧调度数据迁移，而不是复制不完整公式。
3. 增加词条编辑器，让用户人工补充搭配、词源与例句，并区分“词典数据”和“个人笔记”。
4. 增加可选的学习历史图表，但不应让统计信息压过当天复习任务。
