import streamlit as st
import json
import time
from pathlib import Path
from datetime import datetime
from dateutil import parser

# 设置页面配置，开启 wide mode 以便左右双列显示
st.set_page_config(
    page_title="变盘老鼠夹",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 终极极简、冷酷黑绿主题 CSS
st.markdown("""
<style>
    /* 全局背景与字体 */
    .stApp {
        background-color: #000000;
        color: #D0D0D0;
        font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* 隐藏 Streamlit 默认顶部菜单和底部水印 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* 顶部极简栏 */
    .top-bar {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        border-bottom: 1px solid #1A1A1A;
        padding-bottom: 10px;
        margin-bottom: 20px;
    }
    .app-title {
        color: #00FF66;
        font-size: 1.2rem;
        font-weight: 700;
        letter-spacing: 2px;
        margin: 0;
    }
    .sys-status {
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.75rem;
        color: #666666;
    }

    /* 列表列标题 */
    .col-header {
        color: #888888;
        font-size: 0.9rem;
        font-weight: 600;
        letter-spacing: 1px;
        margin-bottom: 15px;
        text-transform: uppercase;
        border-bottom: 1px solid #1A1A1A;
        padding-bottom: 5px;
    }

    /* 数据卡片基础样式 (极简线条) */
    .terminal-card {
        background-color: transparent;
        border: 1px solid #1A1A1A;
        padding: 12px;
        margin-bottom: 12px;
        transition: all 0.2s ease;
    }
    .terminal-card:hover {
        background-color: #050505;
    }

    /* 变盘点左侧高亮指示 */
    .card-breakout-long { border-left: 2px solid #00FF66; }
    .card-breakout-short { border-left: 2px solid #FF3366; }
    .card-forming { border-left: 2px solid #444444; }

    .terminal-card:hover.card-breakout-long { border-color: #00FF66; box-shadow: 0 0 10px rgba(0, 255, 102, 0.05); }
    .terminal-card:hover.card-breakout-short { border-color: #FF3366; box-shadow: 0 0 10px rgba(255, 51, 102, 0.05); }

    /* 卡片内部排版 */
    .card-row-top {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: 8px;
    }
    .coin-ticker {
        font-size: 1.1rem;
        font-weight: 600;
        color: #FFFFFF;
    }
    .signal-text {
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .text-long { color: #00FF66; }
    .text-short { color: #FF3366; }
    .text-neutral { color: #666666; }

    /* 数据细节网格 */
    .details-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 6px;
        font-size: 0.8rem;
        color: #777777;
        margin-bottom: 10px;
    }
    .details-grid span {
        color: #CCCCCC;
        font-family: 'Courier New', Courier, monospace;
    }
    
    /* 原因说明文本 */
    .reason-text {
        font-size: 0.75rem;
        color: #555555;
        margin-bottom: 10px;
    }

    /* 行内极简按钮 */
    .stLinkButton > a {
        display: block;
        width: 100%;
        text-align: center;
        border: 1px solid #1A1A1A !important;
        background-color: transparent !important;
        color: #888888 !important;
        font-size: 0.75rem;
        padding: 4px 0 !important;
        transition: all 0.2s;
    }
    .stLinkButton > a:hover {
        border-color: #333333 !important;
        color: #FFFFFF !important;
        background-color: #111111 !important;
    }
    
    .stButton > button {
        background-color: transparent !important;
        border: 1px solid #333333 !important;
        color: #666666 !important;
        font-size: 0.7rem;
        padding: 2px 10px !important;
    }
    .stButton > button:hover {
        color: #00FF66 !important;
        border-color: #00FF66 !important;
    }
</style>
""", unsafe_allow_html=True)

root_dir = Path(__file__).resolve().parents[1]
state_file = root_dir / "radar" / "state.json"

def load_state():
    if not state_file.exists():
        return None
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_okx_link(symbol):
    base_quote = symbol.split(':')[0]
    formatted = base_quote.replace('/', '-').lower()
    return f"https://www.okx.com/trade-swap/{formatted}-swap"

# 读取状态
state = load_state()

# 渲染顶部栏
top_cols = st.columns([1, 1])
with top_cols[0]:
    st.markdown("<div class='app-title'>变盘老鼠夹</div>", unsafe_allow_html=True)

with top_cols[1]:
    if state:
        try:
            dt = parser.parse(state['last_updated'])
            local_time = dt.strftime("%H:%M:%S")
            status_html = f"<div class='sys-status' style='text-align: right;'>SYNC: {local_time}</div>"
        except:
            status_html = "<div class='sys-status' style='text-align: right;'>SYNC: ERROR</div>"
    else:
        status_html = "<div class='sys-status' style='text-align: right;'>OFFLINE</div>"
    
    # 将刷新按钮和状态文字放在一起
    sub_cols = st.columns([3, 1])
    sub_cols[0].markdown(status_html, unsafe_allow_html=True)
    if sub_cols[1].button("REFRESH"):
        st.rerun()

st.markdown("<div class='top-bar'></div>", unsafe_allow_html=True)

if not state:
    st.error("SYSTEM OFFLINE. BACKGROUND SCANNER NOT RESPONDING.")
    st.stop()

breakouts = state.get("breakouts", [])
watch_list = state.get("watch_list", [])

# 左右三列布局 (修改为3列)
left_col, mid_col, right_col = st.columns(3, gap="large")

# ========================================
# 左列：酝酿中 (Watchlist)
# ========================================
with left_col:
    st.markdown("<div class='col-header'>CHANNEL MONITORING</div>", unsafe_allow_html=True)
    
    if not watch_list:
        st.markdown("<div class='sys-status'>NO FORMING STRUCTURES.</div>", unsafe_allow_html=True)
    else:
        for w in watch_list:
            ticker = w['symbol'].split(':')[0]
            okx_link = get_okx_link(w['symbol'])
            
            st.markdown(f"""
            <div class="terminal-card card-forming">
                <div class="card-row-top">
                    <span class="coin-ticker">{ticker}</span>
                    <span class="signal-text text-neutral">FORMING</span>
                </div>
                <div class="details-grid">
                    <div>TOUCHES: <span>{w['touches']}</span></div>
                    <div>CONVERGENCE: <span>{w['narrowing']}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.link_button(f"VIEW {ticker}", url=okx_link, use_container_width=True)

# ========================================
# 中列：变盘点 (Breakouts)
# ========================================
with mid_col:
    st.markdown("<div class='col-header'>BREAKOUT ALERTS</div>", unsafe_allow_html=True)
    
    if not breakouts:
        st.markdown("<div class='sys-status'>NO ACTIVE BREAKOUTS.</div>", unsafe_allow_html=True)
    else:
        for b in breakouts:
            is_long = b['direction'] == 'LONG'
            card_class = "card-breakout-long" if is_long else "card-breakout-short"
            text_class = "text-long" if is_long else "text-short"
            ticker = b['symbol'].split(':')[0]
            okx_link = get_okx_link(b['symbol'])
            
            st.markdown(f"""
            <div class="terminal-card {card_class}">
                <div class="card-row-top">
                    <span class="coin-ticker">{ticker}</span>
                    <span class="signal-text {text_class}">{b['direction']}</span>
                </div>
                <div class="details-grid">
                    <div>ENT: <span>{b['entry_price']}</span></div>
                    <div>SL: <span>{b['stop_loss']}</span></div>
                    <div>TP1: <span>{b['tp1']}</span></div>
                    <div>TP2: <span>{b['tp2']}</span></div>
                </div>
                <div class="reason-text">>> {b['reason']}</div>
            </div>
            """, unsafe_allow_html=True)
            st.link_button(f"TRADE {ticker}", url=okx_link, use_container_width=True)

# ========================================
# 右列：错过的行情 (Missed)
# ========================================
missed_list = state.get("missed", [])
with right_col:
    st.markdown("<div class='col-header'>MISSED (LAST 48H)</div>", unsafe_allow_html=True)
    
    if not missed_list:
        st.markdown("<div class='sys-status'>NO MISSED OPPORTUNITIES.</div>", unsafe_allow_html=True)
    else:
        for m in missed_list:
            is_long = m['direction'] == 'LONG'
            # 错过的行情使用暗淡颜色
            text_class = "text-neutral"
            ticker = m['symbol'].split(':')[0]
            okx_link = get_okx_link(m['symbol'])
            
            # 解析时间显示多久前
            try:
                b_time = parser.parse(m['breakout_time'])
                ago_hours = (datetime.now(b_time.tzinfo) - b_time).total_seconds() / 3600
                time_str = f"{ago_hours:.1f}h ago"
            except:
                time_str = "Unknown"
            
            st.markdown(f"""
            <div class="terminal-card" style="border-left: 2px solid #555; opacity: 0.7;">
                <div class="card-row-top">
                    <span class="coin-ticker" style="color: #999;">{ticker}</span>
                    <span class="signal-text {text_class}">{m['direction']} ({time_str})</span>
                </div>
                <div class="details-grid">
                    <div style="color: #666;">ENT: <span>{m['entry_price']}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.link_button(f"REVIEW {ticker}", url=okx_link, use_container_width=True)
