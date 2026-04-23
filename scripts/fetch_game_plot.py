#!/usr/bin/env python3
"""
Fetch game plot information from Bangumi API and subject page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from script_http import HttpClient, RequestError, get_logger, setup_logging


BANGUMI_API_BASE = "https://api.bgm.tv/v0"
BANGUMI_WEB_BASE = "https://bgm.tv/subject"
LOGGER = get_logger("fetch_game_plot")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_infobox_key(key: str) -> str:
    normalized = normalize_space(key).strip().strip(":：")
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = re.sub(r"[\s_/·,，;；|]+", "", normalized)
    return normalized.casefold()


def classify_infobox_key(key: str) -> str | None:
    normalized = normalize_infobox_key(key)
    aliases = {
        "developer": {
            "开发",
            "开发商",
            "开发公司",
            "开发团队",
            "开发者",
            "制作",
            "制作公司",
            "制作商",
            "制作团队",
            "developer",
            "developers",
            "developedby",
            "developerstudio",
            "devstudio",
            "studio",
        },
        "publisher": {
            "发行",
            "发行商",
            "发行公司",
            "发行商/代理商",
            "代理发行",
            "出版",
            "出版商",
            "publisher",
            "publishers",
            "publishedby",
        },
        "release_date": {
            "发售日",
            "发售日期",
            "发行日",
            "发行日期",
            "上市日",
            "上市日期",
            "首发日期",
            "release",
            "released",
            "releasedate",
            "dateofrelease",
            "launchdate",
            "publicationdate",
        },
        "genre": {
            "类型",
            "作品类型",
            "游戏类型",
            "题材",
            "genre",
            "genres",
            "type",
            "category",
        },
    }
    for field, names in aliases.items():
        if normalized in names:
            return field
    return None


def flatten_infobox_value(value: object) -> str:
    if isinstance(value, list):
        parts = [str(entry.get("v", "")).strip() for entry in value if isinstance(entry, dict) and entry.get("v")]
        return ", ".join(part for part in parts if part)
    return str(value).strip()


def split_genre_values(value: str) -> list[str]:
    parts = re.split(r"\s*[,/、|｜；;]\s*", value)
    return [part.strip() for part in parts if part.strip()]


def parse_infobox_list(soup: BeautifulSoup) -> dict[str, str]:
    infobox: dict[str, str] = {}
    info_box = soup.select_one("#infobox")
    if not info_box:
        return infobox
    for item in info_box.select("li"):
        key_node = item.select_one("span.tip")
        key = normalize_space(key_node.get_text(" ", strip=True).rstrip(":")) if key_node else ""
        value = normalize_space(item.get_text(" ", strip=True))
        if key:
            value = normalize_space(value.removeprefix(key_node.get_text(" ", strip=True)))
            if value:
                infobox[key] = value
    return infobox


def fetch_subject_from_api(client: HttpClient, subject_id: int) -> dict | None:
    url = f"{BANGUMI_API_BASE}/subjects/{subject_id}"
    try:
        return client.get_json(url)
    except RequestError as exc:
        LOGGER.warning("API 请求失败: %s", exc)
        return None


def fetch_subject_from_web(client: HttpClient, subject_id: int) -> dict:
    url = f"{BANGUMI_WEB_BASE}/{subject_id}"
    result = {"summary": "", "infobox": {}, "plot_keywords": [], "characters": []}
    try:
        html = client.get_text(url)
    except RequestError as exc:
        LOGGER.warning("网页抓取失败: %s", exc)
        return result

    soup = BeautifulSoup(html, "html.parser")
    summary_div = soup.select_one("#subject_summary, #summary, .subject_summary")
    if summary_div:
        result["summary"] = normalize_space(summary_div.get_text("\n", strip=True))

    result["infobox"] = parse_infobox_list(soup)

    tags = []
    for node in soup.select(".subject_tag_section a.l, .tags a.l, .subject_tag_section a"):
        text = normalize_space(node.get_text(" ", strip=True))
        if text and text not in tags:
            tags.append(text)
    result["plot_keywords"] = tags

    characters = []
    for node in soup.select("#browserItemList li a.avatar, #columnInSubjectA .browserCoverMedium"):
        name = normalize_space(node.get("title", "") or node.get_text(" ", strip=True))
        if name and name not in characters:
            characters.append(name)
    result["characters"] = characters
    return result


def extract_plot_elements(api_data: dict | None, web_data: dict) -> dict:
    plot_info = {
        "title": "",
        "title_cn": "",
        "summary": "",
        "platform": "",
        "developer": "",
        "publisher": "",
        "release_date": "",
        "genre_tags": [],
        "characters": [],
        "plot_keywords": [],
        "additional_notes": [],
    }

    if api_data:
        plot_info["title"] = api_data.get("name", "")
        plot_info["title_cn"] = api_data.get("name_cn", "")
        plot_info["summary"] = api_data.get("summary", "")

        platform = api_data.get("platform", {})
        if isinstance(platform, dict):
            plot_info["platform"] = platform.get("name", "")
        elif isinstance(platform, str):
            plot_info["platform"] = platform

        for item in api_data.get("infobox", []):
            key = str(item.get("key", ""))
            value = flatten_infobox_value(item.get("value", ""))
            field = classify_infobox_key(key)
            if field == "developer":
                plot_info["developer"] = value
            elif field == "publisher":
                plot_info["publisher"] = value
            elif field == "release_date":
                plot_info["release_date"] = value
            elif field == "genre":
                plot_info["genre_tags"].extend(split_genre_values(value))

    if web_data.get("summary") and len(web_data["summary"]) > len(plot_info["summary"]):
        plot_info["summary"] = web_data["summary"]

    plot_info["characters"] = web_data.get("characters", [])
    plot_info["plot_keywords"] = web_data.get("plot_keywords", [])

    for key, value in web_data.get("infobox", {}).items():
        field = classify_infobox_key(key)
        if field == "developer" and not plot_info["developer"]:
            plot_info["developer"] = value
        elif field == "publisher" and not plot_info["publisher"]:
            plot_info["publisher"] = value
        elif field == "release_date" and not plot_info["release_date"]:
            plot_info["release_date"] = value
        elif field == "genre":
            plot_info["genre_tags"].extend(split_genre_values(value))

    plot_info["genre_tags"] = sorted(set(plot_info["genre_tags"]))
    plot_info["plot_keywords"] = sorted(set(plot_info["plot_keywords"]))
    if not plot_info["summary"]:
        plot_info["additional_notes"].append("Bangumi 未提供可用剧情简介，可能需要补充外部材料。")
    if not plot_info["characters"]:
        plot_info["additional_notes"].append("网页未提取到角色列表。")
    return plot_info


def generate_plot_guidance(plot_info: dict) -> str:
    guidance = []
    guidance.append("## 剧情信息获取说明\n")
    guidance.append("Bangumi API 和网页端通常只提供基础信息与简介，详细剧情仍建议补充外部材料。\n")
    guidance.append("### 推荐来源\n")
    guidance.append("1. 用户上传材料：游戏脚本、剧情文档、Wiki 链接")
    guidance.append("2. 官方 Wiki / Fandom")
    guidance.append("3. 攻略站或设定资料页")
    guidance.append("4. 视频剧情解说（需自行转写）\n")
    guidance.append("### 当前已获取的信息\n")
    guidance.append(f"- 标题：{plot_info['title_cn'] or plot_info['title'] or '未知'}")
    guidance.append(f"- 平台：{plot_info['platform'] or '未知'}")
    guidance.append(f"- 开发商：{plot_info['developer'] or '未知'}")
    guidance.append(f"- 发行商：{plot_info['publisher'] or '未知'}")
    guidance.append(f"- 发售日期：{plot_info['release_date'] or '未知'}")
    guidance.append(f"- 类型标签：{', '.join(plot_info['genre_tags']) or '无'}")
    guidance.append(f"- 角色：{', '.join(plot_info['characters'][:10]) or '未知'}\n")
    guidance.append("### 剧情简介（来自 Bangumi）\n")
    guidance.append(plot_info["summary"] or "暂无简介")
    return "\n".join(guidance)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch game plot information")
    parser.add_argument("--subject-id", type=int, required=True, help="Bangumi subject ID")
    parser.add_argument("--output", type=str, help="Output JSON file path")
    parser.add_argument("--include-guidance", action="store_true", help="Include guidance for additional materials")
    parser.add_argument("--cache-dir", default=".cache/bangumi-game-plot", help="GET response cache directory")
    parser.add_argument("--cache-ttl", type=int, default=24 * 3600, help="Cache TTL in seconds")
    parser.add_argument("--timeout", type=int, default=30, help="Read timeout in seconds")
    parser.add_argument("--min-interval", type=float, default=0.8, help="Minimum interval between requests")
    return parser


def main() -> int:
    setup_logging()
    args = build_parser().parse_args()

    client = HttpClient(
        timeout=(10.0, float(args.timeout)),
        min_interval=args.min_interval,
        cache_dir=Path(args.cache_dir),
        cache_ttl_seconds=args.cache_ttl,
        logger=LOGGER,
    )

    LOGGER.info("fetching game info for subject %s", args.subject_id)
    api_data = fetch_subject_from_api(client, args.subject_id)
    if not api_data:
        LOGGER.error("Bangumi API 返回为空，无法继续")
        return 2

    web_data = fetch_subject_from_web(client, args.subject_id)
    plot_info = extract_plot_elements(api_data, web_data)
    result = {
        "subject_id": args.subject_id,
        "plot_info": plot_info,
        "data_sources": {
            "api": api_data is not None,
            "web": bool(web_data.get("summary") or web_data.get("characters") or web_data.get("infobox")),
        },
    }
    if args.include_guidance:
        result["guidance"] = generate_plot_guidance(plot_info)

    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        LOGGER.info("output written to %s", args.output)
        if args.include_guidance:
            print(result["guidance"])
        return 0

    sys.stdout.write(output)
    if args.include_guidance:
        sys.stdout.write("\n" + result["guidance"] + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
