---
name: bangumi-comment-skill
description: 根据 Bangumi 长日志写作规律生成更像站内成稿的书籍、番剧、游戏评论/日志；先走通用写作层，再路由到对应领域子 skill。
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
3. 再路由到对应子 skill：
   - 动画 → `anime-log-comment/SKILL.md`
   - 书籍 → `book-log-comment/SKILL.md`
   - 游戏 → `game-log-comment/SKILL.md`
4. 如果用户给了原始笔记，优先保留其判断、语气与个人体验，再做结构化重写
5. 如果素材不足，只输出“草稿 / 模板 / 结构建议”，不要伪造亲身体验

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

## 当前最小可用参考

- 通用写作层：`references/general-writing-layer.md`
- 动画领域层：`anime-log-comment/references/writing-style.md`
- 书籍领域层：`book-log-comment/references/writing-style.md`
- 游戏领域层：`game-log-comment/references/writing-style.md`

这些规则已经是从 Bangumi 长日志样本中压缩出来的最小可用版本；仓库默认不再跟踪本地语料、样稿和采样脚本。
