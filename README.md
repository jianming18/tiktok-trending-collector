# TikTok Trending Collector

使用 `TikTokApi + Playwright(WebKit)` 采集 TikTok Trending 数据，并通过 GitHub Actions 自动运行。

该项目通过代理和 token 池提高抓取成功率，并自动保存抓取历史数据。

---

# 功能

- 使用 `TikTokApi.trending.videos()` 抓取 Trending 数据
- 浏览器固定为 `Playwright WebKit`
- 代理从 `proxiesus-updater` 仓库 `proxiesus.txt` 动态获取
- 抓取失败 / 超时 / 风控 / 空结果时自动轮换代理
- 支持 **msToken 池随机选择**
- 输出最新结果 JSON 和历史 JSONL
- GitHub Actions 自动提交 `data/` 目录

---

# Token 轮换机制

项目使用 **token pool 随机选择策略**。

GitHub Secrets 中配置：

每一行放一个 `msToken`：

每次 workflow 运行时会：

1. 读取 `MS_TOKEN_POOL`
2. 按行解析 token
3. **随机选择一个 token**
4. 用于当前抓取任务

这样可以减少 TikTok 风控风险。

---

# 输出字段

Trending 数据包含：

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

---

# 目录结构

---

# GitHub 配置

进入：

## Secrets

| Name | Description |
|-----|-------------|
| `MS_TOKEN_POOL` | TikTok `msToken` token 池（每行一个） |
| `PROXY_USERNAME` | 代理账号（可选） |
| `PROXY_PASSWORD` | 代理密码（可选） |

示例：

---

## Variables

| Variable | Description | Example |
|--------|-------------|--------|
| `TRENDING_COUNT` | 每次抓取数量 | `1`（测试） / `500` |
| `MAX_PROXIES_TO_TRY` | 每次最多尝试代理数量 | `30` |
| `PROXY_FILE_URL` | 代理列表地址 | 默认已配置 |

默认代理列表：

---

# GitHub Actions 调度

GitHub Actions workflow：

当前调度时间：

```yaml
schedule:
  - cron: "0 0,8,16 * * *"

data/trending_latest.json

data/trending_history.jsonl

data/attempt_log.jsonl

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install webkit

export MS_TOKEN="your_token"
export TRENDING_COUNT="1"

python collector.py

