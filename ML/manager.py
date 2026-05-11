import sys
import subprocess
from pathlib import Path

# 项目根目录
root_dir = Path(__file__).resolve().parents[1]

# 选取 OKX 上成交量较大、流动性好的主流币种
SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"
]

def run_command(cmd: list[str]):
    print(f"执行命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"命令执行失败，退出码: {result.returncode}")
    return result.returncode == 0

def batch_process(months: int = 36):
    """
    分步处理：每一个币种处理完后，再处理下一个。
    这样内存中永远只有一份数据，不会撑爆电脑。
    """
    all_sample_files = []
    
    for symbol in SYMBOLS:
        print(f"\n{'='*20} 正在处理: {symbol} {'='*20}")
        
        # 1. 下载 15m 数据 (仅 15m，用于初步扫描结构)
        fetch_success = run_command([
            "python3", str(root_dir / "main.py"), 
            "fetch-symbol", 
            "--symbol", symbol, 
            "--months", str(months),
            "--timeframes", "15m"
        ])
        
        if not fetch_success:
            print(f"跳过 {symbol}: 数据获取失败")
            continue
            
        # 2. 收集样本 (ML/collector.py)
        collect_success = run_command([
            "python3", str(root_dir / "ML" / "collector.py"), 
            "--symbol", symbol
        ])
        
        if collect_success:
            sample_file = root_dir / "ML" / "data" / f"{symbol.replace('/', '_')}_15m_samples.csv"
            if sample_file.exists():
                all_sample_files.append(sample_file)
                # 提取完特征后，如果想节省空间，可以手动删除 data/ 里的原始大 CSV
                # 但这里我们先保留，除非你磁盘空间非常紧张
        
    # 3. 合并所有样本
    if all_sample_files:
        print("\n正在合并所有币种的样本数据...")
        dfs = [pd.read_csv(f) for f in all_sample_files]
        master_df = pd.concat(dfs, ignore_index=True)
        master_path = root_dir / "ML" / "data" / "master_breakout_samples.csv"
        master_df.to_csv(master_path, index=False)
        print(f"所有样本已汇总至: {master_path}")
        print(f"总计样本量: {len(master_df)}")
        print(f"标签分布: \n{master_df['label'].value_counts()}")

if __name__ == "__main__":
    import pandas as pd # 仅在最后合并时需要
    batch_process(months=36) # 默认抓取3年数据
