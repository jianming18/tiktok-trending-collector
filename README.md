# TikTok Trending Collector

使用 `TikTokApi + Playwright(WebKit)` 采集 TikTok Trending 数据，并通过 GitHub Actions 自动运行。

该项目通过代理和 token 池提高抓取成功率，并自动保存抓取历史数据。

## 功能

- 使用 `TikTokApi.trending.videos()` 抓取 Trending 数据
- 浏览器固定为 `Playwright WebKit`
- 代理从 `proxiesus-updater` 仓库 `proxiesus.txt` 动态获取
- 抓取失败 / 超时 / 风控 / 空结果时自动轮换代理
- 支持 `msToken` 池随机选择
- 输出最新结果 JSON 和历史 JSONL
- GitHub Actions 自动提交 `data/` 目录

## Token 轮换机制

项目使用 **token pool 随机选择策略**。

GitHub Secrets 中配置：

```text
MS_TOKEN_POOL
```

每一行放一个 `msToken`：

```text
token_1
token_2
token_3
token_4
```

每次 workflow 运行时会：

1. 读取 `MS_TOKEN_POOL`
2. 按行解析 token
3. 随机选择一个 token
4. 用于当前抓取任务

这样可以减少 TikTok 风控风险。

## 输出字段

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

进入：

```text
Repository Settings → Secrets and variables → Actions
```

### Secrets

| Name | Description |
|-----|-------------|
| `MS_TOKEN_POOL` | TikTok `msToken` token 池（每行一个） |
| `PROXY_USERNAME` | 代理账号（可选） |
| `PROXY_PASSWORD` | 代理密码（可选） |

示例：

```text
MS_TOKEN_POOL

token_a
token_b
token_c
token_d
```

### Variables

| Variable | Description | Example |
|--------|-------------|--------|
| `TRENDING_COUNT` | 每次抓取数量 | `1`（测试） / `500` |
| `MAX_PROXIES_TO_TRY` | 每次最多尝试代理数量 | `30` |
| `PROXY_FILE_URL` | 代理列表地址 | 默认已配置 |

默认代理列表：

```text
https://raw.githubusercontent.com/jianming18/proxiesus-updater/main/proxiesus.txt
```

## GitHub Actions 调度

GitHub Actions workflow：

```text
.github/workflows/collect.yml
```

当前调度时间：

```yaml
schedule:
  - cron: "0 0,8,16 * * *"
```

对应时间：

- UTC 00:00
- UTC 08:00
- UTC 16:00

你也可以在 GitHub Actions 页面 **手动触发任务**。

## 代理轮换逻辑

程序运行流程：

1. 下载 `proxiesus.txt`
2. 解析为代理列表
3. 从第一条代理开始尝试
4. 若失败则切换下一条代理
5. 成功后结束任务

失败情况包括：

- 连接超时
- TikTok 风控
- 返回空数据
- API 请求失败

所有尝试都会记录到日志。

## 数据文件

抓取结果会保存到 `data/` 目录。

### 最新结果

```text
data/trending_latest.json
```

保存最近一次成功抓取结果。

### 历史记录

```text
data/trending_history.jsonl
```

每次成功抓取会追加一条记录。

### 尝试日志

```text
data/attempt_log.jsonl
```

记录所有代理尝试信息，例如：

- 时间
- 代理地址
- 成功 / 失败
- token index

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install webkit
```

运行：

```bash
export MS_TOKEN="your_token"
export TRENDING_COUNT="1"

python collector.py
```

本地运行时只需要单个 `MS_TOKEN`。

## 注意

- `TikTokApi` 为非官方接口，TikTok 页面或风控变化可能导致抓取失效。
- TikTok 对请求频率、token、代理都可能有限制。
- 使用 token pool + proxy 可以显著提高成功率。

## License

MIT License
