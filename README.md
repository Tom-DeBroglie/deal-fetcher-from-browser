# AI Deal Web Monitor

一个尽量简化的「深度学习 / AI 优惠活动」网页监控仓库。

它不依赖 B站、小红书、知乎登录态，也不依赖 RSSHub。它每天自动：

1. 读取 `config/web_sources.txt` 中的官方/技术社区入口页；
2. 读取 `config/search_queries.txt` 中的搜索词，用搜索结果补充候选文章；
3. 抓取公开网页标题、摘要和正文；
4. 用关键词和来源可信度打分；
5. 去重；
6. 用 PushPlus 推送微信。

## 1. 最少需要配置什么？

GitHub 仓库里只需要配置 1 个 Secret：

```text
PUSHPLUS_TOKEN
```

可选增强搜索质量：

```text
TAVILY_API_KEY
SERPER_API_KEY
```

没有这两个 key 时，脚本会尝试 DuckDuckGo HTML 搜索，但稳定性不如搜索 API。

## 2. 文件说明

```text
web_deal_monitor.py              主脚本
requirements.txt                 Python 依赖
config/search_queries.txt         搜索关键词，一行一个
config/web_sources.txt            官方/社区网页入口，一行一个
config/trusted_domains.txt        高可信域名，命中会加分
config/block_domains.txt          黑名单域名
config/keywords_extra.txt         额外关键词
.github/workflows/daily.yml       GitHub Actions 定时任务
data/sent_items.json              已发送记录，自动生成
data/latest_report.md             最新日报，自动生成
```

## 3. 怎么调整监控范围？

### 增加搜索词

编辑：

```text
config/search_queries.txt
```

每行加一个关键词，例如：

```text
硅基流动 免费额度
AutoDL 学生优惠
Gemini 免费 credits
```

### 增加网页来源

编辑：

```text
config/web_sources.txt
```

每行加一个公开网页入口，例如某个官方公告页、开发者社区、CSDN 专栏首页。

### 降低或提高筛选严格程度

编辑 `.github/workflows/daily.yml` 里的环境变量：

```yaml
MIN_SCORE_TO_REPORT: '13'
MIN_TOTAL_KEYWORD_HITS: '3'
```

更宽松：

```yaml
MIN_SCORE_TO_REPORT: '10'
MIN_TOTAL_KEYWORD_HITS: '2'
```

更严格：

```yaml
MIN_SCORE_TO_REPORT: '16'
MIN_TOTAL_KEYWORD_HITS: '4'
```

## 4. 推送规则大致是什么？

不是只看“打折”出现几次，而是综合评分：

- 标题命中“免费/优惠/token/额度/GPU/学生”等词会高分；
- 正文中优惠词、AI词、领取/申请/截止等动作词越多分越高；
- 官方域名和高可信技术社区会加分；
- 灰产、代充、破解等词会扣分；
- 已经发过的链接不会重复推送。

## 5. 手动测试

GitHub 页面：

```text
Actions → Daily AI Deal Web Monitor → Run workflow
```

测试时建议 `send_empty_report=true`，这样即使没有结果也会推送一条空报告，确认 PushPlus 通了。

## 6. 本地测试

```bash
pip install -r requirements.txt
export PUSHPLUS_TOKEN="你的pushplus token"
export SEND_EMPTY_REPORT=true
python web_deal_monitor.py
```

Windows PowerShell：

```powershell
pip install -r requirements.txt
$env:PUSHPLUS_TOKEN="你的pushplus token"
$env:SEND_EMPTY_REPORT="true"
python web_deal_monitor.py
```

## 7. 建议使用方式

第一周不要急着加很多站点。先保持默认配置跑几天，看 `data/latest_report.md` 和 Actions 日志。

如果误报多，提高：

```text
MIN_SCORE_TO_REPORT
```

如果漏报多，降低：

```text
MIN_SCORE_TO_REPORT
```

并补充 `config/search_queries.txt`。
