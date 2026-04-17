# Law Crawler Unified

Unified Python crawler for several public Chinese legal databases.

## Supported Sources

- `npc`: National Laws and Regulations Database (`flk.npc.gov.cn`)
- `treaty`: Ministry of Foreign Affairs Treaty Database (`treaty.mfa.gov.cn`)
- `gov-rules`: State Council Rules Database (`gov.cn/zhengce/xxgk/gjgzk`)
- `all`: Run all sources sequentially

## Features

- Unified CLI for multiple legal databases
- Fine-grained NPC categories:
  - `法律`
  - `行政法规`
  - `司法解释`
  - `地方法规`
- Alias support for `地方性法规`
- Batch download and metadata export for NPC
- Treaty detail parsing and preview PDF download
- Rules detail page capture and attachment download
- Incremental update mode for NPC based on historical `bbbs`
- Per-category stats reports in `json` and `md`

## Installation

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## Usage

Show help:

```bash
python3 law_crawler_unified.py -h
```

Download all default NPC categories:

```bash
python3 law_crawler_unified.py npc -o ./output_npc
```

Download only local regulations:

```bash
python3 law_crawler_unified.py npc --npc-categories 地方性法规 -o ./output_npc_local
```

Run NPC in incremental mode and download only newly discovered items:

```bash
python3 law_crawler_unified.py npc \
  --npc-incremental \
  --npc-baseline-dir ./previous_output \
  --npc-download-new-only \
  -o ./output_npc_incremental
```

Run treaty database:

```bash
python3 law_crawler_unified.py treaty -o ./output_treaty
```

Run rules database:

```bash
python3 law_crawler_unified.py gov-rules -o ./output_gov_rules
```

Preview only without downloading files:

```bash
python3 law_crawler_unified.py all --no-download --max-items 5 -o ./output_preview
```

## Output Structure

Each source writes a structured output directory with:

- `metadata.jsonl`
- `metadata.csv`
- `summary.json`
- `stats_report.json`
- `stats_report.md`
- `new_items.jsonl` and `new_items.csv` for NPC
- `files/` for downloaded files
- `logs/run.log`

## Notes

- These public websites may change their HTML, APIs, or anti-bot behavior.
- `gov-rules` authentication is derived dynamically from the current frontend bundle.
- This repository does not include downloaded datasets or personal local outputs.

## License

MIT
