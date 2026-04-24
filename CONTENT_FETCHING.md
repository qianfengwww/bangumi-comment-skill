# 内容获取指南

本目录下的脚本用于在生成 Bangumi 风格评论/日志前，获取作品相关的剧情、设定、分集/分章/分路线信息。

## 依赖安装

```bash
# EPUB 读取支持（书籍）
pip install ebooklib

# HTML 解析（所有领域）
pip install beautifulsoup4

# HTTP 请求（所有领域）
pip install requests
```

## 动画：先解析条目 ID（可选但推荐）

**脚本**: `scripts/resolve_subject.py`

### 基本用法

```bash
# 从 Bangumi 条目链接提取 subject_id
python scripts/resolve_subject.py --subject-url "https://bgm.tv/subject/51"

# 直接给作品名搜索（返回最佳匹配和候选）
python scripts/resolve_subject.py --query "CLANNAD" --domain anime

# 自动识别输入是 URL 还是标题
python scripts/resolve_subject.py --input "https://bangumi.tv/subject/51"
python scripts/resolve_subject.py --input "CLANNAD"
```

### 输出格式

```json
{
  "query": "CLANNAD",
  "subject_id": 51,
  "match_type": "search",
  "best_match": {
    "id": 51,
    "name": "CLANNAD -クラナド-",
    "name_cn": "CLANNAD",
    "type": 2,
    "date": "2007-10-04",
    "platform": "TV",
    "url": "https://bgm.tv/subject/51"
  },
  "alternatives": [],
  "error": null
}
```

### 使用建议

- 用户只给作品名时，可以先跑一次 resolver 查看候选，也可以直接把标题传给后续脚本
- URL 输入优先直接提取 `subject_id`，避免不必要搜索
- 如果返回 `ambiguous_match`，优先让用户从候选里确认

---

## 动画：获取分集概要

**脚本**: `scripts/fetch_anime_episodes.py`

### 基本用法

```bash
# 获取分集列表（来自 Bangumi API）
python scripts/fetch_anime_episodes.py --subject-id 12345

# 直接给 Bangumi 条目链接
python scripts/fetch_anime_episodes.py --subject-url "https://bgm.tv/subject/51"

# 直接给标题查询（默认按动画条目搜索）
python scripts/fetch_anime_episodes.py --query "CLANNAD"

# 自动识别 URL 或标题
python scripts/fetch_anime_episodes.py --input "https://bangumi.tv/subject/51"
python scripts/fetch_anime_episodes.py --input "CLANNAD"

# 保存到 JSON
python scripts/fetch_anime_episodes.py --subject-id 12345 --output episodes.json

# 抓取网页端详细剧情（更慢，但信息更完整）
python scripts/fetch_anime_episodes.py --subject-id 12345 --fetch-web-detail
```

### 输出格式

```json
{
  "subject_id": 12345,
  "subject": {
    "name": "CLANNAD -クラナド-",
    "name_cn": "CLANNAD",
    "type": 2,
    "url": "https://bgm.tv/subject/51"
  },
  "resolved_via": "query",
  "query": "CLANNAD",
  "subject_summary": "作品整体简介",
  "episodes": [
    {
      "id": 123456,
      "sort": 1,
      "name": "Episode 1",
      "name_cn": "第一话",
      "desc": "分集剧情概要",
      "desc_source": "api",
      "air_date": "2024-01-01",
      "duration": "24:00"
    }
  ]
}
```

### 工作流

1. 从 Bangumi API 获取分集列表
2. （可选）从 Bangumi 网页端抓取详细剧情
3. 输出 JSON 供写作层使用

---

## 书籍：读取 EPUB 内容

**脚本**: `scripts/read_epub.py`

### 基本用法

```bash
# 提取全书内容
python scripts/read_epub.py --input book.epub

# 提取元数据（作者、出版社、简介等）
python scripts/read_epub.py --input book.epub --metadata-only

# 提取指定章节范围
python scripts/read_epub.py --input book.epub --chapters 1-5

# 输出到 Markdown 文件
python scripts/read_epub.py --input book.epub --output book-content.md

# 限制每章最大字符数（避免输出过长）
python scripts/read_epub.py --input book.epub --max-chars 10000
```

### 输出格式

```markdown
# Book Content

## Title: 书名
## Author: 作者
## Language: zh
## Publisher: 出版社
## Date: 2023

## Description

作品简介...

---

## 第一章

第一章内容...

---

## 第二章

第二章内容...
```

### 工作流

1. 用户上传 EPUB 文件
2. 脚本提取元数据（标题、作者、简介等）
3. 逐章提取正文内容（HTML → Markdown）
4. 输出供写作层使用

---

## 游戏：获取剧情信息

**脚本**: `scripts/fetch_game_plot.py`

### 基本用法

```bash
# 获取基础信息
python scripts/fetch_game_plot.py --subject-id 12345

# 直接给 Bangumi 条目链接
python scripts/fetch_game_plot.py --subject-url "https://bgm.tv/subject/12345"

# 直接给标题查询（默认按游戏条目搜索）
python scripts/fetch_game_plot.py --query "沙耶之歌"

# 保存到 JSON
python scripts/fetch_game_plot.py --subject-id 12345 --output game-info.json

# 包含补充材料的引导说明
python scripts/fetch_game_plot.py --subject-id 12345 --include-guidance
```

### 输出格式

```json
{
  "subject_id": 12345,
  "subject": {
    "name": "沙耶の唄",
    "name_cn": "沙耶之歌",
    "type": 4,
    "url": "https://bgm.tv/subject/12345"
  },
  "resolved_via": "query",
  "query": "沙耶之歌",
  "plot_info": {
    "title": "游戏名称",
    "title_cn": "中文译名",
    "summary": "剧情简介",
    "platform": "PC",
    "developer": "开发商",
    "publisher": "发行商",
    "release_date": "2024-01-01",
    "genre_tags": ["RPG", "冒险"],
    "characters": ["角色 1", "角色 2"],
    "plot_keywords": ["关键词"]
  },
  "guidance": "补充材料的获取建议"
}
```

### 限制说明

Bangumi API 和网页端只提供：
- ✅ 基础信息（标题、平台、开发商、发售日期）
- ✅ 剧情简介（通常较短）
- ✅ 角色列表（部分条目）
- ❌ 详细剧情流程
- ❌ 选项分支信息
- ❌ 多结局详情

**需要详细剧情时，建议补充以下材料之一：**
1. 游戏脚本/剧情文本文件
2. 相关 Wiki 页面链接
3. 剧情解说视频链接（可转译）
4. 用户自己的游玩笔记

---

## 通用：爬取用户给定的网站

**脚本**: `scripts/fetch_web_content.py`

### 适用场景

- 用户提供了作品相关的网站链接（书评网、豆瓣、维基、Fandom、攻略站等）
- 需要从网页提取剧情、设定、角色信息
- 三个领域（动画/书籍/游戏）通用

### 基本用法

```bash
# 爬取单个网页
python scripts/fetch_web_content.py --url "https://example.com/review"

# 爬取多个网页
python scripts/fetch_web_content.py --url "https://a.com" --url "https://b.com"

# 保存到 Markdown
python scripts/fetch_web_content.py --url "https://example.com" --output content.md

# 只提取正文（去除导航、广告等噪音）
python scripts/fetch_web_content.py --url "https://example.com" --extract-body

# 限制最大字符数
python scripts/fetch_web_content.py --url "https://example.com" --max-chars 20000
```

### 输出格式

```markdown
# Web Content

## Source: https://example.com/review
## Fetched: 2024-01-15 10:30:00

### Title: 网页标题

正文内容...

---

## Source: https://another.com/plot
## Fetched: 2024-01-15 10:30:05

### Title: 另一个网页标题

正文内容...
```

### 工作流

1. 用户提供 URL 列表
2. 脚本依次抓取每个页面
3. 使用 Playwright 渲染（支持 SPA）
4. 提取正文内容（自动去除导航、广告）
5. 输出 Markdown 供写作层使用

---

## 通用：抓取 Bangumi 其他用户长评

**脚本**: `scripts/fetch_bangumi_logs.py`

### 适用场景

- 用户要求"参考站内其他用户的评论"
- 需要完善剧情框架、角色分析、主题解读
- 三个领域（动画/书籍/游戏）通用

### 基本用法

```bash
# 抓取某作品的用户长评
python scripts/fetch_bangumi_logs.py --subject-id 12345

# 直接给 Bangumi 条目链接
python scripts/fetch_bangumi_logs.py --subject-url "https://bgm.tv/subject/51"

# 直接给标题查询，并用 --subject-type 辅助限定领域
python scripts/fetch_bangumi_logs.py --query "CLANNAD" --subject-type anime

# 限制抓取数量
python scripts/fetch_bangumi_logs.py --subject-id 12345 --limit 10

# 只抓取长评（超过 500 字）
python scripts/fetch_bangumi_logs.py --subject-id 12345 --min-length 500

# 保存到 JSON
python scripts/fetch_bangumi_logs.py --subject-id 12345 --output logs.json

# 输出为 Markdown（便于阅读）
python scripts/fetch_bangumi_logs.py --subject-id 12345 --output logs.md
```

### 输出格式

```json
{
  "subject_id": 12345,
  "subject": {
    "name": "CLANNAD -クラナド-",
    "name_cn": "CLANNAD",
    "date": "2007-10-04"
  },
  "entries": [
    {
      "kind": "review",
      "author": "用户名",
      "rating": 8,
      "date": "2024-01-10",
      "content": "长评内容...",
      "word_count": 1200,
      "url": "https://bgm.tv/review/123456"
    }
  ]
}
```

### 工作流

1. 从 Bangumi 作品页抓取用户评论列表
2. 过滤出长评（默认 >500 字）
3. 提取评论内容、评分、时间、标签
4. 输出 JSON/Markdown 供写作层参考

### 使用建议

- **剧情框架**：参考多篇长评中的剧情梳理部分
- **角色分析**：提取不同用户对同一角色的解读
- **主题解读**：汇总多篇长评的主题分析角度
- **避免雷同**：参考但不照搬，保持独立判断

---

## 集成到写作流程

### 动画评论流程

```bash
# 1. 获取分集信息
python scripts/fetch_anime_episodes.py --query "CLANNAD" --output episodes.json

# 2. （可选）抓取站内长评参考
python scripts/fetch_bangumi_logs.py --query "CLANNAD" --subject-type anime --output logs.json

# 3. （可选）爬取外部网站
python scripts/fetch_web_content.py --url "https://example.com/review" --output web-content.md

# 4. 调用写作层（传入所有素材）
# （由主 skill 自动处理）
```

### 书籍评论流程

```bash
# 方案 A：用户上传 EPUB
python scripts/read_epub.py --input book.epub --output book-content.md

# 方案 B：用户提供网站链接
python scripts/fetch_web_content.py --url "https://example.com/review" --output web-content.md

# （可选）抓取站内长评参考
python scripts/fetch_bangumi_logs.py --query "三体" --subject-type book --output logs.json

# 调用写作层
# （由主 skill 自动处理）
```

### 游戏评论流程

```bash
# 1. 获取基础信息
python scripts/fetch_game_plot.py --query "沙耶之歌" --output game-info.json

# 2. （可选）爬取攻略站/Wiki
python scripts/fetch_web_content.py --url "https://wiki.example.com/game" --output wiki-content.md

# 3. （可选）抓取站内长评参考
python scripts/fetch_bangumi_logs.py --query "沙耶之歌" --subject-type game --output logs.json

# 4. 如需要详细剧情，引导用户补充材料
# 5. 调用写作层
# （由主 skill 自动处理）
```

---

## 注意事项

1. **API 限制**：Bangumi API 有请求频率限制，批量获取时注意间隔
2. **网页抓取**：`--fetch-web-detail` 模式较慢，建议仅在需要详细剧情时使用
3. **EPUB 版权**：仅处理用户拥有合法使用权的 EPUB 文件
4. **游戏剧情**：Bangumi 不提供完整剧情，需额外来源补充
5. **网站爬取**：遵守目标网站的 robots.txt 和使用条款
6. **长评参考**：参考但不照搬，保持独立判断和原创性
