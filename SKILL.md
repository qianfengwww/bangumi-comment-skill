---
name: bangumi-comment-skill
description: 根据 Bangumi 长日志语料生成更像站内成稿的书籍、番剧、游戏评论/日志；先走通用写作层，再路由到对应领域子 skill。
---

# Bangumi Comment Skill

用于生成 **Bangumi 风格的长日志 / 长评草稿**。

## 何时使用

当用户提到以下任一需求时触发：
- Bangumi / 番组计划 日志
- 长评 / 长日志 / 评论草稿
- 想写动画、书籍、游戏相关的长文评论
- 想把已有观后感 / 读后感 / 通关笔记整理成更像 Bangumi 站内日志的版本

## 主流程

1. 先判断领域：`动画 / 书籍 / 游戏`
2. 先读通用层：`references/general-writing-layer.md`
3. 再路由到对应子 skill：
   - 动画 → `anime-log-comment/SKILL.md`
   - 书籍 → `book-log-comment/SKILL.md`
   - 游戏 → `game-log-comment/SKILL.md`
4. 如果用户已经给了零散笔记，优先保留其核心判断和个人体验，再做结构化重写
5. 如果用户没有给原始体验，只能输出“草稿 / 模板 / 结构建议”，不要伪造亲身体验

## 强制约束

- 不伪造“已看 / 已读 / 已玩”的个人经历
- 不凭空编造剧情细节、章节细节、线路细节或结局体验
- 若素材不足，先补结构，不硬写细节
- 默认输出 Markdown

## 默认交付

- 1 个完整长日志草稿
- 3 个备选标题
- 1 段可选的摘要 / 导语
- 如用户需要，再补：更锐利版 / 更克制版 / 更私密版
