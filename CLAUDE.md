# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Organises a Windows Downloads folder by moving files into a hierarchical folder structure, using local Ollama for text extraction/summarisation and Claude for classification.

## Pipeline

```
extract.py  →  downloads_index.json  →  Claude classifies  →  classifications.json  →  apply.py
```

1. `python extract.py` — scans Downloads, extracts text via pypdf/python-docx, summarises with Ollama (granite4:350m-h), saves `downloads_index.json`
2. Give `downloads_index.json` to Claude → produces `classifications.json`
3. `python apply.py` — dry-run (default), shows planned moves
4. `python apply.py --execute` — moves files

## Key files

| File | Purpose |
|---|---|
| `extract.py` | Phase 1: local Ollama summarisation |
| `apply.py` | Phase 3: reads classifications.json, moves files |
| `organize.py` | All-in-one: Ollama classify + move (older approach) |
| `requirements.txt` | Python deps |
| `classifications.json` | **gitignored** — personal file classifications |
| `downloads_index.json` | **gitignored** — AI summaries of personal files |

## classifications.json format

```json
[
  {"file": "invoice.pdf", "category": "請求・領収書"},
  {"file": "lecture5.pdf", "source": "Study_Materials/lecture5.pdf", "category": "大学/Sheffield/講義資料"}
]
```

- `file`: filename only (used in log output)
- `source`: relative path from Downloads root (optional — defaults to `file`)
- `category`: destination subfolder path (supports nested with `/`)

## apply.py features

- Dry-run by default; `--execute` to actually move
- `--classifications PATH` to specify a different JSON file
- `--folder PATH` to target a different root folder
- NFD/NFC Unicode normalisation for filenames downloaded on macOS
- Duplicate filename protection (adds ` (1)`, ` (2)` suffix)

## Ollama setup

```bash
ollama serve          # start Ollama (if not running)
ollama pull granite4:350m-h  # fast small model for summarisation
```

## Folder structure (current target)

```
Downloads/
├── 大学/Sheffield/{課題・レポート, 規則・ポリシー, 時間割・カレンダー, 手続き・書類, 講義資料, 宿舎}
├── 大学/横浜国立大学/{交換留学, レポート・課題, 講義資料, 過去問, 手続き・書類}
├── 大学/留学準備
├── 勉強/{論文・研究, 高校・予備校, 技術資料}
├── 旅行/{計画, 予約・チケット, 宿泊}
├── 個人書類/{パスポート, 保険, 証明書・成績, 契約書}
├── 英語学習
├── 運転免許
├── 請求・領収書
├── ソフトウェア
└── その他
```
