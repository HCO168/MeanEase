#!/usr/bin/env python3
"""Update MeanEase from Git or the latest GitHub archive."""

from __future__ import annotations

import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parent
ARCHIVE_URL = "https://github.com/HCO168/MeanEase/archive/refs/heads/main.zip"
MAX_ARCHIVE_BYTES = 30 * 1024 * 1024
UPDATE_FILES = (
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "project.md",
    "vocab_coach.html",
    "us_core_7000_authentic.csv",
    "start_vocab.py",
    "update_vocab.py",
    "build_authentic_7000.py",
    "enrich_tatoeba_examples.py",
    "apply_cefr_levels.py",
    "audit_vocabulary.py",
)


def update_with_git():
    """Return True/False for a Git checkout, or None for a ZIP copy."""
    if not (ROOT / ".git").is_dir():
        return None
    git = shutil.which("git")
    if not git:
        print("检测到 Git 仓库，但系统中找不到 Git。")
        return False
    result = subprocess.run(
        [git, "-C", str(ROOT), "pull", "--ff-only", "origin", "main"],
        check=False,
    )
    if result.returncode:
        print("Git 更新失败。请确认网络正常且项目文件没有冲突修改。")
        return False
    print("更新完成。浏览器中的学习进度不会受到影响。")
    return True


def download_archive() -> bytes:
    request = urllib.request.Request(
        ARCHIVE_URL,
        headers={"User-Agent": "MeanEase-updater/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("下载包异常过大，已停止更新")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise RuntimeError("下载包超过安全大小限制，已停止更新")
            chunks.append(chunk)
    return b"".join(chunks)


def read_update_files(archive: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        for member in package.infolist():
            parts = PurePosixPath(member.filename).parts
            if len(parts) == 2 and parts[1] in UPDATE_FILES and not member.is_dir():
                files[parts[1]] = package.read(member)
    missing = set(UPDATE_FILES) - files.keys()
    if missing:
        raise RuntimeError("更新包缺少文件：" + ", ".join(sorted(missing)))
    return files


def validate(files: dict[str, bytes]) -> None:
    html = files["vocab_coach.html"].lower()
    if b"<!doctype html" not in html or b"vocab_coach_db" not in html:
        raise RuntimeError("网页文件校验失败")

    csv_text = files["us_core_7000_authentic.csv"].decode("utf-8-sig")
    header = csv_text.splitlines()[0]
    if not header.startswith("word,base_word,phonetic,pos,meaning,level"):
        raise RuntimeError("词库表头校验失败")
    if ",morphology,morphology_source,morphology_license," not in header:
        raise RuntimeError("词库缺少 morphology 字段")
    if any(field in header.split(",") for field in ("etymology", "etymology_source", "etymology_license")):
        raise RuntimeError("词库仍包含已移除的 etymology 兼容字段")
    if len(csv_text.splitlines()) < 20001:
        raise RuntimeError("词库数量校验失败")

    for name in ("start_vocab.py", "update_vocab.py", "build_authentic_7000.py", "apply_cefr_levels.py", "enrich_tatoeba_examples.py", "audit_vocabulary.py"):
        ast.parse(files[name].decode("utf-8"))


def install(files: dict[str, bytes]) -> None:
    work_dir = Path(tempfile.mkdtemp(prefix=".easymean-update-", dir=ROOT))
    new_dir = work_dir / "new"
    backup_dir = work_dir / "backup"
    replaced: list[tuple[Path, Path | None]] = []
    try:
        new_dir.mkdir()
        backup_dir.mkdir()
        for name, content in files.items():
            target = ROOT / name
            if target.is_symlink():
                raise RuntimeError(f"拒绝覆盖符号链接：{name}")
            staged = new_dir / name
            staged.write_bytes(content)
            if target.exists():
                os.chmod(staged, target.stat().st_mode)

        for name in UPDATE_FILES:
            target = ROOT / name
            backup = backup_dir / name if target.exists() else None
            if backup:
                shutil.copy2(target, backup)
            os.replace(new_dir / name, target)
            replaced.append((target, backup))
    except Exception:
        for target, backup in reversed(replaced):
            if backup and backup.exists():
                os.replace(backup, target)
            elif target.exists():
                target.unlink()
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def main() -> int:
    git_result = update_with_git()
    if git_result is not None:
        return 0 if git_result else 1

    print("检测到 ZIP 版本，正在从 GitHub 下载最新版……")
    try:
        files = read_update_files(download_archive())
        validate(files)
        install(files)
    except Exception as exc:
        print(f"更新失败：{exc}")
        return 1

    print(f"更新完成，共替换 {len(files)} 个应用文件。")
    print("浏览器中的学习进度不会受到影响。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
