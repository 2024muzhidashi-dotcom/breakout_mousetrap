from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# 导入原有 src 中的依赖
from src.levels import SupportResistanceConfig, detect_support_resistance_zones
from src.market_structure import (
    StructureScanConfig,
    _candle_stall,
    _structure_line_at,
    annotate_structure_breakouts,
    merge_structure_candidates,
    scan_consolidation_structures,
)

@dataclass
class ChannelLevelStrategyConfig:
    initial_capital: float = 10.0
    position_pct: float = 0.05
    leverage: float = 100.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    recent_days: int = 730
    level_lookback_days: int = 45
    max_retest_bars: int = 32
    retest_tolerance_atr: float = 0.70
    stop_buffer_atr: float = 0.35
    target_min_gap_atr: float = 0.25
    tp2_inset_atr: float = 0.45
    min_tp2_rr: float = 1.5
    min_expected_tp2_net_bps: float = 2.0
    max_holding_bars: int = 384
    min_bars_between_entries: int = 4
    verbose: bool = True
    # 策略模式: 'tp1_50_be' (50%止盈+保本), 'tp2_or_sl' (纯TP2/SL), 'tp1_100' (TP1全平)
    mode: str = "tp1_50_be"

def _prepare_data(df_15m: pd.DataFrame, recent_days: int) -> pd.DataFrame:
    data = df_15m.copy().sort_values("timestamp").reset_index(drop=True)
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    if recent_days > 0 and not data.empty:
        cutoff = data["timestamp"].iloc[-1] - pd.Timedelta(days=recent_days)
        data = data[data["timestamp"] >= cutoff].copy().reset_index(drop=True)
    return data

def _line_at_trade_time(structure: pd.Series | dict[str, Any], timestamp: pd.Timestamp, direction: str) -> float:
    if direction == "long":
        return float(structure["upper_end"])
    return float(structure["lower_end"])

def _opposite_stop_line(structure: pd.Series | dict[str, Any], timestamp: pd.Timestamp, direction: str) -> float:
    if direction == "long":
        return min(float(structure["lower_start"]), float(structure["lower_end"]))
    return max(float(structure["upper_start"]), float(structure["upper_end"]))

def _entry_stop_price(structure: pd.Series | dict[str, Any], timestamp: pd.Timestamp, direction: str, atr: float, cfg: ChannelLevelStrategyConfig) -> float:
    invalidation_line = _opposite_stop_line(structure, timestamp, direction)
    buffer = atr * cfg.stop_buffer_atr
    if direction == "long":
        return invalidation_line - buffer
    return invalidation_line + buffer

def _find_targets(
    data: pd.DataFrame,
    entry_idx: int,
    direction: str,
    entry_price: float,
    atr: float,
    cfg: ChannelLevelStrategyConfig,
    level_cache: dict[tuple[int, str], pd.DataFrame] | None = None,
    min_tp2_distance: float | None = None,
) -> dict[str, Any] | None:
    entry_time = pd.to_datetime(data.at[entry_idx, "timestamp"], utc=True)
    cache_key = (entry_idx // 96, direction)
    zones = level_cache.get(cache_key) if level_cache is not None else None
    if zones is None:
        start_time = entry_time - pd.Timedelta(days=cfg.level_lookback_days)
        context = data[(data["timestamp"] <= entry_time) & (data["timestamp"] >= start_time)].copy().reset_index(drop=True)
        if len(context) < 120:
            context = data.iloc[: entry_idx + 1].tail(240).copy().reset_index(drop=True)
        if len(context) < 80:
            return None
        zones, _ = detect_support_resistance_zones(context, SupportResistanceConfig())
        if level_cache is not None:
            level_cache[cache_key] = zones
    if zones.empty:
        return None
    min_gap = max(atr * cfg.target_min_gap_atr, 1e-9)
    zones = zones.copy()
    if direction == "long":
        candidates = zones[zones["zone_low"] > entry_price + min_gap].copy()
        candidates = candidates.sort_values(["zone_low", "strength_score"], ascending=[True, False])
        if len(candidates) < 2:
            return None
        tp1_zone = candidates.iloc[0]
        tp2_candidates = candidates.iloc[1:].copy()
        if min_tp2_distance is not None:
            required_raw_tp2 = entry_price + min_tp2_distance + atr * cfg.tp2_inset_atr
            tp2_candidates = tp2_candidates[tp2_candidates["zone_low"] >= required_raw_tp2]
        if tp2_candidates.empty:
            return None
        tp2_zone = tp2_candidates.iloc[0]
        tp1 = float(tp1_zone["zone_low"])
        raw_tp2 = float(tp2_zone["zone_low"])
        tp2 = max(tp1 + min_gap, raw_tp2 - atr * cfg.tp2_inset_atr)
        target_reason = "做多第一目标看上方最近压力区前沿，第二目标看再上方压力区前沿，但TP2稍微向内收，避免差一点摸不到。"
    else:
        candidates = zones[zones["zone_high"] < entry_price - min_gap].copy()
        candidates = candidates.sort_values(["zone_high", "strength_score"], ascending=[False, False])
        if len(candidates) < 2:
            return None
        tp1_zone = candidates.iloc[0]
        tp2_candidates = candidates.iloc[1:].copy()
        if min_tp2_distance is not None:
            required_raw_tp2 = entry_price - min_tp2_distance - atr * cfg.tp2_inset_atr
            tp2_candidates = tp2_candidates[tp2_candidates["zone_high"] <= required_raw_tp2]
        if tp2_candidates.empty:
            return None
        tp2_zone = tp2_candidates.iloc[0]
        tp1 = float(tp1_zone["zone_high"])
        raw_tp2 = float(tp2_zone["zone_high"])
        tp2 = min(tp1 - min_gap, raw_tp2 + atr * cfg.tp2_inset_atr)
        target_reason = "做空第一目标看下方最近支撑区前沿，第二目标看再下方支撑区前沿，但TP2稍微向内收，避免差一点摸不到。"
    return {
        "tp1": tp1,
        "tp2": tp2,
        "tp1_zone_id": str(tp1_zone["zone_id"]),
        "tp2_zone_id": str(tp2_zone["zone_id"]),
        "tp1_zone_low": float(tp1_zone["zone_low"]),
        "tp1_zone_high": float(tp1_zone["zone_high"]),
        "tp2_zone_low": float(tp2_zone["zone_low"]),
        "tp2_zone_high": float(tp2_zone["zone_high"]),
        "tp1_zone_strength": float(tp1_zone["strength_score"]),
        "tp2_zone_strength": float(tp2_zone["strength_score"]),
        "target_reason": target_reason,
    }

def _find_breakout_entry(
    data: pd.DataFrame,
    structure: pd.Series,
    cfg: ChannelLevelStrategyConfig,
    level_cache: dict[tuple[int, str], pd.DataFrame] | None = None,
) -> dict[str, Any] | None:
    breakout_time = pd.to_datetime(structure.get("breakout_time", pd.NaT), utc=True)
    breakout_direction = str(structure.get("breakout_direction", "pending"))
    if pd.isna(breakout_time) or breakout_direction not in {"up", "down"}:
        return None
    direction = "long" if breakout_direction == "up" else "short"
    breakout_positions = data.index[data["timestamp"] == breakout_time]
    if len(breakout_positions) == 0:
        return None
    breakout_idx = int(breakout_positions[0])
    candle = data.iloc[breakout_idx]
    timestamp = pd.to_datetime(candle["timestamp"], utc=True)
    atr = float(candle.get("atr14", np.nan))
    if not np.isfinite(atr) or atr <= 0:
        return None
    entry_price = float(candle["close"])
    broken_line = _line_at_trade_time(structure, timestamp, direction)
    stop_price = _entry_stop_price(structure, timestamp, direction, atr, cfg)
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return None
    targets = _find_targets(
        data,
        breakout_idx,
        direction,
        entry_price,
        atr,
        cfg,
        level_cache,
        min_tp2_distance=risk * cfg.min_tp2_rr,
    )
    if targets is None:
        return None
    if direction == "long" and not (stop_price < entry_price < targets["tp1"] < targets["tp2"]):
        return None
    if direction == "short" and not (stop_price > entry_price > targets["tp1"] > targets["tp2"]):
        return None
    reward_1 = abs(targets["tp1"] - entry_price)
    reward_2 = abs(targets["tp2"] - entry_price)
    expected_net_bps = _expected_two_target_net_bps(direction, entry_price, targets["tp1"], targets["tp2"], cfg)
    if expected_net_bps < cfg.min_expected_tp2_net_bps:
        return None
    return {
        "signal_time": timestamp,
        "entry_idx": breakout_idx,
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss_price": stop_price,
        "channel_broken_line_price": broken_line,
        "channel_opposite_line_price": _opposite_stop_line(structure, timestamp, direction),
        "risk_reward_tp1": reward_1 / risk,
        "risk_reward_tp2": reward_2 / risk,
        "expected_tp2_net_bps": expected_net_bps,
        "entry_reason": (
            "15分钟通道成熟后向上出现有力度实体突破，直接按变盘多单上车。"
            if direction == "long"
            else "15分钟通道成熟后向下出现有力度实体跌破，直接按变盘空单上车。"
        ),
        "stop_reason": (
            "做多止损放在突破时对应的通道下沿下方一点，跌穿通道另一侧才说明变盘失败。"
            if direction == "long"
            else "做空止损放在跌破时对应的通道上沿上方一点，突破通道另一侧才说明变盘失败。"
        ),
        **targets,
    }

def generate_channel_level_signals(
    df_15m: pd.DataFrame,
    cfg: ChannelLevelStrategyConfig | None = None,
    structure_cfg: StructureScanConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = cfg or ChannelLevelStrategyConfig()
    scan_cfg = structure_cfg or StructureScanConfig(breakout_hold_bars=0)
    data = _prepare_data(df_15m, config.recent_days)
    if data.empty:
        return data, pd.DataFrame()
    if config.verbose:
        print(f"[1/4] Scanning channels on {len(data)} candles...", flush=True)
    candidates = scan_consolidation_structures(data, scan_cfg)
    if config.verbose:
        print(f"[2/4] Raw channel candidates: {len(candidates)}", flush=True)
    merged = merge_structure_candidates(candidates)
    if config.verbose:
        print(f"[3/4] Merged channel regions: {len(merged)}", flush=True)
    tracked = annotate_structure_breakouts(data, merged, scan_cfg)
    if tracked.empty:
        return data, tracked
    if config.verbose:
        print(f"[4/4] Tracking strong breakouts for {len(tracked)} regions...", flush=True)
    rows: list[dict[str, Any]] = []
    last_entry_idx = -10_000
    level_cache: dict[tuple[int, str], pd.DataFrame] = {}
    tracked = tracked.sort_values(["breakout_time", "timestamp"], na_position="last").reset_index(drop=True)
    for structure_id, (_, structure) in enumerate(tracked.iterrows(), start=1):
        if config.verbose and structure_id % 50 == 0:
            print(f"      checked {structure_id}/{len(tracked)} regions, signals={len(rows)}", flush=True)
        breakout_time = pd.to_datetime(structure.get("breakout_time", pd.NaT), utc=True)
        known_time = max(pd.to_datetime(structure["timestamp"], utc=True), pd.to_datetime(structure["window_end"], utc=True))
        if pd.isna(breakout_time) or breakout_time <= known_time:
            continue
        entry = _find_breakout_entry(data, structure, config, level_cache)
        if entry is None:
            continue
        if int(entry["entry_idx"]) - last_entry_idx < config.min_bars_between_entries:
            continue
        last_entry_idx = int(entry["entry_idx"])
        row = structure.to_dict()
        row.update(entry)
        row["structure_id"] = f"CH{structure_id:04d}"
        row["is_reverse"] = False
        rows.append(row)
    signals = pd.DataFrame(rows)
    if not signals.empty:
        for col in ["timestamp", "window_start", "window_end", "follow_end", "breakout_time", "signal_time"]:
            if col in signals.columns:
                signals[col] = pd.to_datetime(signals[col], utc=True, errors="coerce")
        signals = signals.sort_values("signal_time").reset_index(drop=True)
    if config.verbose:
        print(f"      final tradable signals: {len(signals)}", flush=True)
    return data, signals

def _apply_slippage(price: float, direction: str, action: str, slippage_bps: float) -> float:
    slip = slippage_bps / 10000.0
    if action == "entry":
        return price * (1.0 + slip) if direction == "long" else price * (1.0 - slip)
    return price * (1.0 - slip) if direction == "long" else price * (1.0 + slip)

def _gross_pnl(direction: str, entry_price: float, exit_price: float, notional: float) -> float:
    if direction == "long":
        return (exit_price - entry_price) * notional / entry_price
    return (entry_price - exit_price) * notional / entry_price

def _expected_two_target_net_bps(
    direction: str,
    entry_price: float,
    tp1: float,
    tp2: float,
    cfg: ChannelLevelStrategyConfig,
) -> float:
    entry_fill = _apply_slippage(entry_price, direction, "entry", cfg.slippage_bps)
    tp1_fill = _apply_slippage(tp1, direction, "exit", cfg.slippage_bps)
    tp2_fill = _apply_slippage(tp2, direction, "exit", cfg.slippage_bps)
    pnl_per_notional = (
        _gross_pnl(direction, entry_fill, tp1_fill, 0.5)
        + _gross_pnl(direction, entry_fill, tp2_fill, 0.5)
        - (cfg.fee_bps / 10000.0) * 2.0
    )
    return pnl_per_notional * 10000.0

def _close_trade(
    trade: dict[str, Any],
    exit_idx: int,
    exit_time: pd.Timestamp,
    exit_price_raw: float,
    exit_reason: str,
    final_size_fraction: float,
    equity_before: float,
    cfg: ChannelLevelStrategyConfig,
) -> dict[str, Any]:
    direction = str(trade["direction"])
    entry_fill = float(trade["entry_fill_price"])
    exit_fill = _apply_slippage(exit_price_raw, direction, "exit", cfg.slippage_bps)
    remaining_notional = float(trade["notional"]) * final_size_fraction
    exit_fee = remaining_notional * cfg.fee_bps / 10000.0
    pnl = _gross_pnl(direction, entry_fill, exit_fill, remaining_notional) - exit_fee
    trade["pnl_amount"] += pnl
    trade["fees_paid"] += exit_fee
    trade["exit_idx"] = exit_idx
    trade["exit_time"] = exit_time
    trade["exit_price"] = exit_price_raw
    trade["exit_fill_price"] = exit_fill
    trade["exit_reason"] = exit_reason
    trade["equity_before"] = equity_before
    trade["equity_after"] = equity_before + float(trade["pnl_amount"])
    trade["pnl_pct_equity"] = float(trade["pnl_amount"]) / max(equity_before, 1e-9)
    risk = abs(float(trade["entry_price"]) - float(trade["stop_loss_price"]))
    reward = float(trade["pnl_amount"]) / max(float(trade["notional"]) * risk / max(float(trade["entry_price"]), 1e-9), 1e-9)
    trade["r_multiple"] = reward
    return trade

def backtest_channel_level_strategy(
    data: pd.DataFrame,
    signals: pd.DataFrame,
    cfg: ChannelLevelStrategyConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    config = cfg or ChannelLevelStrategyConfig()
    candles = data.copy().sort_values("timestamp").reset_index(drop=True)
    if signals.empty:
        equity_df = candles[["timestamp"]].copy()
        equity_df["equity"] = config.initial_capital
        return pd.DataFrame(), equity_df, _metrics(pd.DataFrame(), equity_df, config)

    signal_by_idx: dict[int, list[dict[str, Any]]] = {}
    for _, signal in signals.iterrows():
        idx = int(signal["entry_idx"])
        signal_by_idx.setdefault(idx, []).append(signal.to_dict())

    equity = config.initial_capital
    position: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    trade_seq = 0

    for idx, candle in candles.iterrows():
        timestamp = pd.to_datetime(candle["timestamp"], utc=True)
        high, low, close = float(candle["high"]), float(candle["low"]), float(candle["close"])

        if position is not None:
            direction = str(position["direction"])
            stop = float(position["active_stop_price"])
            tp1, tp2 = float(position["tp1"]), float(position["tp2"])
            final_exit = None

            if direction == "long":
                if low <= stop:
                    if config.mode == "tp1_50_be" and position["tp1_hit"]:
                        exit_reason = "breakeven_stop"
                    else:
                        exit_reason = "stop_loss"
                    final_exit = (exit_reason, stop)
                elif not position["tp1_hit"] and high >= tp1:
                    position["tp1_hit"] = True
                    position["tp1_time"] = timestamp
                    if config.mode == "tp1_100":
                        final_exit = ("take_profit_1", tp1)
                    elif config.mode == "tp1_50_be":
                        position = _close_trade(position, idx, timestamp, tp1, "take_profit_1", 0.5, equity, config)
                        equity = float(position["equity_after"])
                        position["active_stop_price"] = float(position["entry_fill_price"])
                elif position["tp1_hit"] and high >= tp2:
                    final_exit = ("take_profit_2", tp2)
                elif not position["tp1_hit"] and high >= tp2:
                    final_exit = ("take_profit_2", tp2)
            else:
                if high >= stop:
                    if config.mode == "tp1_50_be" and position["tp1_hit"]:
                        exit_reason = "breakeven_stop"
                    else:
                        exit_reason = "stop_loss"
                    final_exit = (exit_reason, stop)
                elif not position["tp1_hit"] and low <= tp1:
                    position["tp1_hit"] = True
                    position["tp1_time"] = timestamp
                    if config.mode == "tp1_100":
                        final_exit = ("take_profit_1", tp1)
                    elif config.mode == "tp1_50_be":
                        position = _close_trade(position, idx, timestamp, tp1, "take_profit_1", 0.5, equity, config)
                        equity = float(position["equity_after"])
                        position["active_stop_price"] = float(position["entry_fill_price"])
                elif position["tp1_hit"] and low <= tp2:
                    final_exit = ("take_profit_2", tp2)
                elif not position["tp1_hit"] and low <= tp2:
                    final_exit = ("take_profit_2", tp2)

            if final_exit is None and idx - int(position["entry_idx"]) >= config.max_holding_bars:
                final_exit = ("time_exit", close)

            if final_exit is not None:
                exit_reason, exit_price = final_exit
                remaining_fraction = 0.5 if (config.mode == "tp1_50_be" and position["tp1_hit"]) else 1.0
                closed = _close_trade(position, idx, timestamp, exit_price, exit_reason, remaining_fraction, equity, config)
                equity = float(closed["equity_after"])
                trades.append(closed)
                position = None

        if position is None:
            if idx in signal_by_idx:
                signal = signal_by_idx[idx][0]
                trade_seq += 1
                entry_fill = _apply_slippage(float(signal["entry_price"]), str(signal["direction"]), "entry", config.slippage_bps)
                margin = equity * config.position_pct
                notional = margin * config.leverage
                entry_fee = notional * config.fee_bps / 10000.0
                position = dict(signal)
                position.update({
                    "trade_id": f"T{trade_seq:04d}",
                    "entry_idx": idx, "entry_time": timestamp,
                    "entry_fill_price": entry_fill, "active_stop_price": float(signal["stop_loss_price"]),
                    "margin_used": margin, "notional": notional,
                    "pnl_amount": -entry_fee, "fees_paid": entry_fee,
                    "tp1_hit": False, "tp1_time": pd.NaT, "tp1_fill_price": np.nan, "equity_at_entry": equity,
                })

        floating = _gross_pnl(str(position["direction"]), float(position["entry_fill_price"]), close, float(position["notional"])) if position else 0.0
        equity_curve.append({"timestamp": timestamp, "equity": equity + floating})

    trades_df, equity_df = pd.DataFrame(trades), pd.DataFrame(equity_curve)
    return trades_df, equity_df, _metrics(trades_df, equity_df, config)

def _max_consecutive_losses(trades_df: pd.DataFrame) -> int:
    max_losses = 0
    current = 0
    for pnl in trades_df.get("pnl_amount", pd.Series(dtype=float)).to_numpy(dtype=float):
        if pnl < 0:
            current += 1
            max_losses = max(max_losses, current)
        else:
            current = 0
    return max_losses

def _metrics(trades_df: pd.DataFrame, equity_df: pd.DataFrame, cfg: ChannelLevelStrategyConfig) -> dict[str, Any]:
    if equity_df.empty:
        final_equity = cfg.initial_capital
        max_drawdown = 0.0
    else:
        final_equity = float(equity_df["equity"].iloc[-1])
        running_max = equity_df["equity"].cummax()
        drawdown = equity_df["equity"] / running_max.replace(0, np.nan) - 1.0
        max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    if trades_df.empty:
        return {
            "initial_capital": cfg.initial_capital,
            "final_equity": final_equity,
            "net_profit": final_equity - cfg.initial_capital,
            "return_pct": (final_equity / cfg.initial_capital - 1.0) if cfg.initial_capital else 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": max_drawdown,
            "max_consecutive_losses": 0,
        }
    pnl = trades_df["pnl_amount"].astype(float)
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())
    return {
        "initial_capital": cfg.initial_capital,
        "final_equity": final_equity,
        "net_profit": final_equity - cfg.initial_capital,
        "return_pct": (final_equity / cfg.initial_capital - 1.0) if cfg.initial_capital else 0.0,
        "total_trades": int(len(trades_df)),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        "max_drawdown": max_drawdown,
        "max_consecutive_losses": _max_consecutive_losses(trades_df),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_pnl": float(pnl.mean()),
        "median_pnl": float(pnl.median()),
    }

def run_channel_level_strategy(
    df_15m: pd.DataFrame,
    cfg: ChannelLevelStrategyConfig | None = None,
    structure_cfg: StructureScanConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    config = cfg or ChannelLevelStrategyConfig()
    data, signals = generate_channel_level_signals(df_15m, config, structure_cfg)
    if config.verbose:
        print("Backtesting AI-optimized strategy (No Reversal)...", flush=True)
    trades, equity, metrics = backtest_channel_level_strategy(data, signals, config)
    if config.verbose:
        print(f"Backtest complete: trades={len(trades)}, final_equity={metrics['final_equity']:.4f}", flush=True)
    return data, signals, trades, equity, metrics
