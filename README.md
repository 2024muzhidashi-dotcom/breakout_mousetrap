# Breakout Mousetrap (变盘老鼠夹) 🪤

**Breakout Mousetrap** 是一个基于通道识别功能的加密货币市场监控雷达终端。

本项目基于我之前的 `crypto_ai_trader` 项目中的 **“通道/收敛识别引擎 (Channel Recognition)”** 进化而来，旨在帮助交易员能快速筛选出值得关注的行情。

##  核心特性
*   **三层扫描引擎**：
    *   **15分钟海选**：全自动拉取 OKX 所有的 USDT 本位永续合约（300+ 币种），寻找正在极致收敛（至少 5 次交替触碰顶底）的种类，放入 `CHANNEL MONITORING` 酝酿列表。
    *   **1分钟高频狙击**：对酝酿列表中的币种进行每分钟的高频扫描，一旦发生实质性放量突破，立即放入 `BREAKOUT ALERTS` 变盘信号列表。
    *   **过去48小时错过的行情**虽然已经错过变盘，但是仍然值得关注的我放入了第三个list。

    *   **极简终端界面**：适配电脑和手机，电脑可一键跳转 OKX 网页端交易。

---

## 💻 一键部署指南 (Mac M系列芯片/Apple Silicon 专用)

本项目全面容器化，并且特别适配了 Mac M1/M2/M3 等 Apple Silicon 芯片。

### 环境准备
1. 确保你的 Mac 上安装了 [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)。
   *(注意选择 **Apple Silicon** 版本下载)*。
2. 确保 Docker 正在运行（顶部状态栏有一个鲸鱼图标）。

### 部署步骤
1. **克隆项目到本地**
   ```bash
   git clone https://github.com/2024muzhidashi-dotcom/breakout_mousetrap.git
   cd breakout_mousetrap
   ```

2. **一键构建并后台启动**
   使用 Docker Compose 启动。Docker 会自动处理 Python 依赖和 M 系芯片架构兼容问题。
   ```bash
   docker-compose up -d --build
   ```

3. **访问雷达终端**
   在你的浏览器中输入：
   👉 **http://localhost:8501**
   
   *手机访问提示：在同一个 WiFi 下的 iPhone 浏览器中，输入你的 Mac 局域网 IP 加端口（例如 `http://192.168.x.x:8501`），点击 Safari 底部的“分享” -> “添加到主屏幕”，即可获得原生 App 体验。*

### 如何停止雷达
如果你想关闭监控引擎：
```bash
docker-compose down
```

## 🛠 技术架构
- 数据源：OKX API (ccxt)
- 核心引擎：Pandas, NumPy, Scikit-learn
- 前端终端：Streamlit
- 部署：Docker, Docker Compose
