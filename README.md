# TikTok Trending Collector

使用 `TikTokApi + Playwright(WebKit)` 采集 TikTok Trending 数据，并通过 GitHub Actions 在每天 UTC 00:00 / 12:00 自动运行。

## 功能

- 使用 `TikTokApi.trending.videos()` 抓取 Trending 数据
- 浏览器固定为 `webkit`
- 代理从 `proxiesus-updater` 仓库的 `proxiesus.txt` 动态获取
- 抓取失败、超时、风控、空结果时自动轮换下一条代理
- 输出最新结果 JSON 和历史明细 JSONL
- GitHub Actions 自动提交 `data/` 目录

## 输出字段

- `video_id`
- `desc`
- `create_time`
- `duration`
- `play_count`
- `like_count`
- `comment_count`
- `share_count`
- `author_username`
- `music_title`
- `hashtags`

## 目录结构

```text
.
├─ .github/
│  └─ workflows/
│     └─ collect.yml
├─ data/
│  └─ .gitkeep
├─ collector.py
├─ proxy_loader.py
├─ requirements.txt
└─ README.md
```

## GitHub 配置

### Secrets

- `MS_TOKEN`：TikTok cookie 中的 `msToken`
- `PROXY_USERNAME`：可选，代理账号
- `PROXY_PASSWORD`：可选，代理密码

### Variables

- `TRENDING_COUNT`：当前测试可设为 `1`，正式可改 `500`
- `MAX_PROXIES_TO_TRY`：每次任务最多尝试多少条代理，默认 `30`
- `PROXY_FILE_URL`：默认已指向 `proxiesus-updater` 的 raw 地址

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install webkit
export MS_TOKEN='你的 ms_token'
export TRENDING_COUNT='1'
python collector.py
```

## GitHub Actions 调度

```yaml
schedule:
  - cron: "0 0,12 * * *"
```

对应时间：

- UTC 00:00
- UTC 12:00

## 代理轮换逻辑

程序启动后会：

1. 下载 `proxiesus.txt`
2. 逐行解析为 `socks5://ip:port`
3. 从第一条开始依次尝试
4. 失败时记录到 `data/attempt_log.jsonl`
5. 成功后输出结果并结束

## 数据文件

- `data/trending_latest.json`：本次最新结果
- `data/trending_history.jsonl`：历史明细
- `data/attempt_log.jsonl`：代理尝试日志

## 注意

- `TikTokApi` 是非官方方案，TikTok 页面或风控变化可能导致抓取失效。
- 当前代码优先保证可部署和可维护，后续可再增加重试次数、指标上报和告警。
