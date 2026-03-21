"""
organize.py — Downloads フォルダをOllamaで内容分類して整理するスクリプト

Usage:
    python organize.py                          # ドライラン（Downloadsを自動検出）
    python organize.py "C:/Users/me/Downloads"  # フォルダを明示指定
    python organize.py --execute                # 実際にファイルを移動
    python organize.py --model phi4             # 使用するOllamaモデルを指定
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

# OllamaのAPIエンドポイント（デフォルトのローカルホスト）
OLLAMA_API_URL = "http://localhost:11434/api/generate"

# 使用するOllamaモデル（--model で上書き可能）
DEFAULT_MODEL = "phi4"

# 分類カテゴリ一覧 — Ollamaへのプロンプトとフォルダ名に使用される
CATEGORIES = [
    "Invoice_Receipt",  # 請求書・領収書・注文確認
    "Work_Documents",  # 業務資料・報告書・議事録
    "Study_Materials",  # 教材・論文・技術資料・スライド
    "Personal_Memos",  # 個人メモ・日記・手紙
    "Others",  # 上記に当てはまらないもの
]

# Ollamaに送るテキストの最大文字数（長すぎると遅くなるため冒頭に絞る）
MAX_CHARS = 1500

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


# ---------------------------------------------------------------------------
# テキスト抽出
# ---------------------------------------------------------------------------


def extract_text(path: Path) -> str | None:
    """
    ファイルからテキストを抽出する。
    対応外の拡張子や読み込みエラーの場合はNoneを返す（→ スキップ扱い）。
    """
    ext = path.suffix.lower()

    if ext in PLAIN_TEXT_EXTENSIONS:
        return _read_plain(path)
    elif ext == ".pdf":
        return _read_pdf(path)
    elif ext == ".docx":
        return _read_docx(path)

    # 対応していない拡張子（画像・動画・zip等）はNoneを返す
    return None


def _read_plain(path: Path) -> str | None:
    """プレーンテキストを読んで先頭MAX_CHARS文字だけ返す。"""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_CHARS]
    except Exception as e:
        print(f"  [warn] テキスト読み込み失敗: {e}")
        return None


def _read_pdf(path: Path) -> str | None:
    """
    PDFからテキストを抽出する。
    pypdfがインストールされていない場合は警告を出してNoneを返す。
    スキャンPDF（画像のみ）はテキストが取れないため空文字になる場合がある。
    """
    try:
        import pypdf
    except ImportError:
        print(
            "  [warn] pypdf 未インストール。PDF読み込みをスキップします（pip install pypdf）"
        )
        return None

    try:
        reader = pypdf.PdfReader(str(path))
        texts = []
        for page in reader.pages:
            texts.append(page.extract_text() or "")
            # MAX_CHARSに達したら残りのページは読まない
            if sum(len(t) for t in texts) >= MAX_CHARS:
                break
        return "".join(texts)[:MAX_CHARS]
    except Exception as e:
        print(f"  [warn] PDF読み込み失敗: {e}")
        return None


def _read_docx(path: Path) -> str | None:
    """
    Word文書（.docx）からテキストを抽出する。
    python-docxがインストールされていない場合は警告を出してNoneを返す。
    """
    try:
        import docx
    except ImportError:
        print(
            "  [warn] python-docx 未インストール。docx読み込みをスキップします（pip install python-docx）"
        )
        return None

    try:
        doc = docx.Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs)
        return text[:MAX_CHARS]
    except Exception as e:
        print(f"  [warn] Word読み込み失敗: {e}")
        return None


# ---------------------------------------------------------------------------
# Ollamaによる分類
# ---------------------------------------------------------------------------


def classify(text: str, model: str) -> str | None:
    """
    テキストをOllamaに送り、カテゴリ名を返す。
    接続失敗・予期しない回答の場合はNoneを返す（→ Uncategorized扱い）。
    """
    # カテゴリリストを文字列に変換してプロンプトに埋め込む
    categories_str = ", ".join(f'"{c}"' for c in CATEGORIES)

    prompt = (
        f"You are a file classifier. "
        f"Classify the following document into exactly one of these categories: {categories_str}.\n"
        f"Reply with only the category name, nothing else. Do not explain.\n\n"
        f"Document:\n{text}"
    )

    try:
        resp = requests.post(
            OLLAMA_API_URL,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60,  # 重いモデルに備えて余裕を持たせる
        )
        resp.raise_for_status()

        # OllamaはJSONで{"response": "..."}を返す
        raw = resp.json().get("response", "").strip().strip('"').strip()

        # 回答がカテゴリリストのいずれかに一致するか検証（部分一致も許容）
        for cat in CATEGORIES:
            if cat.lower() in raw.lower():
                return cat

        # 一致しない場合は警告だけ出してNoneを返す
        print(f"  [warn] Ollamaの回答がカテゴリと一致しません: {raw!r}")
        return None

    except requests.exceptions.ConnectionError:
        # Ollamaが起動していない場合
        print(
            "  [error] Ollamaに接続できません。`ollama serve` で起動しているか確認してください。"
        )
        return None
    except requests.exceptions.Timeout:
        print("  [error] OllamaのAPIがタイムアウトしました（モデルが重すぎる可能性）。")
        return None
    except Exception as e:
        print(f"  [error] Ollama APIエラー: {e}")
        return None


# ---------------------------------------------------------------------------
# ファイル移動（重複防止付き）
# ---------------------------------------------------------------------------


def safe_destination(dest_dir: Path, filename: str) -> Path:
    """
    移動先に同名ファイルがある場合は「名前 (1).ext」のように連番を付けて
    上書きを防ぐ。
    """
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


def move_file(src: Path, dest: Path, execute: bool):
    """
    ファイルを移動する。
    executeがFalseのときは移動先を表示するだけ（ドライラン）。
    """
    if execute:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        print(f"  移動完了: {src.name}  →  {dest.parent.name}/{dest.name}")
    else:
        print(f"  [DRY-RUN] {src.name}  →  {dest.parent.name}/{dest.name}")


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------


def get_downloads_dir() -> Path:
    """
    WindowsのDownloadsフォルダパスを返す。
    USERPROFILE環境変数を使うことでユーザー名に依存しない。
    """
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    return home / "Downloads"


def main():
    parser = argparse.ArgumentParser(
        description="Downloadsフォルダの内容をOllamaで読んで分類・整理するスクリプト"
    )
    parser.add_argument(
        "folder",
        nargs="?",
        help="対象フォルダのパス（省略するとWindowsのDownloadsを自動検出）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="このフラグがある場合のみ実際にファイルを移動する（デフォルトはドライラン）",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"使用するOllamaモデル名（デフォルト: {DEFAULT_MODEL}）",
    )
    args = parser.parse_args()

    # 対象フォルダの決定
    target_dir = Path(args.folder) if args.folder else get_downloads_dir()
    if not target_dir.is_dir():
        print(f"エラー: フォルダが存在しません: {target_dir}")
        sys.exit(1)

    mode_label = "EXECUTE（実際に移動）" if args.execute else "DRY-RUN（表示のみ）"
    print(f"=== organize.py [{mode_label}] ===")
    print(f"対象フォルダ : {target_dir}")
    print(f"Ollamaモデル : {args.model}")
    print(f"カテゴリ     : {', '.join(CATEGORIES)}")
    print()

    # 既存のカテゴリフォルダと "Uncategorized" は処理対象から除外する
    skip_dirs = set(CATEGORIES) | {"Uncategorized"}

    # 対象ファイル一覧（直下のファイルのみ。サブフォルダは再帰しない）
    files = sorted(
        f for f in target_dir.iterdir() if f.is_file() and f.name not in skip_dirs
    )

    if not files:
        print("対象ファイルが見つかりませんでした。")
        return

    print(f"{len(files)} 件のファイルを処理します。\n")
    print("-" * 60)

    stats = {"categorized": 0, "uncategorized": 0, "skipped": 0}

    for file in files:
        print(f"\n[{file.name}]")

        # Step 1: テキストを抽出する
        text = extract_text(file)

        if text is None:
            # 対応外の拡張子（.jpg, .zip等）またはライブラリ未インストール
            print("  → スキップ（テキスト抽出対象外）")
            stats["skipped"] += 1
            continue

        if not text.strip():
            # テキストが空（スキャンPDF等）→ Ollamaに送っても無意味なのでUncategorized
            print("  → テキストが空のためUncategorizedへ")
            category = "Uncategorized"
        else:
            # Step 2: Ollamaで分類させる
            category = classify(text, args.model)
            if category is None:
                # 接続失敗・回答不正のいずれもUncategorizedに振り分ける
                category = "Uncategorized"
            print(f"  → カテゴリ: {category}")

        # Step 3: 移動先パスを決定（重複ファイル名は連番付きで保護）
        dest_dir = target_dir / category
        dest = safe_destination(dest_dir, file.name)

        # Step 4: 移動（またはドライラン表示）
        move_file(file, dest, args.execute)

        if category == "Uncategorized":
            stats["uncategorized"] += 1
        else:
            stats["categorized"] += 1

    # 最終サマリ
    print()
    print("=" * 60)
    print(f"分類済み    : {stats['categorized']} 件")
    print(f"Uncategorized: {stats['uncategorized']} 件")
    print(f"スキップ    : {stats['skipped']} 件（テキスト抽出対象外）")

    if not args.execute:
        print()
        print(
            "※ ドライランです。実際に移動するには --execute を付けて実行してください。"
        )
        print("  例: python organize.py --execute")


if __name__ == "__main__":
    main()
