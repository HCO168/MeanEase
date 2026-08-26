# MeanEase｜英语词汇学习

一个无需后端的英语词汇学习工具，内置 20,000 词英汉词库、CEFR 难度参考、中文构词短注、可溯源双语例句、自适应词汇定级、词距复习队列、发音和稳定进度备份。

在线使用：[https://meanease.hconet.com](https://meanease.hconet.com)

## 启动

- Windows：双击 `启动英语词汇学习.bat`
- macOS：双击 `启动英语词汇学习.command`
- 其他平台：运行 `python3 start_vocab.py`

启动器固定使用 `http://127.0.0.1:8765` 并自动打开浏览器。浏览器会按网址保存 IndexedDB，因此启动器不会自动换端口；重复启动时会直接打开已经运行的页面。按回车键或 `Ctrl+C` 停止服务。Python 建议使用 3.9 或更高版本，无需安装第三方依赖。

## 更新

- Windows：双击 `更新英语词汇学习.bat`
- macOS：双击 `更新英语词汇学习.command`

无论通过 `git clone` 还是 GitHub ZIP 下载，都可以一键更新。Git 仓库会执行安全的快进更新；ZIP 版本会下载最新版、校验应用和 20,000 词库后再替换文件。学习进度保存在浏览器中，不会被代码更新清除。旧版 7,000 词用户首次打开新版时会自动扩容，并保留原有复习状态。

## 数据与隐私

词库、逐卡难度、定级结果和未完成测试均保存在浏览器 IndexedDB 中，不会上传到服务器或 GitHub。“备份进度”导出的 JSON 包含完整学习状态及 SHA-256 完整性校验；在另一台设备或网页版点击“导入进度”即可恢复。损坏或被篡改的新版备份会被拒绝。备份默认下载到浏览器下载目录，仓库也会忽略标准备份文件名。

默认词库基于 [ECDICT](https://github.com/skywind3000/ECDICT) 构建。难度先采用 [Oxford 3000/5000](https://www.oxfordlearnersdictionaries.com/us/wordlists/oxford3000-5000)，再用 [CEFR-J 1.5 和 Octanove C1/C2 1.0](https://github.com/openlanguageprofiles/olp-en-cefrj) 补足；只有被 Octanove 明确标为 C2 的词才记录为 Beyond C1，未匹配词保持未定级。C2 定级阶段与定级后的新词均采用约 75% 明确 C2 词和 25% C1 校准/巩固词，未定级词不参与定级测试。中文构词关系优先来自 [engra](https://github.com/eslsoft/engra)，其余可靠来源语言由 [English Wiktionary](https://en.wiktionary.org/) 数据压缩为中文短注；双语例句来自 [Tatoeba](https://tatoeba.org/) 的校对语料。定级结果只用于安排学习范围，不是正式 CEFR 认证。

完整设计、数据管道和验证说明见 [`project.md`](project.md)。
