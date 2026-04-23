---
name: bangumi-comment-skill
description: 根据 Bangumi 长日志语料生成更像站内成稿的书籍、番剧、游戏评论/日志；先走通用写作层，再路由到对应领域子 skill。
---

# Bangumi Comment Skill

用于生成更像 **Bangumi 站内长日志 / 长评成稿** 的文本，而不是公众号稿、平台运营稿或空泛书评。

## 何时使用

当用户提到以下任一需求时触发：
- Bangumi / 番组计划 日志
- 动画 / 书籍 / 游戏 长评
- 读后感 / 观后感 / 通关感想重写
- 想把零散感受整理成更像站内成稿的版本
- 想模仿 Bangumi 用户日志的结构、语气和段落推进

## 主流程

1. 先判断领域：`动画 / 书籍 / 游戏`
2. 先读通用层：`references/general-writing-layer.md`
3. 再读对应领域总结：
   - 动画样本总结：`data/anime/summary.md`
   - 书籍样本总结：`data/book/summary.md`
   - 游戏样本总结：`data/game/summary.md`
4. 路由到对应子 skill：
   - 动画 → `anime-log-comment/SKILL.md`
   - 书籍 → `book-log-comment/SKILL.md`
   - 游戏 → `game-log-comment/SKILL.md`
5. 如果用户给了原始笔记，优先保留其判断、语气与个人体验，再做结构化重写
6. 如果素材不足，只输出“草稿 / 模板 / 结构建议”，不要伪造亲身体验

## 默认交付

- 1 篇完整长日志草稿
- 3 个备选标题
- 1 段可选导语 / 摘要
- 如用户需要，再补：更锐利版 / 更克制版 / 更私密版

## 强制约束

- 不伪造“已看 / 已读 / 已玩”的个人经历
- 不凭空编造剧情细节、章节细节、路线细节、结局体验
- 不把内容写成营销文、平台种草文、公众号口播稿
- 默认输出 Markdown
- 开头优先给判断、感受或问题，不先堆百科背景

## 当前项目内参考

- 通用写作层：`references/general-writing-layer.md`
- 动画领域层：`anime-log-comment/references/writing-style.md`
- 书籍领域层：`book-log-comment/references/writing-style.md`
- 游戏领域层：`game-log-comment/references/writing-style.md`
- 动画基础样稿：`examples/anime-base-article.md`
- 书籍基础样稿：`examples/book-base-article.md`
- 游戏基础样稿：`examples/game-base-article.md`

## 语料说明

当前仓库已沉淀一批符合以下条件的 Bangumi 长日志样本：
- 正文字数 > 800
- 段落数 > 3
- 三个领域合计 300 篇

这些样本只保存结构化元数据与必要摘录，不保存整篇全文。
