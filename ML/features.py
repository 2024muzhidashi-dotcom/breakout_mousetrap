from __future__ import annotations

from typing import Any
import pandas as pd
import numpy as np

def extract_breakout_features(
    df: pd.DataFrame,
    structure: dict[str, Any],
    breakout_idx: int,
    resistance_zones: pd.DataFrame | None = None,
    support_zones: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    提取变盘时刻的价格行为特征向量。
    """
    # 基础信息定位
    try:
        window_start_idx = df.index[df["timestamp"] == structure["window_start"]][0]
        window_end_idx = df.index[df["timestamp"] == structure["window_end"]][0]
    except (IndexError, KeyError):
        return {}

    zone_df = df.iloc[window_start_idx : window_end_idx + 1]
    
    # 1. 收敛区几何特征 (Zone Geometry)
    duration = len(zone_df)
    narrowing = structure["gap_end"] / max(structure["gap_start"], 1e-9)
    
    # 2. 突破K线行为 (Breakout PA)
    breakout_candle = df.iloc[breakout_idx]
    atr = breakout_candle.get("atr14", 1e-9)
    body = abs(breakout_candle["close"] - breakout_candle["open"])
    candle_range = max(breakout_candle["high"] - breakout_candle["low"], 1e-9)
    
    direction = structure.get("breakout_direction", "up")
    if direction == "up":
        wick = breakout_candle["high"] - max(breakout_candle["open"], breakout_candle["close"])
    else:
        wick = min(breakout_candle["open"], breakout_candle["close"]) - breakout_candle["low"]
    
    wick_ratio = wick / candle_range
    avg_vol = zone_df["volume"].mean()
    vol_ratio = breakout_candle["volume"] / max(avg_vol, 1e-9)
    
    # 3. 前序背景趋势 (Pre-context)
    # 我们看进入收敛区前 2 倍收敛区长度的趋势
    pre_context_len = min(duration * 2, window_start_idx)
    if pre_context_len > 10:
        pre_df = df.iloc[window_start_idx - pre_context_len : window_start_idx]
        pre_trend = (pre_df["close"].iloc[-1] - pre_df["close"].iloc[0]) / pre_df["close"].iloc[0]
        pre_atr = pre_df["atr14"].mean()
    else:
        pre_trend = 0.0
        pre_atr = atr

    # 4. 相对位置 (Relative Position)
    current_price = breakout_candle["close"]
    
    # 距离阻力位/支撑位
    dist_res = 1.0 
    dist_sup = 1.0
    if resistance_zones is not None and not resistance_zones.empty:
        above = resistance_zones[resistance_zones["zone_low"] > current_price]
        if not above.empty:
            dist_res = (above["zone_low"].min() - current_price) / current_price
            
    if support_zones is not None and not support_zones.empty:
        below = support_zones[support_zones["zone_high"] < current_price]
        if not below.empty:
            dist_sup = (current_price - below["zone_high"].max()) / current_price

    # 在最近大周期区间的位置 (0=底部, 1=顶部)
    lookback_range = 200
    range_start = max(0, breakout_idx - lookback_range)
    range_df = df.iloc[range_start : breakout_idx + 1]
    r_high = range_df["high"].max()
    r_low = range_df["low"].min()
    pos_in_range = (current_price - r_low) / max(r_high - r_low, 1e-9)

    return {
        "timestamp": breakout_candle["timestamp"],
        "direction": direction,
        "zone_duration": duration,
        "narrowing_ratio": narrowing,
        "peak_touches": structure["peak_touches"],
        "valley_touches": structure["valley_touches"],
        "alternations": structure["alternations"],
        "breakout_body_atr": body / atr,
        "breakout_wick_ratio": wick_ratio,
        "breakout_vol_ratio": vol_ratio,
        "pre_trend": pre_trend,
        "volatility_contraction": atr / max(pre_atr, 1e-9),
        "dist_to_res": dist_res,
        "dist_to_sup": dist_sup,
        "pos_in_range": pos_in_range,
    }
