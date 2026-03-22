"""
apply.py — classifications.json を読んでファイルを移動するスクリプト

Usage:
    python apply.py                            # ドライラン（デフォルト）
    python apply.py --execute                  # 実際にファイルを移動
    python apply.py "C:/Users/me/Downloads"    # フォルダを明示指定

ワークフロー:
    1. python extract.py          → downloads_index.json を生成
    2. Claude に渡して分類させる   → classifications.json を保存
    3. python apply.py            → ドライランで確認
    4. python apply.py --execute  → 実際に移動

classifications.json の形式:
    [
      {"file": "invoice.pdf",   "category": "Invoice_Receipt"},
      {"file": "lecture5.pdf",  "category": "Study_Materials"},
      ...
    ]
"""

import argparse
import json
import os
import shutil
import sys
import unicodedata
from pathlib import Path

# classifications.json の場所（このスクリプトと同じディレクトリ）
CLASSIFICATIONS_PATH = Path(__file__).parent / "classifications.json"


# ---------------------------------------------------------------------------
# ファイル移動（重複防止付き）
# ---------------------------------------------------------------------------


def safe_destination(dest_dir: Path, filename: str) -> Path:
    """移動先に同名ファイルがある場合は連番を付けて上書きを防ぐ。"""
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def get_downloads_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    return home / "Downloads"


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="classifications.json に基づいてファイルを移動する"
    )
    parser.add_argument("folder", nargs="?", help="対象フォルダ（省略時はDownloads）")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="実際にファイルを移動する（デフォルトはドライラン）",
    )
    parser.add_argument(
        "--classifications",
        default=str(CLASSIFICATIONS_PATH),
        help=f"classifications.json のパス（デフォルト: {CLASSIFICATIONS_PATH}）",
    )
    args = parser.parse_args()

    target_dir = Path(args.folder) if args.folder else get_downloads_dir()
    if not target_dir.is_dir():
        print(f"エラー: フォルダが存在しません: {target_dir}")
        sys.exit(1)

    classifications_path = Path(args.classifications)
    if not classifications_path.exists():
        print(f"エラー: {classifications_path} が見つかりません。")
        print("  Claude に downloads_index.json を渡して分類させ、")
        print("  出力を classifications.json として保存してください。")
        sys.exit(1)

    with open(classifications_path, encoding="utf-8") as f:
        classifications: list[dict] = json.load(f)

    mode_label = "EXECUTE（実際に移動）" if args.execute else "DRY-RUN（表示のみ）"
    print(f"=== apply.py [{mode_label}] ===")
    print(f"対象フォルダ          : {target_dir}")
    print(f"classifications.json : {classifications_path}")
    print(f"分類エントリ数        : {len(classifications)} 件")
    print()

    stats = {"moved": 0, "skipped_missing": 0, "skipped_no_category": 0}

    for entry in classifications:
        filename = entry.get("file", "")
        category = entry.get("category", "").strip()

        if not filename:
            continue

        source = entry.get("source", filename)
        src = target_dir / source
        # NFD/NFC正規化の違いに対応（Macでダウンロードしたファイルに発生）
        if not src.exists():
            src_nfd = target_dir / unicodedata.normalize("NFD", source)
            if src_nfd.exists():
                src = src_nfd

        # ファイルが存在しない場合はスキップ（既に移動済みの可能性）
        if not src.exists():
            print(f"[スキップ] {filename}（ファイルなし）")
            stats["skipped_missing"] += 1
            continue

        # カテゴリが空またはスキップ指定の場合はそのままにする
        if not category or category.lower() in ("skip", "none", ""):
            print(f"[スキップ] {filename}（カテゴリ未指定）")
            stats["skipped_no_category"] += 1
            continue

        dest_dir = target_dir / category
        dest = safe_destination(dest_dir, filename)

        if args.execute:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            print(f"  移動完了: {filename}  →  {category}/{dest.name}")
        else:
            print(f"  [DRY-RUN] {filename}  →  {category}/{dest.name}")

        stats["moved"] += 1

    print()
    print("=" * 60)
    print(f"移動{'完了' if args.execute else '予定'} : {stats['moved']} 件")
    print(f"スキップ（ファイルなし）   : {stats['skipped_missing']} 件")
    print(f"スキップ（カテゴリ未指定） : {stats['skipped_no_category']} 件")

    if not args.execute:
        print()
        print(
            "※ ドライランです。実際に移動するには --execute を付けて実行してください。"
        )


if __name__ == "__main__":
    main()
