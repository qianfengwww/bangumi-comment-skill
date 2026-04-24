---
name: bangumi-comment-skill
description: 根据 Bangumi 长日志写作规律生成更像站内成稿的书籍、番剧、游戏评论/日志；支持先查剧情、设定、章节/路线信息，再写剧情向文字、分析和长评草稿。
---

# Bangumi Comment Skill

用于生成更像 **Bangumi 站内长日志 / 长评成稿** 的文本，而不是公众号稿、平台运营稿或空泛书评。

## 触发条件

用户提到以下任一需求时直接使用：

- 写 Bangumi 日志（动画 / 书籍 / 游戏）
- 把零散观感整理成站内长文
- 先查剧情 / 设定 / 章节 / 路线，再写分析
- 写剧情梳理、角色线分析、单集 / 单卷 / 单章 / 单路线感想
- 模仿 Bangumi 用户的结构和语气

## 主流程

1. 判断领域：动画 / 书籍 / 游戏
2. 确认素材来源：
   - 用户给了笔记 / 摘录 / 剧情点 → 优先用用户的
   - 用户只给作品名 → 可直接传给下游抓取脚本；若需要候选确认，再调用 `scripts/resolve_subject.py`
   - 用户给了 Bangumi 条目链接 → 可直接传给下游抓取脚本；也可先调用 `scripts/resolve_subject.py` 单独提取 `subject_id`
   - 用户给了网站链接 → 调用 `scripts/fetch_web_content.py` 爬取
   - 用户要求参考站内评论 → 调用 `scripts/fetch_bangumi_logs.py` 抓取其他用户长评
3. **内容获取**：
   - **动画** → `scripts/fetch_anime_episodes.py` 查分集概要，支持 `--subject-id` / `--subject-url` / `--query` / `--input`
   - **书籍** → 优先用 `scripts/collect_book_materials.py` 统一处理 EPUB / 普通 URL / Bangumi 标题或条目 URL；仅在明确只需要单一来源时，再回退到 `scripts/read_epub.py` 或 `scripts/fetch_web_content.py`
   - **游戏** → `scripts/fetch_game_plot.py` 查基础信息 + 引导用户补充，支持 `--subject-id` / `--subject-url` / `--query` / `--input`
   - **通用** → `scripts/fetch_bangumi_logs.py` 抓取 Bangumi 其他用户的长评作为参考，支持 `--subject-id` / `--subject-url` / `--query` / `--input`
4. 读通用层：`references/general-writing-layer.md`
5. 路由到对应子 skill：
   - 动画 → `anime-log-comment/SKILL.md`
   - 书籍 → `book-log-comment/SKILL.md`
   - 游戏 → `game-log-comment/SKILL.md`
5. 素材不足时：
   - 可写“剧情整理 / 结构化草稿 / 简介级分析”
   - 不伪造完整观后感 / 读后感 / 通关感

## 输出类型

- 长日志草稿
- 剧情梳理 / 角色关系分析
- 单集 / 单卷 / 单章 / 单路线分析
- 基于剧情的主题分析

## 交付内容

- 1 篇完整正文
- 3 个备选标题
- 视情况补充：
  - 剧情摘要版
  - 分章节 / 分路线提纲
  - 更分析向或更剧情向的版本

## 强制约束

- 不伪造“已看 / 已读 / 已玩”的个人经历
- 可引用公开剧情 / 设定，但不把猜测当事实
- 只有简介级素材时，只写简介级分析
- 不写营销文、种草文、公众号口播稿
- 默认输出 Markdown
- 开头直接给判断 / 感受 / 剧情切口，不堆百科背景

## 参考文件

- 通用写作层：`references/general-writing-layer.md`
- 动画领域层：`anime-log-comment/references/writing-style.md`
- 书籍领域层：`book-log-comment/references/writing-style.md`
- 游戏领域层：`game-log-comment/references/writing-style.md`

## 书籍入口建议

- 用户给 EPUB / 书籍网页 / Bangumi 标题 / Bangumi 书籍条目 URL 的任意组合时，优先运行 `scripts/collect_book_materials.py`
- 标题搜索若返回歧义候选，先看脚本输出里的 `subject_resolution.alternatives`，必要时再让用户确认具体 `subject_id`
- 只有在用户明确只要“读 EPUB”或“抓单个网页”时，才直接调用单功能脚本

以上规则来自对 Bangumi 长日志样本的压缩；仓库默认不跟踪本地语料、样稿和采样脚本。
