import sys
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from dateutil import parser
import pandas as pd

# 将项目根目录添加到路径
root_dir = Path(__file__).resolve().parents[1]
sys.path.append(str(root_dir))

from src.data_loader import OKXPerpDataLoader
from src.features import add_common_features
from src.market_structure import StructureScanConfig, scan_consolidation_structures, merge_structure_candidates, annotate_structure_breakouts
from src.channel_level_strategy import ChannelLevelStrategyConfig, _find_breakout_entry

def get_all_active_usdt_swaps(loader: OKXPerpDataLoader) -> list[str]:
    loader.exchange.load_markets()
    symbols = []
    for symbol, market in loader.exchange.markets.items():
        if market.get('swap') and market.get('settle') == 'USDT' and market.get('active'):
            symbols.append(symbol)
    return sorted(symbols)

def fetch_recent_data(loader: OKXPerpDataLoader, symbol: str, timeframe: str = "15m", limit: int = 400) -> pd.DataFrame:
    try:
        rows = loader.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return add_common_features(df)
    except Exception as e:
        return pd.DataFrame()

def run_radar_cycle():
    state_file = root_dir / "radar" / "state.json"
    state = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "watch_list": [],  # 正在酝酿的通道
        "breakouts": [],   # 刚刚突破的变盘点
        "missed": []       # 过去48小时错过的变盘点
    }
    
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                saved_state = json.load(f)
                state.update(saved_state)
        except Exception:
            pass
            
    last_full_scan_str = state.get("last_full_scan")
    current_time = datetime.now(timezone.utc)
    
    if last_full_scan_str:
        try:
            last_full_scan = parser.parse(last_full_scan_str)
            minutes_since_full = (current_time - last_full_scan).total_seconds() / 60.0
        except Exception:
            minutes_since_full = 99999
    else:
        minutes_since_full = 99999
        
    # 如果 missed 列表为空，或者距离上次超过 15 分钟，执行全网扫描
    is_full_scan = minutes_since_full >= 15 or len(state.get("missed", [])) == 0
    
    loader = OKXPerpDataLoader()
    config = ChannelLevelStrategyConfig(verbose=False)
    scan_cfg = StructureScanConfig(breakout_hold_bars=0)
    
    if is_full_scan:
        print(f"\n--- 执行【全网海选扫描】 (寻找新的酝酿中通道和错过的行情) ---")
        symbols_to_scan = get_all_active_usdt_swaps(loader)
        state["watch_list"] = [] 
        state["last_full_scan"] = current_time.isoformat()
    else:
        symbols_to_scan = [w["symbol"] for w in state.get("watch_list", [])]
        symbols_to_scan = list(set(symbols_to_scan)) 
        print(f"\n--- 执行【高频狙击扫描】 (监控左侧列表的 {len(symbols_to_scan)} 个币种) ---")
        if not symbols_to_scan:
            print("当前酝酿列表为空，跳过高频扫描。等待下一次全网海选...")
            return

    new_breakouts = []
    new_missed = []
    new_watchlist = [] if is_full_scan else state.get("watch_list", [])
    
    for i, symbol in enumerate(symbols_to_scan):
        print(f"扫描进度 [{i+1}/{len(symbols_to_scan)}]: {symbol}   ", end="\r")
        df = fetch_recent_data(loader, symbol, "15m", limit=400) # 扩大拉取范围以便找到过去48h的记录
        if df.empty or len(df) < 50:
            continue
            
        latest_timestamp = df["timestamp"].iloc[-1]
        
        candidates = scan_consolidation_structures(df, scan_cfg)
        merged = merge_structure_candidates(candidates)
        tracked = annotate_structure_breakouts(df, merged, scan_cfg)
        
        if tracked.empty:
            if not is_full_scan:
                new_watchlist = [w for w in new_watchlist if w["symbol"] != symbol]
            continue
            
        symbol_still_forming = False
        
        for _, structure in tracked.iterrows():
            breakout_time_raw = structure.get("breakout_time", pd.NaT)
            window_end = pd.to_datetime(structure["window_end"], utc=True)
            gap = structure["gap_end"] / max(structure["gap_start"], 1e-9)
            
            # --- 判别 Watchlist (正在酝酿) ---
            if pd.isna(breakout_time_raw):
                bars_since_end = (latest_timestamp - window_end).total_seconds() / (15 * 60)
                if bars_since_end <= 5 and (structure["peak_touches"] >= 3 or structure["valley_touches"] >= 3):
                    symbol_still_forming = True
                    if is_full_scan:
                        new_watchlist.append({
                            "symbol": symbol,
                            "type": "Channel",
                            "status": "Forming",
                            "touches": f"Top: {structure['peak_touches']}, Bot: {structure['valley_touches']}",
                            "narrowing": f"{gap:.2f}",
                            "last_update": window_end.isoformat()
                        })
                    continue 
            
            # --- 判别 Breakout (变盘点) 和 Missed (错过的) ---
            breakout_time = pd.to_datetime(breakout_time_raw, utc=True)
            if not pd.isna(breakout_time):
                bars_since_breakout = (latest_timestamp - breakout_time).total_seconds() / (15 * 60)
                max_bars_ago = 4 if is_full_scan else 1
                
                entry = _find_breakout_entry(df, structure, config, level_cache={})
                if entry is not None:
                    breakout_data = {
                        "symbol": symbol,
                        "direction": "LONG" if entry["direction"] == "long" else "SHORT",
                        "entry_price": f"{entry['entry_price']:.4f}",
                        "stop_loss": f"{entry['stop_loss_price']:.4f}",
                        "tp1": f"{entry['tp1']:.4f}",
                        "tp2": f"{entry['tp2']:.4f}",
                        "breakout_time": breakout_time.isoformat(),
                        "reason": entry["entry_reason"]
                    }
                    
                    if 0 <= bars_since_breakout <= max_bars_ago:
                        # 最新变盘点
                        existing = [b for b in state.get("breakouts", []) if b["symbol"] == symbol and b["breakout_time"] == breakout_time.isoformat()]
                        if not existing:
                            new_breakouts.append(breakout_data)
                    elif max_bars_ago < bars_since_breakout <= (48 * 4): 
                        # 过去48小时内错过的 (48h = 192根15mK线)
                        existing_alert = [b for b in state.get("breakouts", []) if b["symbol"] == symbol and b["breakout_time"] == breakout_time.isoformat()]
                        existing_missed = [m for m in state.get("missed", []) if m["symbol"] == symbol and m["breakout_time"] == breakout_time.isoformat()]
                        if not existing_alert and not existing_missed:
                            new_missed.append(breakout_data)

        if not is_full_scan and not symbol_still_forming:
            new_watchlist = [w for w in new_watchlist if w["symbol"] != symbol]

    state["watch_list"] = new_watchlist
    
    state["breakouts"] = new_breakouts + state.get("breakouts", [])
    state["missed"] = new_missed + state.get("missed", [])
    
    # 清理陈旧的记录 (保留最近 48 小时内的)
    def clean_old(items):
        valid = []
        seen = set()
        for item in items:
            try:
                b_time = parser.parse(item["breakout_time"])
                if (current_time - b_time).total_seconds() <= 48 * 3600:
                    unique_key = f"{item['symbol']}_{item['breakout_time']}"
                    if unique_key not in seen:
                        valid.append(item)
                        seen.add(unique_key)
            except Exception:
                pass
        # 按照发生时间倒序排列
        valid.sort(key=lambda x: parser.parse(x["breakout_time"]), reverse=True)
        return valid
        
    state["breakouts"] = clean_old(state["breakouts"])
    state["missed"] = clean_old(state["missed"])
    state["last_updated"] = current_time.isoformat()
    
    print(f"\n扫描完成. 酝酿中: {len(state['watch_list'])}, 新变盘: {len(new_breakouts)}, 历史变盘库: {len(state['breakouts'])}, 错过库: {len(state['missed'])}.")
    
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    print("启动市场双层雷达引擎 (15分钟海选 + 1分钟高频狙击)...")
    while True:
        try:
            run_radar_cycle()
        except Exception as e:
            print(f"雷达引擎异常: {e}")
        time.sleep(60)
