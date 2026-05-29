#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI / 深度学习优惠活动网页监控器

设计目标：
1. 不依赖 B站/小红书/知乎登录态；
2. 优先抓公开网页、官方公告页、CSDN/掘金/博客园等技术社区；
3. 先标题/摘要初筛，再抓正文评分；
4. 去重后通过 PushPlus 推送。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

STATE_PATH = DATA / "sent_items.json"
REPORT_PATH = DATA / "latest_report.md"

USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 AI-Deal-Monitor/1.0",
)

MAX_SEARCH_RESULTS_PER_QUERY = int(os.getenv("MAX_SEARCH_RESULTS_PER_QUERY", "5"))
MAX_CANDIDATES_PER_RUN = int(os.getenv("MAX_CANDIDATES_PER_RUN", "120"))
MAX_ARTICLES_TO_FETCH = int(os.getenv("MAX_ARTICLES_TO_FETCH", "80"))
MIN_SCORE_TO_REPORT = int(os.getenv("MIN_SCORE_TO_REPORT", "13"))
MIN_PROMO_HITS = int(os.getenv("MIN_PROMO_HITS", "1"))
MIN_AI_HITS = int(os.getenv("MIN_AI_HITS", "1"))
MIN_TOTAL_KEYWORD_HITS = int(os.getenv("MIN_TOTAL_KEYWORD_HITS", "3"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
SLEEP_SECONDS = float(os.getenv("SLEEP_SECONDS", "0.8"))
SEND_EMPTY_REPORT = os.getenv("SEND_EMPTY_REPORT", "false").lower() in {"1", "true", "yes"}
ENABLE_DDG_SEARCH = os.getenv("ENABLE_DDG_SEARCH", "true").lower() in {"1", "true", "yes"}
ADD_YEAR_VARIANTS = os.getenv("ADD_YEAR_VARIANTS", "false").lower() in {"1", "true", "yes"}
MAX_FOREIGN_OFFICIAL_REPORT_ITEMS = int(os.getenv("MAX_FOREIGN_OFFICIAL_REPORT_ITEMS", "3"))
MAX_FOREIGN_INTEL_REPORT_ITEMS = int(os.getenv("MAX_FOREIGN_INTEL_REPORT_ITEMS", "7"))
MAX_DOMESTIC_OFFICIAL_REPORT_ITEMS = int(os.getenv("MAX_DOMESTIC_OFFICIAL_REPORT_ITEMS", "3"))
MAX_DOMESTIC_INTEL_REPORT_ITEMS = int(os.getenv("MAX_DOMESTIC_INTEL_REPORT_ITEMS", "7"))
MIN_STRONG_PROMO_HITS = int(os.getenv("MIN_STRONG_PROMO_HITS", "1"))

PROMO_KEYWORDS = [
    "免费", "限免", "白嫖", "薅羊毛", "羊毛", "优惠", "折扣", "打折", "半价", "低至", "立减", "满减",
    "福利", "礼包", "补贴", "代金券", "优惠券", "抵扣券", "算力券", "兑换码", "邀请码", "折扣码",
    "额度", "免费额度", "试用", "免费试用", "公测", "内测", "领取", "申请", "活动入口", "注册送",
    "token", "tokens", "credits", "credit", "coupon", "discount", "free", "free trial", "free tier", "student discount",
]

AI_KEYWORDS = [
    "ai", "人工智能", "深度学习", "机器学习", "大模型", "llm", "aigc", "agent", "智能体",
    "api", "模型", "推理", "训练", "微调", "embedding", "rag", "gpu", "算力", "云服务器", "云资源",
    "gemini", "claude", "openai", "chatgpt", "github copilot", "copilot", "hugging face", "huggingface",
    "deepseek", "kimi", "通义", "千问", "qwen", "百炼", "火山方舟", "豆包", "混元", "千帆", "文心",
    "智谱", "glm", "bigmodel", "硅基流动", "siliconflow", "modelscope", "魔搭", "modelarts", "昇腾",
]

ACTION_KEYWORDS = [
    "领取", "申请", "注册", "认证", "学生认证", "教育认证", "开发者", "入口", "活动入口", "有效期", "截止",
    "限时", "名额", "资格", "redeem", "apply", "claim", "register", "deadline",
]

NEGATIVE_KEYWORDS = [
    "二手", "破解", "盗版", "账号出租", "代充", "接码", "灰产", "博彩", "成人", "色情", "vpn机场", "返佣软文",
]

DATE_PATTERNS = [
    r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})",
    r"(20\d{2}[-/.年]\d{1,2})",
]


STRONG_PROMO_KEYWORDS = [
    "免费额度", "赠送额度", "新用户额度", "试用额度", "调用额度", "api额度", "推理额度", "模型额度", "算力额度",
    "免费token", "免费 token", "赠送token", "赠送 token", "tokens额度", "token额度", "token plan",
    "优惠活动", "限时优惠", "限时免费", "限免", "免费试用", "公测免费", "免费领取", "领取入口", "活动入口",
    "优惠券", "代金券", "抵扣券", "算力券", "资源券", "兑换券", "折扣码", "优惠码", "兑换码", "邀请码",
    "学生优惠", "教育优惠", "学生免费", "学生认证", "教育认证", "开发者福利", "开发者计划", "开发者额度",
    "免费gpu", "免费 gpu", "免费算力", "算力券", "gpu券", "云资源免费", "云服务器免费",
    "降价", "价格调整", "价格下调", "限时折扣", "折扣", "打折", "半价", "立减", "满减", "补贴",
    "free credits", "free credit", "promo credits", "trial credits", "cloud credits", "api credits", "compute credits", "gpu credits",
    "free tokens", "free token", "bonus tokens", "token credits", "monthly credits",
    "free trial", "free tier", "limited time free", "limited-time free", "free access", "free plan",
    "student discount", "student credits", "student plan", "education discount", "academic discount", "developer credits",
    "coupon code", "promo code", "discount code", "voucher", "coupon", "redeem code", "giveaway", "grant",
    "price cut", "price reduction", "pricing update", "limited offer", "special offer", "launch offer",
]

FOREIGN_OFFICIAL_DOMAINS = [
    "openai.com", "anthropic.com", "blog.google", "developers.googleblog.com", "google.com", "cloud.google.com",
    "github.blog", "github.com", "education.github.com", "huggingface.co", "aws.amazon.com", "azure.microsoft.com",
    "microsoft.com", "microsoft.ai", "techcommunity.microsoft.com", "ai.azure.com", "nvidia.com",
]

DOMESTIC_OFFICIAL_DOMAINS = [
    "aliyun.com", "alibabacloud.com", "bailian.console.aliyun.com", "volcengine.com", "developer.volcengine.com",
    "bytedance.com", "coze.cn", "doubao.com", "tencent.com", "cloud.tencent.com", "hunyuan.tencent.com",
    "baidu.com", "cloud.baidu.com", "qianfan.cloud.baidu.com", "huaweicloud.com", "xfyun.cn", "xinghuo.xfyun.cn",
    "bigmodel.cn", "open.bigmodel.cn", "zhipuai.cn", "moonshot.cn", "platform.moonshot.cn",
    "deepseek.com", "api-docs.deepseek.com", "siliconflow.cn", "cloud.siliconflow.cn", "modelscope.cn",
    "xiaomi.com", "mi.com", "xiaomimimo.com", "platform.xiaomimimo.com", "mimo.xiaomi.com", "xiaoai.mi.com",
    "vivo.com", "vivo.com.cn", "developer.vivo.com", "dev.vivo.com.cn", "meituan.com", "tech.meituan.com",
]

FOREIGN_INTEL_DOMAINS = [
    "producthunt.com", "indiehackers.com", "hackernews.com", "news.ycombinator.com", "techcrunch.com", "theverge.com",
]

DOMESTIC_INTEL_DOMAINS = [
    "csdn.net", "blog.csdn.net", "juejin.cn", "cnblogs.com", "oschina.net", "infoq.cn", "jiqizhixin.com",
    "qbitai.com", "aibase.com", "36kr.com", "geekpark.net", "sspai.com", "leiphone.com", "ifanr.com",
]

CATEGORY_LABELS = {
    "foreign_official": "国外大厂官号",
    "domestic_official": "国内大厂官号",
    "foreign_intel": "国外优惠活动情报账户/网站",
    "domestic_intel": "国内优惠活动情报账户/网站",
}


@dataclass
class Candidate:
    url: str
    title: str = ""
    snippet: str = ""
    source: str = ""


@dataclass
class ScoredItem:
    url: str
    title: str
    snippet: str
    source: str
    domain: str
    score: int
    promo_hits: int
    ai_hits: int
    action_hits: int
    matched_keywords: List[str]
    published_guess: str = ""
    content_hash: str = ""
    source_category: str = "domestic_intel"


def read_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        rows.append(s)
    return rows


def norm_space(s: str, max_len: int = 10000) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len]


def domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""





def domain_matches(domain: str, rules: List[str]) -> bool:
    return any(domain == x or domain.endswith("." + x) for x in rules)


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def classify_source(url: str, title: str = "", text: str = "") -> str:
    """把来源分成：国外官号、国内官号、国外情报、国内情报。"""
    d = domain_of(url)
    path = urlparse(url).path.lower()

    # 少数“官方账号开在社区平台”的情况，用路径修正。
    if d == "blog.csdn.net" and "meituantech" in path:
        return "domestic_official"

    if domain_matches(d, FOREIGN_OFFICIAL_DOMAINS):
        return "foreign_official"
    if domain_matches(d, DOMESTIC_OFFICIAL_DOMAINS):
        return "domestic_official"
    if domain_matches(d, FOREIGN_INTEL_DOMAINS):
        return "foreign_intel"
    if domain_matches(d, DOMESTIC_INTEL_DOMAINS):
        return "domestic_intel"

    # 未知网页按语言粗分，避免完全漏掉搜索引擎找到的高分帖子。
    return "domestic_intel" if has_chinese(" ".join([title, text])) else "foreign_intel"


def is_blocked(url: str, blocked_domains: List[str]) -> bool:
    d = domain_of(url)
    return any(d == b or d.endswith("." + b) for b in blocked_domains)


def load_state() -> Dict[str, dict]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, dict]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    })
    return s


def clean_ddg_url(href: str) -> str:
    if not href:
        return ""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        if qs.get("uddg"):
            return unquote(qs["uddg"][0])
    return href


def search_duckduckgo(query: str, max_results: int) -> Tuple[List[Candidate], Optional[str]]:
    if not ENABLE_DDG_SEARCH:
        return [], None
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query, "kl": "cn-zh"}
    try:
        r = session().get(url, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        items: List[Candidate] = []
        for res in soup.select("div.result"):
            a = res.select_one("a.result__a")
            if not a:
                continue
            link = clean_ddg_url(a.get("href", ""))
            title = norm_space(a.get_text(" "), 300)
            sn = res.select_one("a.result__snippet") or res.select_one("div.result__snippet")
            snippet = norm_space(sn.get_text(" ") if sn else "", 500)
            if link and link.startswith("http"):
                items.append(Candidate(url=link, title=title, snippet=snippet, source=f"DuckDuckGo: {query}"))
            if len(items) >= max_results:
                break
        return items, None
    except Exception as exc:
        return [], f"DDG search failed: {query} -> {exc}"


def search_tavily(query: str, max_results: int) -> Tuple[List[Candidate], Optional[str]]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return [], None
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_raw_content": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        items = []
        for x in data.get("results", [])[:max_results]:
            items.append(Candidate(
                url=x.get("url", ""),
                title=norm_space(x.get("title", ""), 300),
                snippet=norm_space(x.get("content", ""), 500),
                source=f"Tavily: {query}",
            ))
        return [i for i in items if i.url], None
    except Exception as exc:
        return [], f"Tavily search failed: {query} -> {exc}"


def search_serper(query: str, max_results: int) -> Tuple[List[Candidate], Optional[str]]:
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    if not api_key:
        return [], None
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        items = []
        for x in data.get("organic", [])[:max_results]:
            items.append(Candidate(
                url=x.get("link", ""),
                title=norm_space(x.get("title", ""), 300),
                snippet=norm_space(x.get("snippet", ""), 500),
                source=f"Serper: {query}",
            ))
        return [i for i in items if i.url], None
    except Exception as exc:
        return [], f"Serper search failed: {query} -> {exc}"


def fetch_page(url: str) -> Tuple[str, str, str, Optional[str]]:
    """返回 title, description, body_text, error"""
    try:
        r = session().get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            return "", "", "", f"HTTP {r.status_code}"
        ctype = r.headers.get("content-type", "")
        if "text/html" not in ctype and "application/xhtml" not in ctype and not r.text.lstrip().startswith("<"):
            return "", "", "", f"unsupported content-type: {ctype}"
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()
        title = ""
        if soup.title:
            title = soup.title.get_text(" ")
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            title = og.get("content", title)
        desc = ""
        md = soup.select_one('meta[name="description"]') or soup.select_one('meta[property="og:description"]')
        if md and md.get("content"):
            desc = md.get("content", "")
        # 优先正文容器，否则使用所有 p/li/h1-h3
        main = soup.select_one("article") or soup.select_one("main") or soup.select_one("#content") or soup.body or soup
        parts = []
        for el in main.select("h1,h2,h3,p,li,blockquote"):
            txt = norm_space(el.get_text(" "), 1000)
            if txt:
                parts.append(txt)
        body = norm_space("\n".join(parts), 30000)
        return norm_space(title, 300), norm_space(desc, 800), body, None
    except Exception as exc:
        return "", "", "", str(exc)


def extract_links_from_source_page(url: str, max_links: int = 30) -> Tuple[List[Candidate], Optional[str]]:
    try:
        r = session().get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            return [], f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.text, "lxml")
        base_domain = domain_of(r.url)
        candidates: List[Candidate] = []
        seen = set()
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            link = urljoin(r.url, href)
            if not link.startswith("http"):
                continue
            p = urlparse(link)
            if p.scheme not in {"http", "https"}:
                continue
            # 默认只收同域链接，防止首页外链太多
            if domain_of(link) != base_domain and not domain_of(link).endswith("." + base_domain):
                continue
            title = norm_space(a.get_text(" "), 250)
            if len(title) < 4:
                continue
            clean = link.split("#")[0]
            if clean in seen:
                continue
            seen.add(clean)
            candidates.append(Candidate(url=clean, title=title, snippet="", source=f"Source page: {url}"))
            if len(candidates) >= max_links:
                break
        return candidates, None
    except Exception as exc:
        return [], str(exc)


def keyword_hits(text: str, words: List[str]) -> Tuple[int, List[str]]:
    t = text.lower()
    hits = 0
    matched = []
    for w in words:
        wl = w.lower()
        count = t.count(wl)
        if count > 0:
            hits += count
            matched.append(w)
    return hits, matched





def strong_promo_hits(text: str) -> Tuple[int, List[str]]:
    """强优惠词命中：避免把普通模型发布、普通新闻误判成优惠活动。"""
    return keyword_hits(text, STRONG_PROMO_KEYWORDS)


def guess_date(text: str) -> str:
    for pat in DATE_PATTERNS:
        m = re.search(pat, text)
        if m:
            raw = m.group(1).replace("年", "-").replace("月", "-").replace("日", "")
            try:
                return dtparser.parse(raw, fuzzy=True).date().isoformat()
            except Exception:
                return m.group(1)
    return ""


def score_candidate(c: Candidate, trusted_domains: List[str], extra_keywords: List[str]) -> Optional[ScoredItem]:
    title, desc, body, err = fetch_page(c.url)
    full_title = title or c.title or "无标题"
    full_text = norm_space("\n".join([c.title, c.snippet, title, desc, body]), 30000)
    if not full_text or len(full_text) < 40:
        return None

    promo_hits, promo_words = keyword_hits(full_text, PROMO_KEYWORDS)
    ai_hits, ai_words = keyword_hits(full_text, AI_KEYWORDS)
    action_hits, action_words = keyword_hits(full_text, ACTION_KEYWORDS)
    neg_hits, neg_words = keyword_hits(full_text, NEGATIVE_KEYWORDS)
    extra_hits, extra_words = keyword_hits(full_text, extra_keywords)
    strong_hits, strong_words = strong_promo_hits(full_text)

    title_text = (full_title + " " + c.title).lower()
    title_promo_hits, _ = keyword_hits(title_text, PROMO_KEYWORDS)
    title_ai_hits, _ = keyword_hits(title_text, AI_KEYWORDS)
    title_action_hits, _ = keyword_hits(title_text, ACTION_KEYWORDS)
    title_strong_hits, _ = strong_promo_hits(title_text)

    d = domain_of(c.url)
    trusted = any(d == x or d.endswith("." + x) for x in trusted_domains)

    total_hits = promo_hits + ai_hits + action_hits + extra_hits
    if promo_hits < MIN_PROMO_HITS or ai_hits < MIN_AI_HITS or total_hits < MIN_TOTAL_KEYWORD_HITS:
        return None
    # 必须至少命中一个“强优惠”表达，避免普通 AI 新闻因为 free/token/api 等泛词被推送。
    if strong_hits < MIN_STRONG_PROMO_HITS and title_strong_hits < MIN_STRONG_PROMO_HITS:
        return None

    score = 0
    score += min(promo_hits, 8) * 2
    score += min(ai_hits, 8) * 1
    score += min(action_hits, 6) * 2
    score += min(extra_hits, 5) * 2
    score += min(strong_hits, 6) * 5
    score += title_promo_hits * 5
    score += title_ai_hits * 3
    score += title_action_hits * 4
    if trusted:
        score += 6
    if any(x in full_text for x in ["官方", "官网", "活动规则", "有效期", "截止", "领取地址", "申请入口"]):
        score += 4
    if any(x.lower() in full_text.lower() for x in ["official", "deadline", "terms", "apply", "claim"]):
        score += 3
    if neg_hits:
        score -= 8
    if len(body) < 120:
        score -= 3

    if score < MIN_SCORE_TO_REPORT:
        return None

    snippet = norm_space(desc or c.snippet or body[:400], 500)
    matched = sorted(set(promo_words + ai_words + action_words + extra_words + strong_words))[:25]
    source_category = classify_source(c.url, full_title, full_text[:2000])
    chash = hashlib.sha256((full_title + d + body[:800]).encode("utf-8", "ignore")).hexdigest()[:16]
    return ScoredItem(
        url=c.url,
        title=norm_space(full_title, 180),
        snippet=snippet,
        source=c.source,
        domain=d,
        score=score,
        promo_hits=promo_hits,
        ai_hits=ai_hits,
        action_hits=action_hits,
        matched_keywords=matched,
        published_guess=guess_date(full_text[:3000]),
        content_hash=chash,
        source_category=source_category,
    )


def dedupe(items: List[ScoredItem]) -> List[ScoredItem]:
    best: Dict[str, ScoredItem] = {}
    for it in items:
        # URL 去 query 后 + 标题前 30 字，兼顾同文不同搜索来源
        p = urlparse(it.url)
        base = f"{p.netloc}{p.path}".rstrip("/")
        title_norm = re.sub(r"\W+", "", it.title.lower())[:50]
        key = hashlib.sha256((base + title_norm).encode("utf-8", "ignore")).hexdigest()[:16]
        if key not in best or it.score > best[key].score:
            best[key] = it
    return sorted(best.values(), key=lambda x: x.score, reverse=True)


def select_report_items(scored: List[ScoredItem], state: Dict[str, dict]) -> Tuple[List[ScoredItem], int]:
    """按国内/国外分别挑选：国外官号3 + 国外情报7 + 国内官号3 + 国内情报7，最多20条。"""
    buckets: Dict[str, List[ScoredItem]] = {
        "foreign_official": [],
        "foreign_intel": [],
        "domestic_official": [],
        "domestic_intel": [],
    }
    skipped = 0

    for it in scored:
        key = hashlib.sha256((it.url + it.content_hash).encode("utf-8", "ignore")).hexdigest()[:20]
        if key in state:
            skipped += 1
            continue
        if it.source_category in buckets:
            buckets[it.source_category].append(it)

    picked: List[ScoredItem] = []
    picked.extend(buckets["foreign_official"][:MAX_FOREIGN_OFFICIAL_REPORT_ITEMS])
    picked.extend(buckets["foreign_intel"][:MAX_FOREIGN_INTEL_REPORT_ITEMS])
    picked.extend(buckets["domestic_official"][:MAX_DOMESTIC_OFFICIAL_REPORT_ITEMS])
    picked.extend(buckets["domestic_intel"][:MAX_DOMESTIC_INTEL_REPORT_ITEMS])
    return picked, skipped


def make_report(new_items: List[ScoredItem], skipped_count: int, errors: List[str]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    if new_items:
        lines.append("# 🎯 深度学习 / AI 优惠活动监控周报")
        lines.append("")
        foreign_official_count = sum(1 for x in new_items if x.source_category == "foreign_official")
        foreign_intel_count = sum(1 for x in new_items if x.source_category == "foreign_intel")
        domestic_official_count = sum(1 for x in new_items if x.source_category == "domestic_official")
        domestic_intel_count = sum(1 for x in new_items if x.source_category == "domestic_intel")
        lines.append(
            f"发现 {len(new_items)} 条可能有价值的新活动信息："
            f"国外官号 {foreign_official_count} 条，国外情报 {foreign_intel_count} 条；"
            f"国内官号 {domestic_official_count} 条，国内情报 {domestic_intel_count} 条。"
        )
        lines.append("")
        lines.append(
            "筛选规则：国外官号最多 "
            f"{MAX_FOREIGN_OFFICIAL_REPORT_ITEMS} 条，国外情报最多 {MAX_FOREIGN_INTEL_REPORT_ITEMS} 条；"
            "国内官号最多 "
            f"{MAX_DOMESTIC_OFFICIAL_REPORT_ITEMS} 条，国内情报最多 {MAX_DOMESTIC_INTEL_REPORT_ITEMS} 条；"
            "已过滤普通模型发布、泛 AI 新闻和弱优惠信息。"
        )
        lines.append("")

        order = ["foreign_official", "foreign_intel", "domestic_official", "domestic_intel"]
        seq = 1
        for cat in order:
            group = [x for x in new_items if x.source_category == cat]
            if not group:
                continue
            lines.append(f"## {CATEGORY_LABELS.get(cat, cat)}")
            lines.append("")
            for it in group:
                lines.append(f"### {seq}. {it.title}")
                lines.append(f"- 评分：{it.score}")
                lines.append(f"- 来源类别：{CATEGORY_LABELS.get(it.source_category, it.source_category)}")
                lines.append(f"- 来源域名：{it.domain}")
                if it.published_guess:
                    lines.append(f"- 疑似日期：{it.published_guess}")
                lines.append(f"- 命中词：{', '.join(it.matched_keywords[:14])}")
                if it.snippet:
                    lines.append(f"- 摘要：{it.snippet}")
                lines.append(f"- 链接：{it.url}")
                lines.append("")
                seq += 1
    else:
        lines.append("# 📭 深度学习优惠活动周报")
        lines.append("")
        lines.append("本周期没有发现新的、可信度足够高的深度学习/AI优惠活动。")
        lines.append("")
    lines.append(f"跳过的已发送/重复信息：{skipped_count} 条")
    lines.append(f"抓取异常：{len(errors)} 个")
    lines.append(f"运行时间：{now}")
    if errors:
        lines.append("")
        lines.append("## 抓取异常（仅显示前10个）")
        for e in errors[:10]:
            lines.append(f"- {e}")
        if len(errors) > 10:
            lines.append(f"- ... 其余 {len(errors) - 10} 个异常已省略")
    return "\n".join(lines).strip() + "\n"

def pushplus_send(title: str, content: str) -> None:
    token = os.getenv("PUSHPLUS_TOKEN", "").strip()
    if not token:
        print("[WARN] PUSHPLUS_TOKEN not set; skip push.")
        return
    r = requests.post(
        "https://www.pushplus.plus/send",
        json={"token": token, "title": title, "content": content, "template": "markdown"},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 200:
        raise RuntimeError(f"PushPlus returned non-success: {data}")


def current_year_queries(queries: List[str]) -> List[str]:
    if not ADD_YEAR_VARIANTS:
        # 去重保序
        seen = set()
        uniq = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                uniq.append(q)
        return uniq

    year = datetime.now().year
    out = []
    for q in queries:
        out.append(q)
        if "site:" not in q and str(year) not in q:
            out.append(f"{q} {year}")
    # 去重保序
    seen = set()
    uniq = []
    for q in out:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq


def main() -> int:
    print("[INFO] AI deal web monitor started.")
    state = load_state()
    trusted_domains = read_lines(CONFIG / "trusted_domains.txt")
    blocked_domains = read_lines(CONFIG / "block_domains.txt")
    extra_keywords = read_lines(CONFIG / "keywords_extra.txt")
    queries = current_year_queries(read_lines(CONFIG / "search_queries.txt"))
    sources = read_lines(CONFIG / "web_sources.txt")

    errors: List[str] = []
    candidates: List[Candidate] = []

    # 1) 从公开网页入口抽取候选链接
    for idx, src in enumerate(sources, 1):
        print(f"[INFO] Source page {idx}/{len(sources)}: {src}")
        rows, err = extract_links_from_source_page(src)
        if err:
            errors.append(f"source {src} -> {err}")
        candidates.extend(rows)
        time.sleep(SLEEP_SECONDS)
        if len(candidates) >= MAX_CANDIDATES_PER_RUN:
            break

    # 2) 搜索引擎补充候选
    for idx, q in enumerate(queries, 1):
        if len(candidates) >= MAX_CANDIDATES_PER_RUN:
            break
        print(f"[INFO] Search {idx}/{len(queries)}: {q}")
        merged = []
        for fn in (search_tavily, search_serper, search_duckduckgo):
            rows, err = fn(q, MAX_SEARCH_RESULTS_PER_QUERY)
            if err:
                errors.append(err)
            merged.extend(rows)
            # 如果 API 搜索已经有结果，仍允许 DDG 补一点，但不重复过多
        candidates.extend(merged)
        time.sleep(SLEEP_SECONDS + random.random() * 0.5)

    # 3) 清洗候选
    seen_urls = set()
    clean_candidates: List[Candidate] = []
    for c in candidates:
        u = c.url.strip().split("#")[0]
        if not u.startswith("http"):
            continue
        if is_blocked(u, blocked_domains):
            continue
        # 过滤明显无关文件
        if re.search(r"\.(jpg|jpeg|png|gif|webp|pdf|zip|rar|7z|mp4|mp3)(\?|$)", u, re.I):
            continue
        if u in seen_urls:
            continue
        seen_urls.add(u)
        clean_candidates.append(Candidate(url=u, title=c.title, snippet=c.snippet, source=c.source))
        if len(clean_candidates) >= MAX_CANDIDATES_PER_RUN:
            break

    print(f"[INFO] Candidates collected: {len(clean_candidates)}")

    # 4) 抓正文评分
    scored: List[ScoredItem] = []
    for idx, c in enumerate(clean_candidates[:MAX_ARTICLES_TO_FETCH], 1):
        print(f"[INFO] Fetch article {idx}/{min(len(clean_candidates), MAX_ARTICLES_TO_FETCH)}: {c.url}")
        try:
            item = score_candidate(c, trusted_domains, extra_keywords)
            if item:
                scored.append(item)
                print(f"[HIT] score={item.score} title={item.title[:60]}")
        except Exception as exc:
            errors.append(f"article {c.url} -> {exc}")
        time.sleep(SLEEP_SECONDS)

    scored = dedupe(scored)
    print(f"[INFO] Scored hits: {len(scored)}")

    # 5) 去除已发送，并按“国外3+7、国内3+7”挑选本次推送
    new_items, skipped = select_report_items(scored, state)
    for it in new_items:
        key = hashlib.sha256((it.url + it.content_hash).encode("utf-8", "ignore")).hexdigest()[:20]
        state[key] = {
            "title": it.title,
            "url": it.url,
            "score": it.score,
            "source_category": it.source_category,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }

    # 控制 state 大小
    if len(state) > 1000:
        latest = sorted(state.items(), key=lambda kv: kv[1].get("sent_at", ""), reverse=True)[:800]
        state = dict(latest)

    report = make_report(new_items, skipped_count=skipped, errors=errors)
    REPORT_PATH.write_text(report, encoding="utf-8")
    save_state(state)

    print(report)
    if new_items or SEND_EMPTY_REPORT:
        pushplus_send("深度学习 / AI 优惠活动监控周报", report)
        print("[INFO] PushPlus sent.")
    else:
        print("[INFO] No new items and SEND_EMPTY_REPORT=false; skip push.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
