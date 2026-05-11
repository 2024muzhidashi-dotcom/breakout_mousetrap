import sys
from pathlib import Path
import pandas as pd
import numpy as np
import joblib

# 将项目根目录添加到路径
root_dir = Path(__file__).resolve().parents[1]
sys.path.append(str(root_dir))

from src.data_loader import load_local_ohlcv
from src.features import add_common_features
from ML.strategy_clean import (
    ChannelLevelStrategyConfig,
    generate_channel_level_signals,
    backtest_channel_level_strategy,
    _metrics
)
from src.levels import SupportResistanceConfig, detect_support_resistance_zones
from ML.features import extract_breakout_features

def run_ml_backtest(
    symbol: str, 
    timeframe: str = "15m", 
    prob_threshold: float = 0.5,
    initial_capital: float = 10.0,
    leverage: float = 50.0,
    position_pct: float = 0.08,
    mode: str = "tp1_50_be"
):
    print(f"\n开始对 {symbol} 进行 AI 过滤回测 (模式: {mode})...")
    print(f"参数: 初始资金={initial_capital}U, 杠杆={leverage}x, 仓位={position_pct*100}%, AI阈值={prob_threshold}")
    
    # 1. 加载模型
    model_path = root_dir / "ML" / "models" / "breakout_classifier.joblib"
    feature_names_path = root_dir / "ML" / "models" / "feature_names.joblib"
    
    if not model_path.exists():
        print("错误: 找不到训练好的模型，请先运行 ML/train.py")
        return
        
    model = joblib.load(model_path)
    feature_names = joblib.load(feature_names_path)
    
    # 2. 加载数据
    df = add_common_features(load_local_ohlcv(symbol, timeframe))
    
    # 3. 生成原始策略信号
    config = ChannelLevelStrategyConfig(
        verbose=False,
        initial_capital=initial_capital,
        leverage=leverage,
        position_pct=position_pct,
        mode=mode
    )
    data, signals = generate_channel_level_signals(df, config)
    
    if signals.empty:
        print("原始策略未产生任何信号。")
        return
        
    print(f"原始信号数量: {len(signals)}")
    
    # 4. 使用 AI 模型进行过滤
    # 提取支撑阻力位用于特征抓取
    zones, _ = detect_support_resistance_zones(df, SupportResistanceConfig())
    if not zones.empty:
        res_zones = zones[zones["current_role"] == "resistance"].copy()
        sup_zones = zones[zones["current_role"] == "support"].copy()
    else:
        res_zones = pd.DataFrame()
        sup_zones = pd.DataFrame()
    
    filtered_rows = []
    skipped_count = 0
    
    # 性能统计指标
    stats = {
        "correctly_filtered_fake": 0, # AI 说是假，实际也是假 (TN)
        "missed_real": 0,            # AI 说是假，实际是真 (FN)
        "caught_real": 0,            # AI 说是真，实际也是真 (TP)
        "failed_fake": 0,            # AI 说是真，实际是假 (FP)
        "total_real": 0,
        "total_fake": 0
    }

    print("正在逐一鉴定信号并分析结果...")
    for _, signal in signals.iterrows():
        # 1. 提取当前信号的特征
        breakout_idx = int(signal["entry_idx"])
        features_dict = extract_breakout_features(df, signal.to_dict(), breakout_idx, res_zones, sup_zones)
        
        if not features_dict:
            continue
            
        # 2. 预测概率
        features_df = pd.DataFrame([features_dict])[feature_names]
        prob = model.predict_proba(features_df)[0, 1]
        ai_decision = prob >= prob_threshold
        
        # 3. 鉴定实际结果 (Labeling Logic) - 严格按 TP2 鉴定
        direction = signal["direction"]
        entry_price = float(signal["entry_price"])
        tp2_price = float(signal["tp2"])
        sl_price = float(signal["stop_loss_price"])
        
        actual_is_real = False
        lookahead = 192 # 观察两天
        for i in range(breakout_idx + 1, min(breakout_idx + lookahead, len(df))):
            curr_high, curr_low = df.at[i, "high"], df.at[i, "low"]
            if direction == "long":
                if curr_high >= tp2_price:
                    actual_is_real = True; break
                if curr_low <= sl_price:
                    actual_is_real = False; break
            else: # short
                if curr_low <= tp2_price:
                    actual_is_real = True; break
                if curr_high >= sl_price:
                    actual_is_real = False; break
        
        if actual_is_real: stats["total_real"] += 1
        else: stats["total_fake"] += 1

        # 4. 对比 AI 决策与实际
        if ai_decision: # AI 决定入场
            if actual_is_real:
                stats["caught_real"] += 1
                signal_with_prob = signal.to_dict()
                signal_with_prob["ai_prob"] = prob
                filtered_rows.append(signal_with_prob)
            else:
                stats["failed_fake"] += 1
                signal_with_prob = signal.to_dict()
                signal_with_prob["ai_prob"] = prob
                filtered_rows.append(signal_with_prob)
        else: # AI 决定过滤
            if actual_is_real:
                stats["missed_real"] += 1
            else:
                stats["correctly_filtered_fake"] += 1
            skipped_count += 1
            
    filtered_signals = pd.DataFrame(filtered_rows)
    
    # 5. 执行回测
    trades, equity = pd.DataFrame(), pd.DataFrame()
    if not filtered_signals.empty:
        trades, equity, metrics = backtest_channel_level_strategy(data, filtered_signals, config)
    else:
        metrics = {"final_equity": initial_capital, "net_profit": 0, "win_rate": 0, "profit_factor": 0, "max_drawdown": 0, "total_trades": 0, "return_pct": 0}
        equity = pd.DataFrame([{"timestamp": data['timestamp'].iloc[0], "equity": initial_capital}, {"timestamp": data['timestamp'].iloc[-1], "equity": initial_capital}])

    # 6. 输出详细分析报告
    print("\n" + "="*40)
    print(f"NoFake_Breakout AI 过滤器深度分析 - {symbol} (模式: {mode})")
    print("-" * 40)
    print(f"原始信号总数: {len(signals)}")
    print(f"  - 实际为真的变盘 (达TP2): {stats['total_real']}")
    print(f"  - 实际为假的突破: {stats['total_fake']}")
    print("\nAI 过滤表现:")
    print(f"  ✅ 成功过滤掉的假突破: {stats['correctly_filtered_fake']} / {stats['total_fake']} (过滤率: {stats['correctly_filtered_fake']/max(1,stats['total_fake'])*100:.1f}%)")
    print(f"  ❌ 遗憾错过的真行情: {stats['missed_real']} / {stats['total_real']} (漏掉率: {stats['missed_real']/max(1,stats['total_real'])*100:.1f}%)")
    print(f"  🎯 成功抓到的真行情: {stats['caught_real']}")
    print(f"  ⚠️  没能躲过的假突破: {stats['failed_fake']}")
    
    print("\n回测财务指标:")
    print(f"最终资金: {metrics['final_equity']:.2f} USDT (净利: {metrics['net_profit']:.2f})")
    print(f"实战胜率: {metrics['win_rate']*100:.2f}%")
    print(f"最大回撤: {metrics['max_drawdown']*100:.2f}%")
    print("="*40)
    
    # 保存结果
    output_dir = root_dir / "backtests" / "ml_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    equity.to_csv(output_dir / f"{symbol.replace('/', '_')}_{mode}_ml_equity.csv", index=False)
    trades.to_csv(output_dir / f"{symbol.replace('/', '_')}_{mode}_ml_trades.csv", index=False)
    
    return metrics

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument("--threshold", type=float, default=0.50)
    parser.add_argument("--capital", type=float, default=10.0)
    parser.add_argument("--leverage", type=float, default=50.0)
    parser.add_argument("--pos_pct", type=float, default=0.08)
    parser.add_argument("--mode", type=str, choices=["tp1_50_be", "tp2_or_sl", "tp1_100"], default="tp1_50_be")
    args = parser.parse_args()
    
    run_ml_backtest(
        args.symbol, 
        prob_threshold=args.threshold,
        initial_capital=args.capital,
        leverage=args.leverage,
        position_pct=args.pos_pct,
        mode=args.mode
    )
