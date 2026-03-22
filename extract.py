"""
extract.py — ファイルの内容をOllamaでローカルに要約し、インデックスを生成するスクリプト

Usage:
    python extract.py                          # Downloadsを自動検出
    python extract.py "C:/Users/me/Downloads"  # フォルダを明示指定
    python extract.py --model granite4:350m-h  # モデル指定

出力: downloads_index.json（organize.py と同じディレクトリに保存）

次のステップ:
    1. downloads_index.json を Claude に渡して分類させる
    2. Claude が出力した classifications.json を apply.py で実行する
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

OLLAMA_API_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "granite4:350m-h"

# テキストをそのまま読めるファイル拡張子
PLAIN_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".log",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".rst",
}

# 要約に使うテキストの最大文字数（要約なので少なくてOK）
MAX_CHARS = 1200

# インデックスファイルの保存先（このスクリプトと同じディレクトリ）
INDEX_PATH = Path(__file__).parent / "downloads_index.json"


# ---------------------------------------------------------------------------
# テキスト抽出（organize.py と同じロジック）
# ---------------------------------------------------------------------------


def extract_text(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in PLAIN_TEXT_EXTENSIONS:
        return _read_plain(path)
    elif ext == ".pdf":
        return _read_pdf(path)
    elif ext == ".docx":
        return _read_docx(path)
    return None


def _read_plain(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_CHARS]
    except Exception:
        return None


def _read_pdf(path: Path) -> str | None:
    try:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        texts = []
        for page in reader.pages:
            texts.append(page.extract_text() or "")
            if sum(len(t) for t in texts) >= MAX_CHARS:
                break
        return "".join(texts)[:MAX_CHARS] or None
    except ImportError:
        return None
    except Exception:
        return None


def _read_docx(path: Path) -> str | None:
    try:
        import docx

        doc = docx.Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs)
        return text[:MAX_CHARS] or None
    except ImportError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Ollamaで1行要約を生成
# ---------------------------------------------------------------------------


def summarize(text: str, model: str) -> str:
    """
    ファイルのテキストをOllamaに送り、1文の説明を返す。
    失敗した場合は空文字列を返す（→ Claudeが判断不能として扱える）。
    """
    prompt = (
        "Describe this document in one sentence. "
        "State the document type (e.g. invoice, lecture notes, passport, travel plan) "
        "and the main subject. Be factual and concise. Do not guess. "
        "If the content is unclear, say 'Unclear document content.'\n\n"
        f"Document:\n{text}"
    )

    try:
        resp = requests.post(
            OLLAMA_API_URL,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        return f"[extraction error: {e}]"


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------


def get_downloads_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    return home / "Downloads"


def main():
    parser = argparse.ArgumentParser(
        description="ファイルをローカルで要約してインデックスJSONを生成する"
    )
    parser.add_argument("folder", nargs="?", help="対象フォルダ（省略時はDownloads）")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollamaモデル（デフォルト: {DEFAULT_MODEL}）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="既存のインデックスに追記する（処理済みをスキップ）",
    )
    args = parser.parse_args()

    target_dir = Path(args.folder) if args.folder else get_downloads_dir()
    if not target_dir.is_dir():
        print(f"エラー: フォルダが存在しません: {target_dir}")
        sys.exit(1)

    # --resume の場合は既存インデックスを読み込む
    existing: dict[str, dict] = {}
    if args.resume and INDEX_PATH.exists():
        with open(INDEX_PATH, encoding="utf-8") as f:
            for entry in json.load(f):
                existing[entry["file"]] = entry
        print(f"既存インデックス読み込み: {len(existing)} 件")

    print(f"=== extract.py ===")
    print(f"対象フォルダ : {target_dir}")
    print(f"Ollamaモデル : {args.model}")
    print(f"出力先       : {INDEX_PATH}")
    print()

    # 対象ファイル一覧（既存カテゴリフォルダはスキップ）
    skip_dirs = {
        "Invoice_Receipt",
        "University_Docs",
        "Study_Materials",
        "Travel_Plans",
        "Personal_Documents",
        "Others",
        "Uncategorized",
    }
    files = sorted(
        f for f in target_dir.iterdir() if f.is_file() and f.name not in skip_dirs
    )

    results = []
    skipped_count = 0
    extracted_count = 0

    for i, file in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {file.name}")

        # --resume: 処理済みはスキップ
        if args.resume and file.name in existing:
            print("  → スキップ（処理済み）")
            results.append(existing[file.name])
            continue

        text = extract_text(file)

        if text is None or not text.strip():
            # テキスト抽出不可（画像・zip・exe・スキャンPDF等）
            entry = {
                "file": file.name,
                "extractable": False,
                "summary": "",
                "extracted_at": datetime.now().strftime("%Y-%m-%d"),
            }
            print("  → テキスト抽出不可（スキップ）")
            skipped_count += 1
        else:
            # Ollamaで要約
            summary = summarize(text, args.model)
            entry = {
                "file": file.name,
                "extractable": True,
                "summary": summary,
                "extracted_at": datetime.now().strftime("%Y-%m-%d"),
            }
            print(f"  → {summary[:80]}{'...' if len(summary) > 80 else ''}")
            extracted_count += 1

        results.append(entry)

        # 10件ごとに中間保存（途中終了しても安全）
        if i % 10 == 0:
            with open(INDEX_PATH, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

    # 最終保存
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    print(f"要約完了 : {extracted_count} 件")
    print(f"スキップ : {skipped_count} 件（テキスト抽出不可）")
    print(f"出力先   : {INDEX_PATH}")
    print()
    print("次のステップ:")
    print("  downloads_index.json を Claude に渡して分類させてください。")
    print("  Claude の出力（classifications.json）を保存後:")
    print("  python apply.py")


if __name__ == "__main__":
    main()
