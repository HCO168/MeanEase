# MeanEase｜英语词汇学习

一个 local-first 的英语词汇学习工具，内置 20,000 词英汉词库、CEFR 难度参考、中文构词短注、可溯源双语例句、自适应词汇定级、词距复习队列、发音、离线进度备份和可选的 HCONet 手动云存档。

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

20,000 词词典正文由服务器静态 CSV 提供，并在浏览器 IndexedDB 中缓存供学习使用。逐卡调度、设置、每日统计、定级结果和未完成测试默认只保存在当前浏览器。MeanEase 不会自动同步；只有已登录用户在网页版设置中明确点击“保存到云端”时，浏览器才会把发生变化的单词调度字段和少量个人元数据整理成 `meanease_personal_data.csv` 并上传到个人 Drive 应用数据区。静态词典正文不会进入个人云存档。

“从云端恢复”会先明确确认，再以当前服务器静态词库为底，在单个 IndexedDB 事务中覆盖个人学习字段。云端 revision 与本浏览器已知 revision 不一致时，覆盖前还会再次确认，避免另一台设备的存档被静默覆盖。独立启动器的 `http://127.0.0.1:8765` 来源不能读取 HCONet 网站登录 Cookie，因此继续提供完整离线学习与 JSON 备份，但云存档按钮会提示改用网页版。

“备份进度”导出 schema v5 JSON，只包含发生变化的逐词调度字段、设置、统计、定级结果和学习位置，不再包含 20,000 词的词义、音标、例句或其他静态词典正文。备份仍带 SHA-256 完整性校验；在另一台设备或网页版点击“导入进度”即可把个人字段匹配到当地的当前词库。损坏或被篡改的新版备份会被拒绝。导入 schema v2、v3 或 v4 旧备份时，浏览器会在本地提取个人字段、转换为 v5、完成恢复并立即提供转换后文件下载，旧文件不会上传到服务器。

默认词库基于 [ECDICT](https://github.com/skywind3000/ECDICT) 构建。难度先采用 [Oxford 3000/5000](https://www.oxfordlearnersdictionaries.com/us/wordlists/oxford3000-5000)，再用 [CEFR-J 1.5 和 Octanove C1/C2 1.0](https://github.com/openlanguageprofiles/olp-en-cefrj) 补足；只有被 Octanove 明确标为 C2 的词才记录为 Beyond C1，未匹配词保持未定级。C2 定级阶段与定级后的新词均采用约 75% 明确 C2 词和 25% C1 校准/巩固词，未定级词不参与定级测试。中文构词关系优先来自 [engra](https://github.com/eslsoft/engra)，其余可靠来源语言由 [English Wiktionary](https://en.wiktionary.org/) 数据压缩为中文短注；双语例句来自 [Tatoeba](https://tatoeba.org/) 的校对语料。定级结果只用于安排学习范围，不是正式 CEFR 认证。

完整设计、数据管道和验证说明见 [`project.md`](project.md)。
