# Law Crawler Unified / 法规数据库统一爬虫

Unified Python crawler for several public Chinese legal databases.

面向多个公开中文法规数据库的统一 Python 爬虫脚本。

## Overview / 项目简介

This repository provides a single command-line entrypoint for crawling and downloading metadata or files from multiple public legal databases.

这个仓库提供一个统一的命令行入口，用于抓取多个公开法规数据库的元数据与文件。

Current supported sources:

当前支持的数据源：

- `npc`: National Laws and Regulations Database / 国家法律法规数据库
- `treaty`: Ministry of Foreign Affairs Treaty Database / 外交部条约数据库
- `gov-rules`: State Council Rules Database / 国家规章库
- `all`: run all supported sources sequentially / 顺序执行全部数据源

## Features / 主要功能

- Unified CLI for multiple legal databases
- One script, one output convention, multiple sources
- Fine-grained NPC category selection
- NPC incremental update mode based on historical identifiers
- Batch file download and directory export for NPC
- Treaty detail parsing and preview PDF download
- Rule detail page capture and attachment download
- Structured outputs in JSONL, CSV, JSON, and Markdown reports

- 多数据库统一命令行入口
- 单脚本、统一输出结构、统一运行方式
- 支持国家法律法规数据库细分类别抓取
- 支持基于历史标识的国家法律法规数据库增量更新
- 支持国家法律法规数据库的批量目录导出和正文下载
- 支持条约库详情页解析与预览 PDF 下载
- 支持国家规章库正文抓取与附件下载
- 支持 JSONL、CSV、JSON 和 Markdown 统计报告输出

## Supported Sources / 支持的数据源

### `npc`

National Laws and Regulations Database: [https://flk.npc.gov.cn/search](https://flk.npc.gov.cn/search)

国家法律法规数据库：[https://flk.npc.gov.cn/search](https://flk.npc.gov.cn/search)

Supported categories:

支持的类别：

- `法律`
- `行政法规`
- `司法解释`
- `地方法规`

Alias:

别名支持：

- `地方性法规` -> `地方法规`

### `treaty`

Ministry of Foreign Affairs Treaty Database: [https://treaty.mfa.gov.cn/web/](https://treaty.mfa.gov.cn/web/)

外交部条约数据库：[https://treaty.mfa.gov.cn/web/](https://treaty.mfa.gov.cn/web/)

Supported collections:

支持的集合：

- `全部`
- `双边`
- `多边`

### `gov-rules`

State Council Rules Database: [https://www.gov.cn/zhengce/xxgk/gjgzk/](https://www.gov.cn/zhengce/xxgk/gjgzk/)

国家规章库：[https://www.gov.cn/zhengce/xxgk/gjgzk/](https://www.gov.cn/zhengce/xxgk/gjgzk/)

Supported categories:

支持的类别：

- `部门规章`
- `地方政府规章`

## Installation / 安装

Recommended environment:

推荐环境：

- Python 3.10+
- `venv` or another isolated virtual environment

Create a virtual environment and install dependencies:

创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Current dependencies:

当前依赖：

- `requests`
- `beautifulsoup4`
- `cryptography`

## Quick Start / 快速开始

Show help:

查看帮助：

```bash
python3 law_crawler_unified.py -h
```

Run all supported sources:

抓取全部支持的数据源：

```bash
python3 law_crawler_unified.py all -o ./output_all
```

Preview metadata only without downloading files:

只预览元数据，不下载文件：

```bash
python3 law_crawler_unified.py all --no-download --max-items 5 -o ./output_preview
```

## Usage / 使用方法

### 1. NPC / 国家法律法规数据库

Download the default NPC categories:

下载默认的国家法律法规数据库分类：

```bash
python3 law_crawler_unified.py npc -o ./output_npc
```

Download only laws and judicial interpretations:

只下载法律和司法解释：

```bash
python3 law_crawler_unified.py npc --npc-categories 法律 司法解释 -o ./output_npc_selected
```

Download local regulations:

下载地方性法规：

```bash
python3 law_crawler_unified.py npc --npc-categories 地方性法规 -o ./output_npc_local
```

Build index only:

只建索引，不下载正文：

```bash
python3 law_crawler_unified.py npc --no-download -o ./output_npc_index
```

### 2. NPC Incremental Update / 国家法律法规数据库增量更新

Use a previous output directory as the baseline and mark newly discovered items.

用上一轮输出目录作为基线，标记新增规范。

```bash
python3 law_crawler_unified.py npc \
  --npc-incremental \
  --npc-baseline-dir ./previous_output \
  -o ./output_npc_incremental
```

Download only newly discovered items:

只下载新增规范：

```bash
python3 law_crawler_unified.py npc \
  --npc-incremental \
  --npc-baseline-dir ./previous_output \
  --npc-download-new-only \
  -o ./output_npc_incremental
```

How incremental mode works:

增量模式工作方式：

- It loads historical `metadata.jsonl`
- It extracts historical `bbbs` identifiers
- It compares current search results with historical identifiers
- It marks records as `is_new` or `is_known`
- It writes `new_items.jsonl` and `new_items.csv`

- 读取历史 `metadata.jsonl`
- 提取历史 `bbbs` 标识
- 将本轮抓取结果与历史标识比对
- 标记记录为 `is_new` 或 `is_known`
- 输出 `new_items.jsonl` 和 `new_items.csv`

### 3. Treaty Database / 外交部条约数据库

Run the treaty crawler:

运行条约库爬虫：

```bash
python3 law_crawler_unified.py treaty -o ./output_treaty
```

Run only selected collections:

只运行指定集合：

```bash
python3 law_crawler_unified.py treaty --treaty-collections 双边 多边 -o ./output_treaty_selected
```

### 4. Rules Database / 国家规章库

Run the rules crawler:

运行国家规章库爬虫：

```bash
python3 law_crawler_unified.py gov-rules -o ./output_gov_rules
```

Run only selected categories:

只运行指定分类：

```bash
python3 law_crawler_unified.py gov-rules --gov-categories 部门规章 -o ./output_gov_rules_selected
```

## Command-Line Options / 命令行参数

Common options:

通用参数：

- `-o, --output-root`: output root directory / 输出根目录
- `--no-download`: collect metadata only / 只抓元数据，不下载文件
- `--max-pages`: limit pages per category / 限制每个分类抓取页数
- `--max-items`: limit items per category / 限制每个分类抓取条数
- `--timeout`: HTTP timeout in seconds / HTTP 超时秒数

NPC options:

国家法律法规数据库参数：

- `--npc-categories`: NPC categories / 抓取分类
- `--npc-page-size`: page size for NPC API / NPC 接口分页大小
- `--npc-incremental`: enable incremental update mode / 开启增量更新模式
- `--npc-baseline-dir`: historical output directory / 历史输出目录
- `--npc-download-new-only`: download only new records in incremental mode / 增量模式下只下载新增项

Treaty options:

条约库参数：

- `--treaty-collections`: collections to crawl / 要抓取的集合

Rules options:

国家规章库参数：

- `--gov-categories`: categories to crawl / 要抓取的分类
- `--gov-page-size`: page size for rules API / 国家规章库分页大小

## Output Structure / 输出结构

The crawler writes structured outputs under the selected output root.

脚本会在指定输出根目录下生成结构化结果。

Typical files:

典型输出文件：

- `summary.json`: run summary / 运行汇总
- `stats_report.json`: structured stats report / 结构化统计报告
- `stats_report.md`: readable Markdown report / 可读 Markdown 报告
- `logs/run.log`: runtime log / 运行日志

Per-category files:

每个分类下的文件：

- `metadata.jsonl`: full metadata records / 完整元数据
- `metadata.csv`: spreadsheet-friendly metadata / 便于查看的表格版本
- `new_items.jsonl`: new items in incremental mode / 增量模式下的新增项
- `new_items.csv`: CSV view of new items / 新增项 CSV
- `files/`: downloaded documents, attachments, or PDFs / 下载的正文、附件或 PDF

Example layout:

目录示意：

```text
output_root/
  logs/
    run.log
  summary.json
  stats_report.json
  stats_report.md
  npc/
    stats_report.json
    stats_report.md
    法律/
      metadata.jsonl
      metadata.csv
      new_items.jsonl
      new_items.csv
      summary.json
      stats_report.json
      stats_report.md
      files/
```

## Implementation Notes / 实现说明

### NPC

- Uses the current public search API
- Uses the current batch export endpoint for directory XLSX
- Uses the current batch download endpoint for files

- 直接调用当前公开搜索接口
- 使用当前批量导出目录接口生成 XLSX
- 使用当前批量下载接口获取正文文件

### Treaty

- Parses current list pages
- Opens detail pages for metadata extraction
- Downloads preview PDFs when available

- 解析当前列表页
- 进入详情页提取元数据
- 有预览 PDF 时自动下载

### Rules

- Discovers auth parameters from the current frontend bundle
- Builds the request header dynamically
- Downloads detail pages and detected attachments

- 从当前前端脚本里提取认证参数
- 动态生成请求头
- 下载正文页面和识别到的附件

## Limitations / 限制与说明

- Public websites may change structure, APIs, or anti-bot behavior at any time.
- Large crawls may take a long time and may be affected by temporary rate limits.
- Incremental update is identifier-based, not timestamp-based.
- This repository intentionally excludes downloaded datasets and local test outputs.

- 公开网站可能随时变更页面结构、接口或反爬策略。
- 大规模抓取耗时较长，也可能受到临时限流影响。
- 当前增量更新基于标识比对，不是基于时间戳过滤。
- 本仓库有意不包含下载后的数据文件和本地测试产物。

## Suggested Next Steps / 后续可扩展方向

- Add timestamp-based NPC update windows
- Add resumable download state
- Add unit tests around parsers
- Add GitHub Actions for basic validation

- 增加基于时间窗口的 NPC 更新模式
- 增加断点续跑状态管理
- 为解析逻辑补充单元测试
- 为仓库补充 GitHub Actions 基础校验

## Disclaimer / 免责声明

Use this project only for lawful access to public information and within the target websites' terms and restrictions.

本项目仅应用于合法获取公开信息，并应遵守目标网站的使用条款和访问限制。

## License / 许可证

MIT
