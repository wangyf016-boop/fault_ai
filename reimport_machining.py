"""
重新导入 Machining CSV 到 Qdrant

当前导入规则：
  - problem 字段：故障的现象描述 → problem
  - station 字段：设备 → station 
  - cause 字段：预测故障原因 → cause 
  - 嵌入文本质量：从仅含 action+line 变为 problem+cause+action+station+line 

用法: python reimport_machining.py
"""
import sys
import os
import csv
import re
import uuid
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from app.dataset.dataset_router import DatasetEmbeddingService
from app.retrievers.qdrant_store import QdrantVectorStore

COLLECTION = "Machining"
CSV_FILES = [
    ROOT / "Version2" / "Machining 2023.csv",
    ROOT / "Version2" / "Machining 2024.csv",
    ROOT / "Version2" / "Machining 2025.csv",
]
BATCH_SIZE = 50


def read_csv(path: Path) -> list:
    """读取 CSV，自动检测编码"""
    for enc in ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']:
        try:
            with open(path, 'r', encoding=enc) as f:
                reader = csv.DictReader(f)
                data = []
                source_year = ""
                m = re.search(r"(19|20)\d{2}", path.stem)
                if m:
                    source_year = m.group(0)
                for idx, row in enumerate(reader, start=2):
                    cleaned = {k.strip(): (v.strip() if v else '') for k, v in row.items()}
                    if not cleaned.get('id'):
                        cleaned['id'] = str(idx - 1)
                    cleaned['_source_row'] = str(idx)
                    cleaned['_source_year'] = source_year
                    cleaned['_source_file'] = path.name
                    data.append(cleaned)
                return data
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法读取: {path}")


def main():
    print("=" * 60)
    print("重新导入 Machining 数据到 Qdrant")
    print("   使用最新字段映射（cause 优先取 预测故障原因）+ 嵌入质量")
    print("=" * 60)

    svc = DatasetEmbeddingService()

    # 1. 读取所有 CSV
    all_data = []
    for csv_path in CSV_FILES:
        if not csv_path.exists():
            print(f"  跳过不存在的文件: {csv_path.name}")
            continue
        data = read_csv(csv_path)
        print(f"   {csv_path.name}: {len(data)} 条")
        # 标记来源
        for row in data:
            row['_source'] = csv_path.stem
        all_data.extend(data)

    print(f"\n总计: {len(all_data)} 条记录")

    # 2. 验证映射
    sample = all_data[0]
    print(f"\n映射验证 (第1条):")
    print(f"   line:    {svc._get_field(sample, 'line')!r}")
    print(f"   station: {svc._get_field(sample, 'station')!r}")
    print(f"   problem: {svc._get_field(sample, 'problem')!r}")
    print(f"   cause:   {svc._get_field(sample, 'cause')!r}")
    print(f"   action:  {svc._get_field(sample, 'action')!r}")
    print(f"   date:    {svc._get_date(sample)!r}")
    print(f"   text:    {svc.prepare_text(sample)}")

    # 确认
    ans = input(f"\n 即将删除旧 {COLLECTION} 集合并重新导入 {len(all_data)} 条记录。\n   预计耗时 ~{len(all_data) * 0.15 / 60:.0f} 分钟。继续？[y/N] ")
    if ans.strip().lower() != 'y':
        print("已取消。")
        return

    # 3. 删除旧 collection
    from qdrant_client import QdrantClient
    client = QdrantClient(host="localhost", port=6333)
    try:
        client.delete_collection(COLLECTION)
        print(f"\n 已删除旧 {COLLECTION} 集合")
    except Exception:
        pass

    # 4. 重新导入
    t0 = time.time()

    def progress(done, total):
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(f"   {done}/{total} ({done/total*100:.1f}%) - {rate:.1f} 条/秒 - 预计剩余 {eta/60:.1f} 分钟", end="\r")

    result = svc.embed_to_qdrant(all_data, COLLECTION, batch_size=BATCH_SIZE, progress_callback=progress)

    elapsed = time.time() - t0
    print(f"\n\n{'=' * 60}")
    print(f" 导入完成!")
    print(f"   集合: {result['collection']}")
    print(f"   成功: {result['success']} / {result['total']}")
    print(f"   耗时: {elapsed/60:.1f} 分钟 ({elapsed:.0f} 秒)")
    print(f"{'=' * 60}")

    # 5. 验证
    info = client.get_collection(COLLECTION)
    print(f"\n验证: {COLLECTION} 集合有 {info.points_count} 个点")

    # 抽样检查
    pts = client.scroll(COLLECTION, limit=1)
    if pts[0]:
        p = pts[0][0].payload
        print(f"   抽样: line={p.get('line')}, station={p.get('station')},")
        print(f"          problem={p.get('problem','')[:30]}, cause={p.get('cause','')[:20]}")


if __name__ == "__main__":
    main()
