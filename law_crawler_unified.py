#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import base64
import csv
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SAFE_CHAR_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
EM_TAG_RE = re.compile(r"</?em[^>]*>", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")


NPC_DEFAULT_CATEGORIES = ["法律", "行政法规", "司法解释", "地方法规"]
TREATY_DEFAULT_COLLECTIONS = ["全部", "双边", "多边"]
GOV_RULE_DEFAULT_CATEGORIES = ["部门规章", "地方政府规章"]
NPC_CATEGORY_ALIASES = {
    "地方性法规": "地方法规",
    "地方法规": "地方法规",
}


@dataclass
class CrawlOptions:
    output_root: Path
    download_files: bool
    max_pages: int | None
    max_items: int | None
    npc_page_size: int
    gov_page_size: int
    timeout: int


def sanitize_filename(name: str, fallback: str = "unnamed") -> str:
    name = SAFE_CHAR_RE.sub("_", name).strip().rstrip(".")
    return name or fallback


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join(clean_text(item) for item in value if clean_text(item))
    text = str(value)
    text = EM_TAG_RE.sub("", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text


def decode_filename_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("response-content-disposition")
    if not values:
        return None
    disposition = values[0]
    match = re.search(r'filename="([^"]+)"', disposition, re.IGNORECASE)
    if not match:
        return None
    filename = match.group(1)
    try:
        filename = unquote(unquote(filename))
    except Exception:
        filename = unquote(filename)
    return sanitize_filename(filename)


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem}__{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def extract_year(value: str) -> str:
    match = re.search(r"(\d{4})", clean_text(value))
    return match.group(1) if match else "未知"


def count_existing_files(paths: Iterable[str], base_dir: Path) -> int:
    total = 0
    for item in paths:
        if item and (base_dir / item).exists():
            total += 1
    return total


def summarize_top(counter: Counter, limit: int = 15) -> list[dict]:
    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]


def render_simple_markdown_report(title: str, sections: list[tuple[str, dict | list[dict] | list[str] | str]]) -> str:
    lines = [f"# {title}", ""]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.extend([f"生成时间：{generated_at}", ""])
    for heading, payload in sections:
        lines.append(f"## {heading}")
        if isinstance(payload, str):
            lines.extend([payload, ""])
            continue
        if isinstance(payload, dict):
            for key, value in payload.items():
                lines.append(f"- {key}: {value}")
            lines.append("")
            continue
        if isinstance(payload, list):
            if payload and isinstance(payload[0], dict):
                for row in payload:
                    name = row.get("name", "")
                    count = row.get("count", "")
                    extra = row.get("extra", "")
                    text = f"- {name}: {count}"
                    if extra:
                        text += f" ({extra})"
                    lines.append(text)
            else:
                for row in payload:
                    lines.append(f"- {row}")
            lines.append("")
            continue
    return "\n".join(lines).rstrip() + "\n"


class HttpClient:
    def __init__(self, timeout: int) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=5,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def get(self, url: str, **kwargs) -> requests.Response:
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response

    def post(self, url: str, **kwargs) -> requests.Response:
        response = self.session.post(url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response


class BaseCrawler:
    source_name = "base"

    def __init__(self, options: CrawlOptions, logger: logging.Logger) -> None:
        self.options = options
        self.logger = logger
        self.client = HttpClient(timeout=options.timeout)
        self.source_root = ensure_dir(options.output_root / self.source_name)

    def crawl(self) -> dict:
        raise NotImplementedError

    def limit_reached(self, rows: list[dict]) -> bool:
        return self.options.max_items is not None and len(rows) >= self.options.max_items

    def apply_item_limit(self, rows: list[dict]) -> list[dict]:
        if self.options.max_items is None:
            return rows
        return rows[: self.options.max_items]


class NpcCrawler(BaseCrawler):
    source_name = "npc"
    base_url = "https://flk.npc.gov.cn"

    def __init__(
        self,
        options: CrawlOptions,
        logger: logging.Logger,
        categories: list[str] | None,
        incremental: bool = False,
        baseline_dir: Path | None = None,
        download_new_only: bool = False,
    ) -> None:
        super().__init__(options, logger)
        self.request_headers = {"Content-Type": "application/json;charset=utf-8"}
        selected_categories = categories or NPC_DEFAULT_CATEGORIES
        self.selected_categories = [self.normalize_category_name(name) for name in selected_categories]
        self.incremental = incremental
        self.baseline_dir = baseline_dir
        self.download_new_only = download_new_only
        self.known_bbbs: set[str] = set()

    def normalize_category_name(self, name: str) -> str:
        normalized = clean_text(name)
        return NPC_CATEGORY_ALIASES.get(normalized, normalized)

    def load_known_bbbs(self) -> set[str]:
        candidates: list[Path] = []
        if self.baseline_dir:
            candidates.append(self.baseline_dir.expanduser().resolve())
        if self.source_root.exists():
            candidates.append(self.source_root)

        known: set[str] = set()
        visited: set[Path] = set()
        for candidate in candidates:
            if candidate in visited or not candidate.exists():
                continue
            visited.add(candidate)
            search_root = candidate / "npc" if candidate.name != "npc" and (candidate / "npc").exists() else candidate
            for path in search_root.rglob("metadata.jsonl"):
                for row in read_jsonl(path):
                    bbbs = clean_text(row.get("bbbs"))
                    if bbbs:
                        known.add(bbbs)
        return known

    def fetch_category_map(self) -> dict[str, list[int]]:
        response = self.client.get(f"{self.base_url}/law-search/search/enumData")
        data = response.json()["data"]["flfgfl"]["children"]
        mapping: dict[str, list[int]] = {}
        for node in data:
            mapping[node["name"]] = [code for code in node.get("codeIdList", []) if code is not None]
        return mapping

    def search_page(self, codes: list[int], page_num: int) -> dict:
        payload = {
            "searchRange": 1,
            "sxrq": [],
            "gbrq": [],
            "searchType": 2,
            "sxx": [],
            "gbrqYear": [],
            "flfgCodeId": codes,
            "zdjgCodeId": [],
            "searchContent": "",
            "orderByParam": {"order": "-1", "sort": ""},
            "pageNum": page_num,
            "pageSize": self.options.npc_page_size,
        }
        response = self.client.post(
            f"{self.base_url}/law-search/search/list",
            json=payload,
            headers=self.request_headers,
        )
        data = response.json()
        if data.get("code") != 200:
            raise RuntimeError(f"NPC search failed: {data}")
        return data

    def export_directory(self, bbbs_list: list[str], output_path: Path) -> None:
        response = self.client.post(
            f"{self.base_url}/law-search/download/excel",
            json=bbbs_list,
            headers=self.request_headers,
        )
        output_path.write_bytes(response.content)

    def batch_urls(self, bbbs_list: list[str]) -> list[dict]:
        payload = [{"bbbs": bbbs, "format": "docx"} for bbbs in bbbs_list]
        response = self.client.post(
            f"{self.base_url}/law-search/download/batch",
            json=payload,
            headers=self.request_headers,
        )
        data = response.json()
        if data.get("code") != 200:
            raise RuntimeError(f"NPC batch download failed: {data}")
        return data["data"]

    def download_npc_file(self, url: str, target_path: Path) -> Path:
        response = self.client.get(url, stream=True)
        path = unique_path(target_path)
        with path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    fh.write(chunk)
        return path

    def build_category_stats(self, category_name: str, records: list[dict], category_root: Path) -> dict:
        publish_years = Counter(extract_year(row.get("publish_date", "")) for row in records)
        effective_years = Counter(extract_year(row.get("effective_date", "")) for row in records)
        issuer_counts = Counter(clean_text(row.get("issuer")) or "未知" for row in records)
        status_counts = Counter(clean_text(row.get("status_code")) or "未知" for row in records)
        ext_counts = Counter()
        for row in records:
            downloaded_file = row.get("downloaded_file", "")
            if downloaded_file:
                ext = Path(downloaded_file).suffix.lower() or "[none]"
                ext_counts[ext] += 1
        stats = {
            "source": "npc",
            "category": category_name,
            "record_count": len(records),
            "new_record_count": sum(1 for row in records if row.get("is_new")),
            "known_record_count": sum(1 for row in records if row.get("is_known")),
            "downloaded_file_count": sum(1 for row in records if row.get("downloaded_file")),
            "publish_years": dict(sorted(publish_years.items())),
            "effective_years": dict(sorted(effective_years.items())),
            "top_issuers": summarize_top(issuer_counts),
            "status_counts": dict(sorted(status_counts.items())),
            "download_file_extensions": dict(sorted(ext_counts.items())),
        }
        write_json(category_root / "stats_report.json", stats)
        markdown = render_simple_markdown_report(
            f"NPC 分类统计报告 - {category_name}",
            [
                (
                    "概览",
                    {
                        "source": "npc",
                        "category": category_name,
                        "record_count": stats["record_count"],
                        "new_record_count": stats["new_record_count"],
                        "known_record_count": stats["known_record_count"],
                        "downloaded_file_count": stats["downloaded_file_count"],
                    },
                ),
                ("发布年份分布", stats["publish_years"]),
                ("施行年份分布", stats["effective_years"]),
                ("状态分布", stats["status_counts"]),
                ("下载文件扩展名", stats["download_file_extensions"]),
                ("发文机关 Top 15", stats["top_issuers"]),
            ],
        )
        write_text(category_root / "stats_report.md", markdown)
        return stats

    def crawl_category(self, category_name: str, codes: list[int]) -> dict:
        category_root = ensure_dir(self.source_root / sanitize_filename(category_name, category_name))
        files_dir = ensure_dir(category_root / "files")
        records: list[dict] = []

        self.logger.info("NPC: 开始抓取 %s", category_name)
        page_num = 1
        total = None
        while True:
            if self.options.max_pages is not None and page_num > self.options.max_pages:
                break
            page = self.search_page(codes, page_num)
            rows = page.get("rows", [])
            if total is None:
                total = page.get("total", len(rows))
                self.logger.info("NPC: %s 总量 %s", category_name, total)
            if not rows:
                break
            for row in rows:
                record = {
                    "source": "npc",
                    "category": category_name,
                    "bbbs": row.get("bbbs", ""),
                    "title": clean_text(row.get("title")),
                    "issuer": clean_text(row.get("zdjgName")),
                    "issuer_code": row.get("zdjgCodeId"),
                    "category_code": row.get("flfgCodeId"),
                    "law_nature": clean_text(row.get("flxz")),
                    "publish_date": clean_text(row.get("gbrq")),
                    "effective_date": clean_text(row.get("sxrq")),
                    "status_code": row.get("sxx"),
                    "detail_url": "",
                    "downloaded_file": "",
                    "is_known": False,
                    "is_new": True,
                }
                if self.incremental:
                    record["is_known"] = record["bbbs"] in self.known_bbbs
                    record["is_new"] = not record["is_known"]
                records.append(record)
                if self.limit_reached(records):
                    break
            if self.limit_reached(records):
                break
            if len(records) >= (total or 0):
                break
            page_num += 1

        records = self.apply_item_limit(records)
        new_records = [record for record in records if record.get("is_new")]
        download_records = records
        if self.incremental and self.download_new_only:
            download_records = new_records
        bbbs_list = [record["bbbs"] for record in download_records if record["bbbs"]]

        if self.options.download_files and bbbs_list:
            self.logger.info("NPC: 导出 %s 目录文件", category_name)
            export_name = f"{category_name}_文件目录.xlsx"
            if self.incremental and self.download_new_only:
                export_name = f"{category_name}_增量文件目录.xlsx"
            self.export_directory(bbbs_list, category_root / export_name)
            batch_size = 100
            for start in range(0, len(download_records), batch_size):
                chunk = download_records[start : start + batch_size]
                url_items = self.batch_urls([item["bbbs"] for item in chunk])
                if len(url_items) != len(chunk):
                    raise RuntimeError(f"NPC: {category_name} batch return count mismatch")
                for record, item in zip(chunk, url_items):
                    url = item["url"]
                    filename = decode_filename_from_url(url) or sanitize_filename(
                        f"{record['title']}_{record['bbbs']}.docx"
                    )
                    saved_path = self.download_npc_file(url, files_dir / filename)
                    record["downloaded_file"] = str(saved_path.relative_to(category_root))

        write_jsonl(category_root / "metadata.jsonl", records)
        write_csv(category_root / "metadata.csv", records)
        write_jsonl(category_root / "new_items.jsonl", new_records)
        write_csv(category_root / "new_items.csv", new_records)
        stats = self.build_category_stats(category_name, records, category_root)
        write_json(
            category_root / "summary.json",
            {
                "source": "npc",
                "category": category_name,
                "count": len(records),
                "new_count": len(new_records),
                "download_target_count": len(download_records),
            },
        )
        return {
            "category": category_name,
            "count": len(records),
            "new_count": len(new_records),
            "path": str(category_root),
            "stats_report": str(category_root / "stats_report.json"),
        }

    def crawl(self) -> dict:
        category_map = self.fetch_category_map()
        missing = [name for name in self.selected_categories if name not in category_map]
        if missing:
            raise ValueError(f"NPC 不支持这些分类: {missing}")
        if self.incremental:
            self.known_bbbs = self.load_known_bbbs()
            self.logger.info("NPC: 已加载历史标识 %s 条", len(self.known_bbbs))
        results = []
        category_stats = []
        for category in self.selected_categories:
            result = self.crawl_category(category, category_map[category])
            results.append(result)
            stats_path = Path(result["stats_report"])
            category_stats.append(json.loads(stats_path.read_text(encoding="utf-8")))

        source_stats = {
            "source": "npc",
            "incremental": self.incremental,
            "baseline_dir": str(self.baseline_dir) if self.baseline_dir else "",
            "known_bbbs_count": len(self.known_bbbs),
            "selected_categories": self.selected_categories,
            "total_records": sum(item["count"] for item in results),
            "total_new_records": sum(item["new_count"] for item in results),
            "categories": category_stats,
        }
        write_json(self.source_root / "summary.json", results)
        write_json(self.source_root / "stats_report.json", source_stats)
        source_markdown = render_simple_markdown_report(
            "NPC 统计报告",
            [
                (
                    "概览",
                    {
                        "incremental": self.incremental,
                        "baseline_dir": str(self.baseline_dir) if self.baseline_dir else "",
                        "known_bbbs_count": len(self.known_bbbs),
                        "selected_categories": ", ".join(self.selected_categories),
                        "total_records": source_stats["total_records"],
                        "total_new_records": source_stats["total_new_records"],
                    },
                ),
                (
                    "分类汇总",
                    [
                        {
                            "name": item["category"],
                            "count": item["count"],
                            "extra": f"new={item['new_count']}",
                        }
                        for item in results
                    ],
                ),
            ],
        )
        write_text(self.source_root / "stats_report.md", source_markdown)
        return {"source": "npc", "results": results, "stats": source_stats}


class TreatyCrawler(BaseCrawler):
    source_name = "treaty"
    base_url = "https://treaty.mfa.gov.cn/web/"

    collection_urls = {
        "全部": "allinfos.jsp?nPageIndex_={page}",
        "双边": "shuangbian.jsp?nPageIndex_={page}",
        "多边": "duobian.jsp?nPageIndex_={page}",
    }

    def __init__(
        self,
        options: CrawlOptions,
        logger: logging.Logger,
        collections: list[str] | None,
    ) -> None:
        super().__init__(options, logger)
        self.selected_collections = collections or TREATY_DEFAULT_COLLECTIONS

    def fetch_html(self, url: str) -> BeautifulSoup:
        response = self.client.get(url)
        response.encoding = "utf-8"
        return BeautifulSoup(response.text, "html.parser")

    def collection_page_url(self, collection_name: str, page: int) -> str:
        return urljoin(self.base_url, self.collection_urls[collection_name].format(page=page))

    def parse_page_count(self, soup: BeautifulSoup) -> int:
        text = soup.get_text(" ", strip=True)
        match = re.search(r"当前:\s*\d+\s*/\s*(\d+)\s*页", text)
        return int(match.group(1)) if match else 1

    def parse_list_page(self, soup: BeautifulSoup) -> list[dict]:
        items = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if "detail" not in href:
                continue
            title = clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "detail_url": urljoin(self.base_url, href),
                }
            )
        return items

    def parse_detail(self, detail_url: str) -> dict:
        soup = self.fetch_html(detail_url)
        content = soup.select_one("div.neirong") or soup
        text = content.get_text("\n", strip=True)
        title_node = content.select_one("p.neirongp")
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        if not title and soup.title:
            title = clean_text(soup.title.get_text(strip=True).split("_")[0])
        if not title:
            first_lines = [line.strip() for line in text.splitlines() if line.strip()]
            title = first_lines[0] if first_lines else ""

        preview_links = []
        pdf_index = 1
        for anchor in content.find_all("a", href=True):
            href = anchor["href"]
            if not href.lower().endswith(".pdf"):
                continue
            label = ""
            previous_anchor = anchor.find_previous_sibling("a")
            if previous_anchor is not None:
                label = clean_text(previous_anchor.get_text(" ", strip=True))
            if not label:
                label = clean_text(anchor.parent.get_text(" ", strip=True).replace("预览", ""))
            label = label or f"preview_{pdf_index}"
            pdf_index += 1
            preview_links.append({"label": label, "url": urljoin(detail_url, href)})

        def extract(pattern: str) -> str:
            match = re.search(pattern, text, re.MULTILINE)
            return clean_text(match.group(1)) if match else ""

        return {
            "title": title,
            "detail_url": detail_url,
            "category": extract(r"类别：\s*([^\n]+)"),
            "domain": extract(r"领域：\s*([^\n]+)"),
            "sign_date": extract(r"我国签署时间：\s*([^\n]+)"),
            "effective_date": extract(r"条约生效时间：\s*([^\n]+)"),
            "depositary": extract(r"保存机关：\s*([^\n]+)"),
            "sign_place": extract(r"签署地点：\s*([^\n]+)"),
            "hong_kong_macau": extract(r"港澳情况：\s*([^\n]+)"),
            "effective_to_china": extract(r"对我国生效时间：\s*([^\n]+)"),
            "statement_reservation": extract(r"我国声明保留情况：\s*([^\n]+)"),
            "other_info": extract(r"其他：\s*([^\n]+)"),
            "preview_links": preview_links,
        }

    def download_file(self, url: str, path: Path) -> Path:
        response = self.client.get(url, stream=True)
        final_path = unique_path(path)
        with final_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    fh.write(chunk)
        return final_path

    def crawl_collection(self, collection_name: str) -> dict:
        collection_root = ensure_dir(self.source_root / sanitize_filename(collection_name, collection_name))
        files_root = ensure_dir(collection_root / "files")
        records: list[dict] = []

        first_page = self.fetch_html(self.collection_page_url(collection_name, 1))
        page_count = self.parse_page_count(first_page)
        self.logger.info("Treaty: %s 共 %s 页", collection_name, page_count)

        current_page = 1
        while True:
            if self.options.max_pages is not None and current_page > self.options.max_pages:
                break
            soup = first_page if current_page == 1 else self.fetch_html(self.collection_page_url(collection_name, current_page))
            items = self.parse_list_page(soup)
            if not items:
                break
            for item in items:
                detail = self.parse_detail(item["detail_url"])
                record = {
                    "source": "treaty",
                    "collection": collection_name,
                    **detail,
                    "downloaded_files": [],
                }
                if self.options.download_files and detail["preview_links"]:
                    record_dir = ensure_dir(
                        files_root / sanitize_filename(f"{detail['title']}_{collection_name}", "treaty")
                    )
                    downloaded_files = []
                    for index, preview in enumerate(detail["preview_links"], start=1):
                        ext = Path(urlparse(preview["url"]).path).suffix or ".pdf"
                        filename = sanitize_filename(f"{index:02d}_{preview['label']}{ext}", f"{index:02d}{ext}")
                        saved_path = self.download_file(preview["url"], record_dir / filename)
                        downloaded_files.append(str(saved_path.relative_to(collection_root)))
                    record["downloaded_files"] = downloaded_files
                records.append(record)
                if self.limit_reached(records):
                    break
            if self.limit_reached(records):
                break
            if current_page >= page_count:
                break
            current_page += 1

        records = self.apply_item_limit(records)
        write_jsonl(collection_root / "metadata.jsonl", records)
        write_csv(collection_root / "metadata.csv", records)
        write_json(
            collection_root / "summary.json",
            {"source": "treaty", "collection": collection_name, "count": len(records)},
        )
        return {"collection": collection_name, "count": len(records), "path": str(collection_root)}

    def crawl(self) -> dict:
        missing = [name for name in self.selected_collections if name not in self.collection_urls]
        if missing:
            raise ValueError(f"条约库不支持这些集合: {missing}")
        results = []
        for collection in self.selected_collections:
            results.append(self.crawl_collection(collection))
        write_json(self.source_root / "summary.json", results)
        return {"source": "treaty", "results": results}


class GovRulesCrawler(BaseCrawler):
    source_name = "gov_rules"
    index_url = "https://www.gov.cn/zhengce/xxgk/gjgzk/index.htm?searchWord="

    query_endpoint_path = "/athena/forward/BD8730CDDA12515E2D9E1B21AA11C0D6"
    category_map = {
        "部门规章": "部门规章",
        "地方政府规章": "地方政府规章",
    }

    def __init__(
        self,
        options: CrawlOptions,
        logger: logging.Logger,
        categories: list[str] | None,
    ) -> None:
        super().__init__(options, logger)
        self.selected_categories = categories or GOV_RULE_DEFAULT_CATEGORIES
        self.athena_base_url = ""
        self.athena_app_key = ""
        self.athena_app_name = ""

    def build_athena_key(self, public_key_b64: str, seed: str) -> str:
        pem = (
            "-----BEGIN PUBLIC KEY-----\n"
            f"{public_key_b64}\n"
            "-----END PUBLIC KEY-----\n"
        ).encode("ascii")
        public_key = serialization.load_pem_public_key(pem)
        encrypted = public_key.encrypt(seed.encode("utf-8"), padding.PKCS1v15())
        return quote(base64.b64encode(encrypted).decode("ascii"), safe="")

    def discover_athena_auth(self) -> None:
        response = self.client.get(self.index_url)
        response.encoding = "utf-8"
        html = response.text
        script_match = re.search(r'<script src="(index\.js\?[^"]+)"></script>', html)
        if not script_match:
            raise RuntimeError("无法在国家规章库首页找到 index.js")
        script_url = urljoin(self.index_url, script_match.group(1))
        script_text = self.client.get(script_url).text
        auth_match = re.search(
            r'var s="(?P<base>https://[^"]+)",o=encodeURIComponent\(a\("(?P<pub>[^"]+)","(?P<seed>[^"]+)"\)\),c=encodeURIComponent\("(?P<name>[^"]+)"\)',
            script_text,
        )
        if not auth_match:
            raise RuntimeError("无法从国家规章库前端脚本提取接口认证参数")
        self.athena_base_url = auth_match.group("base")
        self.athena_app_key = self.build_athena_key(auth_match.group("pub"), auth_match.group("seed"))
        self.athena_app_name = quote(auth_match.group("name"), safe="")

    def request_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": "https://www.gov.cn/",
            "athenaappname": self.athena_app_name,
            "athenaappkey": self.athena_app_key,
        }

    def search_page(self, category_name: str, page_no: int) -> dict:
        payload = {
            "code": "18258ab0ac9",
            "preference": None,
            "searchFields": [
                {"fieldName": "f_202321807875", "searchWord": category_name, "searchType": "TERM", "withHighLight": True},
                {"fieldName": "f_202321360426", "withHighLight": True},
                {"fieldName": "f_202321758948", "withHighLight": True},
                {"fieldName": "f_202321423473", "searchType": "TERM", "withHighLight": True},
                {"fieldName": "f_202321159816", "searchWord": "", "searchType": "TERM"},
                {"fieldName": "f_20232380533", "searchType": "TERM", "withHighLight": True},
                {"fieldName": "f_202328191239", "withHighLight": True, "searchType": "TERM"},
                {"fieldName": "f_20221110222856", "withHighLight": True, "searchType": "TERM"},
            ],
            "sorts": [{}, {"sortField": "f_202321915922", "sortOrder": "DESC"}],
            "resultFields": [
                "f_202355832506",
                "f_20232124962",
                "f_202321124775",
                "f_202321159816",
                "f_202321360426",
                "f_202321423473",
                "f_202321758948",
                "f_202321807875",
                "f_202321864401",
                "f_202321915922",
                "f_202323394765",
                "f_202328191239",
                "f_202344311304",
                "f_202355832506",
                "f_2023425676953",
                "f_2023425808265",
                "f_202321136868",
                "f_20232380533",
                "f_20232151076",
                "doc_pub_url",
            ],
            "trackTotalHits": "true",
            "tableName": "t_1860c735d31",
            "pageSize": self.options.gov_page_size,
            "pageNo": page_no,
            "granularity": "ALL",
        }
        response = self.client.post(
            f"{self.athena_base_url}{self.query_endpoint_path}",
            json=payload,
            headers=self.request_headers(),
        )
        data = response.json()
        if data["resultCode"]["code"] != 200:
            raise RuntimeError(f"Gov rules search failed: {data['resultCode']}")
        return data["result"]["data"]

    def parse_detail_page(self, detail_url: str) -> dict:
        response = self.client.get(detail_url)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        content_node = soup.select_one(".pages_content")
        text_content = clean_text(content_node.get_text("\n", strip=True) if content_node else "")
        attachments = []
        for anchor in soup.select('a[href][appendix="true"], a[href][data-appendix="true"]'):
            href = anchor.get("href")
            if not href:
                continue
            attachments.append(
                {
                    "title": clean_text(anchor.get_text(" ", strip=True) or anchor.get("title") or ""),
                    "url": urljoin(detail_url, href),
                }
            )
        return {
            "html": response.text,
            "text": text_content,
            "attachments": attachments,
        }

    def download_file(self, url: str, path: Path) -> Path:
        response = self.client.get(url, stream=True)
        final_path = unique_path(path)
        with final_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    fh.write(chunk)
        return final_path

    def crawl_category(self, category_name: str) -> dict:
        category_root = ensure_dir(self.source_root / sanitize_filename(category_name, category_name))
        files_root = ensure_dir(category_root / "files")
        records: list[dict] = []

        self.logger.info("Gov rules: 开始抓取 %s", category_name)
        page_no = 1
        total = None
        while True:
            if self.options.max_pages is not None and page_no > self.options.max_pages:
                break
            data = self.search_page(category_name, page_no)
            pager = data["pager"]
            items = data["list"]
            if total is None:
                total = pager["total"]
                self.logger.info("Gov rules: %s 总量 %s", category_name, total)
            if not items:
                break
            for item in items:
                title = clean_text(item.get("f_202321360426"))
                detail_url = clean_text(item.get("doc_pub_url"))
                record = {
                    "source": "gov_rules",
                    "category": category_name,
                    "title": title,
                    "issuer": clean_text(item.get("f_202323394765")),
                    "law_type": clean_text(item.get("f_202321807875")),
                    "publish_text": clean_text(item.get("f_202344311304")),
                    "publish_time": clean_text(item.get("f_202321915922")),
                    "org_names": clean_text(item.get("f_202328191239")),
                    "detail_url": detail_url,
                    "body_excerpt": clean_text(item.get("f_202321758948"))[:300],
                    "downloaded_text": "",
                    "downloaded_html": "",
                    "attachment_files": [],
                }
                if self.options.download_files and detail_url:
                    record_dir = ensure_dir(files_root / sanitize_filename(title, "rule"))
                    detail = self.parse_detail_page(detail_url)
                    html_path = record_dir / "page.html"
                    txt_path = record_dir / "page.txt"
                    html_path.write_text(detail["html"], encoding="utf-8")
                    txt_path.write_text(detail["text"], encoding="utf-8")
                    record["downloaded_html"] = str(html_path.relative_to(category_root))
                    record["downloaded_text"] = str(txt_path.relative_to(category_root))
                    attachment_files = []
                    for attachment in detail["attachments"]:
                        ext = Path(urlparse(attachment["url"]).path).suffix or ""
                        filename = sanitize_filename(attachment["title"], "attachment")
                        saved_path = self.download_file(attachment["url"], record_dir / f"{filename}{ext}")
                        attachment_files.append(str(saved_path.relative_to(category_root)))
                    record["attachment_files"] = attachment_files
                records.append(record)
                if self.limit_reached(records):
                    break
            if self.limit_reached(records):
                break
            if page_no >= pager["pageCount"]:
                break
            page_no += 1

        records = self.apply_item_limit(records)
        write_jsonl(category_root / "metadata.jsonl", records)
        write_csv(category_root / "metadata.csv", records)
        write_json(
            category_root / "summary.json",
            {"source": "gov_rules", "category": category_name, "count": len(records)},
        )
        return {"category": category_name, "count": len(records), "path": str(category_root)}

    def crawl(self) -> dict:
        missing = [name for name in self.selected_categories if name not in self.category_map]
        if missing:
            raise ValueError(f"国家规章库不支持这些分类: {missing}")
        self.discover_athena_auth()
        results = []
        for category in self.selected_categories:
            results.append(self.crawl_category(category))
        write_json(self.source_root / "summary.json", results)
        return {"source": "gov_rules", "results": results}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一法规数据库爬虫")
    parser.add_argument(
        "source",
        choices=["npc", "treaty", "gov-rules", "all"],
        help="要爬取的数据源",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        default=str(Path.cwd() / f"crawl_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
        help="输出根目录",
    )
    parser.add_argument("--no-download", action="store_true", help="只建索引，不下载文件")
    parser.add_argument("--max-pages", type=int, default=None, help="每个分类最多抓取多少页")
    parser.add_argument("--max-items", type=int, default=None, help="每个分类最多抓取多少条")
    parser.add_argument("--npc-page-size", type=int, default=500, help="NPC 接口每页条数")
    parser.add_argument("--gov-page-size", type=int, default=500, help="国家规章库接口每页条数")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP 超时时间（秒）")
    parser.add_argument("--npc-categories", nargs="*", default=None, help="NPC 分类，如 法律 行政法规 司法解释 地方性法规")
    parser.add_argument("--npc-incremental", action="store_true", help="开启 NPC 增量更新模式，基于历史 metadata.jsonl 标记新增规范")
    parser.add_argument("--npc-baseline-dir", default=None, help="NPC 增量更新的历史目录，可传旧输出根目录或 npc 目录")
    parser.add_argument("--npc-download-new-only", action="store_true", help="NPC 增量更新时只下载新增规范")
    parser.add_argument("--treaty-collections", nargs="*", default=None, help="条约集合，如 全部 双边 多边")
    parser.add_argument("--gov-categories", nargs="*", default=None, help="国家规章库分类，如 部门规章 地方政府规章")
    return parser


def setup_logger(output_root: Path) -> logging.Logger:
    ensure_dir(output_root)
    ensure_dir(output_root / "logs")
    logger = logging.getLogger("unified_law_crawler")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(output_root / "logs" / "run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    output_root = Path(args.output_root).expanduser().resolve()
    logger = setup_logger(output_root)
    options = CrawlOptions(
        output_root=output_root,
        download_files=not args.no_download,
        max_pages=args.max_pages,
        max_items=args.max_items,
        npc_page_size=args.npc_page_size,
        gov_page_size=args.gov_page_size,
        timeout=args.timeout,
    )

    crawlers: list[BaseCrawler] = []
    if args.source in ("npc", "all"):
        baseline_dir = Path(args.npc_baseline_dir).expanduser() if args.npc_baseline_dir else None
        crawlers.append(
            NpcCrawler(
                options,
                logger,
                args.npc_categories,
                incremental=args.npc_incremental,
                baseline_dir=baseline_dir,
                download_new_only=args.npc_download_new_only,
            )
        )
    if args.source in ("treaty", "all"):
        crawlers.append(TreatyCrawler(options, logger, args.treaty_collections))
    if args.source in ("gov-rules", "all"):
        crawlers.append(GovRulesCrawler(options, logger, args.gov_categories))

    summaries = []
    start = time.time()
    for crawler in crawlers:
        logger.info("开始执行数据源: %s", crawler.source_name)
        summaries.append(crawler.crawl())
        logger.info("完成数据源: %s", crawler.source_name)

    summary = {
        "started_at": datetime.now().isoformat(),
        "elapsed_seconds": round(time.time() - start, 2),
        "download_files": options.download_files,
        "summaries": summaries,
    }
    write_json(output_root / "summary.json", summary)
    write_json(output_root / "stats_report.json", summary)
    report_markdown = render_simple_markdown_report(
        "法规爬虫运行报告",
        [
            (
                "运行概览",
                {
                    "output_root": str(output_root),
                    "download_files": options.download_files,
                    "elapsed_seconds": summary["elapsed_seconds"],
                },
            ),
            (
                "数据源汇总",
                [
                    {
                        "name": item["source"],
                        "count": sum(result.get("count", 0) for result in item.get("results", [])),
                        "extra": f"分类数={len(item.get('results', []))}",
                    }
                    for item in summaries
                ],
            ),
        ],
    )
    write_text(output_root / "stats_report.md", report_markdown)
    logger.info("全部完成，输出目录: %s", output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
