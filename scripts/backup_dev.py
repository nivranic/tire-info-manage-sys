"""本机数据备份工具（第61轮全局圆桌 G2-3 裁决）。

此前备份只有 README 手工作业说明（停写 + SQLite backup API + 三处数据缺一不可），
无任何可执行入口；服务运行中直接拷贝 .db 单文件会丢失 -wal 中已提交未 checkpoint
的事务。本工具补上可执行路径：

    python scripts/backup_dev.py [--data-dir data] [--output data/backups]

- 主库经 SQLite backup API 复制（源以只读模式打开，WAL 安全）；
- 对象目录 dev.db.objects/ 与 parser-bundles/ 一并复制（漏掉对象目录会使所有
  capture/document 读取 503）；
- 写入 manifest.json（schema 版本清单、字节与文件计数），供恢复时核对。

恢复仍是手工流程：停 API/Worker → 用备份目录内容替换 data/ 对应三项 → 重启
（见 README「原文对象、PDF 收件与备份」）。备份产物追加式保留，本工具不删除任何
旧备份。属本机运维工具：服务器部署形态必须替换为带异地保管的灾备方案。
"""
import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def backup_database(source: Path, target: Path) -> int:
    source_uri = f"file:{source.as_posix()}?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True)
    try:
        target_connection = sqlite3.connect(target.as_posix())
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
    finally:
        source_connection.close()
    return target.stat().st_size


def copy_tree(source: Path, target: Path) -> int:
    if not source.is_dir():
        return 0
    shutil.copytree(source, target)
    return sum(1 for item in target.rglob("*") if item.is_file())


def schema_versions(database: Path) -> list[str]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        return [row[0] for row in connection.execute("SELECT version FROM tire_schema_versions ORDER BY version")]
    except sqlite3.DatabaseError:
        return []
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="本机数据备份（SQLite backup API + 对象目录 + parser bundles）")
    parser.add_argument("--data-dir", default="data", help="数据目录（默认仓库根 data/）")
    parser.add_argument("--output", default=None, help="备份根目录（默认 <data-dir>/backups）")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    database = data_dir / "dev.db"
    if not database.is_file():
        raise SystemExit(f"主库不存在：{database}")
    output_root = Path(args.output) if args.output else data_dir / "backups"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = output_root / f"backup-{stamp}"
    if target.exists():
        raise SystemExit(f"备份目录已存在：{target}")

    target.mkdir(parents=True)
    db_bytes = backup_database(database, target / "dev.db")
    objects_count = copy_tree(data_dir / "dev.db.objects", target / "dev.db.objects")
    bundles_count = copy_tree(data_dir / "parser-bundles", target / "parser-bundles")
    manifest = {
        "tool": "scripts/backup_dev.py@1",
        "created_at": stamp,
        "database_bytes": db_bytes,
        "object_files": objects_count,
        "parser_bundle_files": bundles_count,
        "schema_versions": schema_versions(target / "dev.db"),
        "restore": "停 API/Worker 后以本目录内容替换 data/ 的 dev.db、dev.db.objects/、parser-bundles/ 三项再重启",
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "backup": str(target), "database_bytes": db_bytes,
                      "object_files": objects_count, "parser_bundle_files": bundles_count,
                      "schema_versions": len(manifest["schema_versions"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
