import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
from tqdm import tqdm

# 将项目根目录添加到路径，以便导入 src
root_dir = Path(__file__).resolve().parents[1]
sys.path.append(str(root_dir))

from src.data_loader import load_local_ohlcv
from src.features import add_common_features
from src.market_structure import (
    StructureScanConfig,
    scan_consolidation_structures,
    merge_structure_candidates,
    annotate_structure_breakouts
)
from src.levels import SupportResistanceConfig, detect_support_resistance_zones
from ML.features import extract_breakout_features

from ML.strategy_clean import (
    ChannelLevelStrategyConfig,
    _find_breakout_entry,
)

def collect_samples(symbol: str, timeframe: str = "15m"):
    print(f"开始收集 {symbol} {timeframe} 的样本数据...")
    
    # 1. 加载数据并添加基础特征 (ATR等)
    try:
        df = add_common_features(load_local_ohlcv(symbol, timeframe))
    except FileNotFoundError:
        print(f"找不到本地数据 {symbol} {timeframe}，请先运行 fetch-symbol")
        return

    # 2. 扫描市场结构
    config = ChannelLevelStrategyConfig(verbose=False)
    scan_cfg = StructureScanConfig(breakout_hold_bars=0) 
    candidates = scan_consolidation_structures(df, scan_cfg)
    merged = merge_structure_candidates(candidates)
    tracked = annotate_structure_breakouts(df, merged, scan_cfg)
    
    if tracked.empty:
        print("未检测到任何市场结构。")
        return

    # 3. 提取特征并标注标签
    samples = []
    level_cache = {}
    
    # 获取全局支撑阻力用于特征计算
    zones_full, _ = detect_support_resistance_zones(df, SupportResistanceConfig())
    res_zones_full = zones_full[zones_full["current_role"] == "resistance"].copy()
    sup_zones_full = zones_full[zones_full["current_role"] == "support"].copy()

    for _, structure in tqdm(tracked.iterrows(), total=len(tracked), desc="Processing Structures"):
        # 使用策略逻辑判断该信号是否“合规”
        entry_params = _find_breakout_entry(df, structure, config, level_cache)
        if entry_params is None:
            continue
            
        breakout_idx = int(entry_params["entry_idx"])
        
        # 提取特征
        features = extract_breakout_features(df, structure.to_dict(), breakout_idx, res_zones_full, sup_zones_full)
        if not features:
            continue
            
        # --- 标注标签 (Labeling) ---
        # 严格标签：只有打到 TP2 才算真变盘 (1)，打到止损算假突破 (0)
        tp2_price = entry_params["tp2"]
        sl_price = entry_params["stop_loss_price"]
        direction = entry_params["direction"]
        
        label = None
        lookahead = 192 # 观察两天的时间 (15m * 192)
        
        for i in range(breakout_idx + 1, min(breakout_idx + lookahead, len(df))):
            curr_high, curr_low = df.at[i, "high"], df.at[i, "low"]
            
            if direction == "long":
                if curr_high >= tp2_price:
                    label = 1 # 达到 TP2，实打实的真行情
                    break
                if curr_low <= sl_price:
                    label = 0 # 达到止损，假突破
                    break
            else: # short
                if curr_low <= tp2_price:
                    label = 1 # 达到 TP2，实打实的真行情
                    break
                if curr_high >= sl_price:
                    label = 0 # 达到止损，假突破
                    break
        
        if label is not None:
            features["label"] = label
            samples.append(features)

    if not samples:
        print("没有收集到有效的标注样本。")
        return

    samples_df = pd.DataFrame(samples)
    output_path = root_dir / "ML" / "data" / f"{symbol.replace('/', '_')}_{timeframe}_samples.csv"
    samples_df.to_csv(output_path, index=False)
    print(f"收集完成！共 {len(samples_df)} 个样本，保存至: {output_path}")
    print(f"标签分布: \n{samples_df['label'].value_counts()}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument("--timeframe", type=str, default="15m")
    args = parser.parse_args()
    
    collect_samples(args.symbol, args.timeframe)
