#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI / 深度学习优惠活动网页监控器

目标：
1. 不依赖 B站/小红书/知乎登录态；
2. 抓公开网页、官方公告页、CSDN/掘金/博客园等技术社区；
3. 每类来源先保留一定候选，再抓正文筛选，避免国外官网占满全部名额；
4. 优惠词为主，AI词为辅；
5. 国内/国外分别输出：官号3条 + 情报7条，最多20条；
6. PushPlus 推送。
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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

MAX_SEARCH_RESULTS_PER_QUERY = int(os.getenv("MAX_SEARCH_RESULTS_PER_QUERY", "3"))
MAX_SEARCH_QUERIES = int(os.getenv("MAX_SEARCH_QUERIES", "80"))
MAX_SOURCE_PAGES = int(os.getenv("MAX_SOURCE_PAGES", "90"))
MAX_SOURCE_LINKS_PER_PAGE = int(os.getenv("MAX_SOURCE_LINKS_PER_PAGE", "24"))
MAX_CANDIDATES_PER_RUN = int(os.getenv("MAX_CANDIDATES_PER_RUN", "280"))
MAX_ARTICLES_TO_FETCH = int(os.getenv("MAX_ARTICLES_TO_FETCH", "90"))

CATEGORY_FETCH_FOREIGN_OFFICIAL = int(os.getenv("CATEGORY_FETCH_FOREIGN_OFFICIAL", "18"))
CATEGORY_FETCH_FOREIGN_INTEL = int(os.getenv("CATEGORY_FETCH_FOREIGN_INTEL", "22"))
CATEGORY_FETCH_DOMESTIC_OFFICIAL = int(os.getenv("CATEGORY_FETCH_DOMESTIC_OFFICIAL", "22"))
CATEGORY_FETCH_DOMESTIC_INTEL = int(os.getenv("CATEGORY_FETCH_DOMESTIC_INTEL", "28"))

MIN_SCORE_TO_REPORT = int(os.getenv("MIN_SCORE_TO_REPORT", "18"))
MIN_PROMO_HITS = int(os.getenv("MIN_PROMO_HITS", "1"))
MIN_AI_HITS = int(os.getenv("MIN_AI_HITS", "1"))
MIN_TOTAL_KEYWORD_HITS = int(os.getenv("MIN_TOTAL_KEYWORD_HITS", "3"))
MIN_STRONG_PROMO_HITS = int(os.getenv("MIN_STRONG_PROMO_HITS", "2"))
MIN_DEAL_SIGNAL_HITS = int(os.getenv("MIN_DEAL_SIGNAL_HITS", "1"))

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))
SLEEP_SECONDS = float(os.getenv("SLEEP_SECONDS", "0.15"))
SEND_EMPTY_REPORT = os.getenv("SEND_EMPTY_REPORT", "false").lower() in {"1", "true", "yes"}
ENABLE_DDG_SEARCH = os.getenv("ENABLE_DDG_SEARCH", "true").lower() in {"1", "true", "yes"}
ADD_YEAR_VARIANTS = os.getenv("ADD_YEAR_VARIANTS", "false").lower() in {"1", "true", "yes"}

MAX_FOREIGN_OFFICIAL_REPORT_ITEMS = int(os.getenv("MAX_FOREIGN_OFFICIAL_REPORT_ITEMS", "3"))
MAX_FOREIGN_INTEL_REPORT_ITEMS = int(os.getenv("MAX_FOREIGN_INTEL_REPORT_ITEMS", "7"))
MAX_DOMESTIC_OFFICIAL_REPORT_ITEMS = int(os.getenv("MAX_DOMESTIC_OFFICIAL_REPORT_ITEMS", "3"))
MAX_DOMESTIC_INTEL_REPORT_ITEMS = int(os.getenv("MAX_DOMESTIC_INTEL_REPORT_ITEMS", "7"))

PROMO_KEYWORDS = [
    # 中文：免费/优惠/领取
    "免费", "限免", "白嫖", "薅羊毛", "羊毛", "福利", "礼包", "补贴", "优惠", "优惠活动",
    "折扣", "打折", "半价", "低至", "立减", "满减", "减免", "返现", "买赠", "促销", "特惠",
    "领取", "申请", "注册", "注册送", "一键领取", "开放领取", "活动入口", "申请入口", "领取入口",
    "兑换", "兑换码", "邀请码", "优惠码", "折扣码", "促销码",

    # 中文：额度/券/token/API/算力
    "额度", "免费额度", "赠送额度", "新用户额度", "新人额度", "试用额度", "调用额度",
    "API额度", "推理额度", "模型额度", "训练额度", "算力额度", "开发者额度",
    "优惠券", "代金券", "抵扣券", "算力券", "资源券", "云券", "GPU券", "训练券", "推理券",
    "token", "tokens", "免费token", "免费 token", "赠送token", "赠送 token", "token额度", "Token Plan",

    # 中文：学生/教育/科研
    "学生优惠", "教育优惠", "校园优惠", "高校优惠", "学生免费", "学生认证", "教育认证",
    "学术认证", "edu认证", "学生专享", "学生福利", "学生计划", "教育计划", "科研优惠",
    "科研额度", "学术额度", "实验室额度", "课题组额度",

    # 中文：开发者/开源/创业/比赛
    "开发者计划", "开发者活动", "开发者福利", "开发者优惠", "开发者免费", "开发者补贴",
    "开源项目免费", "开源项目额度", "创业扶持", "创业计划", "初创额度", "初创优惠",
    "黑客松算力", "比赛算力", "竞赛算力", "挑战赛额度", "训练营免费",

    # English：discount/free/credits
    "free", "free trial", "free tier", "free plan", "free access", "limited time free", "limited-time free",
    "free credits", "free credit", "trial credits", "promo credits", "bonus credits", "cloud credits",
    "compute credits", "gpu credits", "api credits", "inference credits", "model credits", "token credits",
    "free tokens", "free token", "bonus tokens", "free quota", "free allowance", "free usage",
    "coupon", "coupon code", "promo code", "discount code", "voucher", "redeem code", "giveaway",
    "discount", "student discount", "education discount", "academic discount", "developer credits",
    "student credits", "student plan", "student pack", "startup credits", "research credits",
    "grant", "offer", "limited offer", "special offer", "launch offer", "price cut", "price reduction",
    "pricing update",
]

AI_KEYWORDS = [
    "ai", "人工智能", "深度学习", "机器学习", "大模型", "llm", "aigc", "agent", "智能体",
    "api", "模型", "推理", "训练", "微调", "embedding", "rag", "gpu", "算力", "云服务器", "云资源",
    "gemini", "claude", "openai", "chatgpt", "github copilot", "copilot", "hugging face", "huggingface",
    "deepseek", "kimi", "通义", "千问", "qwen", "百炼", "火山方舟", "豆包", "混元", "千帆", "文心",
    "智谱", "glm", "bigmodel", "硅基流动", "siliconflow", "modelscope", "魔搭", "modelarts", "昇腾",
    "mimo", "xiaomi", "小米", "vivo", "字节", "火山", "微软", "azure", "aws", "google cloud",
    "runpod", "modal", "together ai", "openrouter", "autodl", "矩池云", "趋动云",
]

ACTION_KEYWORDS = [
    "领取", "申请", "注册", "认证", "学生认证", "教育认证", "学术认证", "edu认证", "兑换",
    "入口", "活动入口", "领取入口", "申请入口", "有效期", "截止", "限时", "名额", "资格",
    "开通", "升级", "降价", "价格下调", "价格调整", "优惠券", "代金券", "抵扣券", "算力券",
    "apply", "claim", "register", "redeem", "deadline", "get started", "start for free",
    "apply now", "claim now", "limited time", "pricing", "price cut", "price reduction",
]

# 强优惠词：必须命中至少一定数量，避免普通AI新闻误入
STRONG_PROMO_KEYWORDS = [
    # 免费额度 / token / API
    "免费额度", "赠送额度", "新用户额度", "新人额度", "注册额度", "注册送额度", "注册送",
    "调用额度", "api额度", "API额度", "推理额度", "模型额度", "训练额度", "试用额度",
    "每月额度", "月度额度", "免费调用", "免费推理", "免费生成", "免费对话", "免费问答",
    "免费使用", "免费开放", "限时免费", "限免", "公测免费", "免费试用", "开放体验",
    "免费申请", "免费领取", "领取入口", "活动入口", "申请入口",

    "免费token", "免费 token", "赠送token", "赠送 token", "送token", "送 token",
    "token额度", "token 额度", "tokens额度", "tokens 额度", "token plan", "Token Plan",
    "API token", "api token", "免费API", "免费 API", "API免费", "API 免费",

    # 优惠券 / 代金券 / 码
    "优惠券", "代金券", "抵扣券", "折扣券", "算力券", "资源券", "云券", "GPU券",
    "训练券", "推理券", "体验券", "兑换券", "满减券", "折扣码", "优惠码", "兑换码",
    "邀请码", "领取码", "促销码", "券包", "礼包码", "福利码",

    # 价格优惠
    "限时优惠", "限时折扣", "价格优惠", "套餐优惠", "订阅优惠", "会员优惠",
    "打折", "折扣", "半价", "低至", "立减", "满减", "减免", "补贴", "返现",
    "充值返", "买赠", "特惠", "促销", "降价", "价格下调", "价格调整", "价格减免",

    # 学生 / 教育 / 科研
    "学生优惠", "教育优惠", "校园优惠", "高校优惠", "学生免费", "学生专享",
    "学生福利", "学生认证", "教育认证", "学术认证", "edu认证", "学生套餐",
    "学生计划", "校园计划", "高校计划", "教育计划", "学术计划", "教师优惠",
    "教师认证", "科研优惠", "科研额度", "学术额度", "实验室额度", "课题组额度",

    # 开发者 / 开源 / 创业 / 比赛
    "开发者计划", "开发者活动", "开发者优惠", "开发者免费", "开发者额度",
    "开发者福利", "开发者补贴", "开源项目额度", "开源项目免费", "开源免费",
    "创业扶持", "创业计划", "初创额度", "初创免费", "初创优惠", "黑客松额度",
    "黑客松算力", "竞赛算力", "比赛算力", "大赛算力", "挑战赛额度", "训练营免费",

    # GPU / 云 / 算力
    "免费算力", "算力免费", "算力福利", "算力优惠", "算力补贴", "算力额度",
    "免费GPU", "免费 GPU", "GPU免费", "GPU 免费", "GPU福利", "GPU优惠", "GPU额度",
    "免费云服务器", "云服务器免费", "云服务器试用", "免费云资源", "云资源免费",
    "免费云主机", "免费Notebook", "免费 Notebook", "免费开发环境", "免费实验环境",
    "免费显卡", "显卡免费",

    # English：free / credits / tokens
    "free credits", "free credit", "bonus credits", "promo credits", "trial credits",
    "cloud credits", "compute credits", "gpu credits", "api credits", "inference credits",
    "model credits", "monthly credits", "usage credits", "token credits",
    "free tokens", "free token", "bonus tokens", "complimentary tokens", "token giveaway",
    "tokens giveaway", "free token credits", "free quota", "free allowance", "free usage",
    "free api calls", "free inference", "free compute",

    # English：free tier / trial
    "free tier", "free plan", "free access", "free trial", "limited time free",
    "limited-time free", "free for limited time", "trial offer", "special offer",
    "launch offer", "early access", "get started for free", "start building free",

    # English：coupon / discount
    "discount", "discounted", "coupon", "voucher", "promo code", "coupon code",
    "redeem code", "promotion code", "referral code", "deal", "deals", "offer",
    "offers", "giveaway", "grant", "subsidy", "limited offer", "student deal",
    "developer deal", "price cut", "price reduction", "pricing update", "discount promotion",

    # English：student / education / developer
    "student discount", "student offer", "student free", "free for students",
    "student credits", "student plan", "student pack", "student developer pack",
    "education discount", "education offer", "academic discount", "academic credits",
    "edu discount", "edu offer", "campus offer", "developer credits",
    "developer offer", "developer program", "developer grant", "startup credits",
    "startup program", "startup offer", "research credits", "research grant",
    "open source credits",

    # 典型活动/平台表达
    "GitHub Student Developer Pack", "Azure for Students", "Google AI Studio free",
    "Gemini API free", "Gemini free tier", "Copilot student", "Claude credits",
    "OpenAI credits", "DeepSeek pricing", "DeepSeek discount", "百炼免费额度",
    "火山方舟免费额度", "硅基流动免费额度", "智谱免费token", "魔搭免费算力",
    "AutoDL优惠", "矩池云优惠", "趋动云优惠",
]

# 更强的“活动信号”：只出现 free/token/api 不够，还要尽量出现这些
DEAL_SIGNAL_KEYWORDS = [
    "领取", "申请", "注册", "注册送", "认证", "兑换", "入口", "活动入口", "领取入口", "申请入口",
    "有效期", "截止", "限时", "名额", "资格", "优惠券", "代金券", "算力券", "兑换码",
    "折扣码", "优惠码", "价格下调", "价格调整", "降价", "免费额度", "赠送额度",
    "学生认证", "教育认证", "开发者计划", "开发者额度",
    "claim", "apply", "register", "redeem", "deadline", "coupon code", "promo code",
    "discount code", "free credits", "promo credits", "trial credits", "student discount",
    "developer credits", "price cut", "price reduction", "pricing update", "limited offer",
    "get started for free", "apply now", "claim now",
]

NEGATIVE_KEYWORDS = [
    "二手", "破解", "盗版", "账号出租", "代充", "接码", "灰产", "博彩", "成人", "色情",
    "vpn机场", "返佣软文", "网盘资源", "破解版", "会员共享", "账号共享",
]

DATE_PATTERNS = [
    r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})",
    r"(20\d{2}[-/.年]\d{1,2})",
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
    "producthunt.com", "indiehackers.com", "hackernews.com", "news.ycombinator.com", "techcrunch.com",
    "theverge.com", "dev.to", "medium.com",
]

DOMESTIC_INTEL_DOMAINS = [
    "csdn.net", "blog.csdn.net", "juejin.cn", "cnblogs.com", "oschina.net", "infoq.cn", "jiqizhixin.com",
    "qbitai.com", "aibase.com", "36kr.com", "geekpark.net", "sspai.com", "leiphone.com", "ifanr.com",
    "segmentfault.com", "51cto.com",
]

CATEGORY_LABELS = {
    "foreign_official": "国外大厂官号",
    "foreign_intel": "国外优惠活动情报账户/网站",
    "domestic_official": "国内大厂官号",
    "domestic_intel": "国内优惠活动情报账户/网站",
}

CATEGORY_FETCH_LIMITS = {
    "foreign_official": CATEGORY_FETCH_FOREIGN_OFFICIAL,
    "foreign_intel": CATEGORY_FETCH_FOREIGN_INTEL,
    "domestic_official": CATEGORY_FETCH_DOMESTIC_OFFICIAL,
    "domestic_intel": CATEGORY_FETCH_DOMESTIC_INTEL,
}


@dataclass
class Candidate:
    url: str
    title: str = ""
    snippet: str = ""
    source: str = ""
    hint_category: str = ""
    rough_score: int = 0


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
    strong_hits: int
    deal_signal_hits: int
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
    d = domain_of(url)
    path = urlparse(url).path.lower()

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
    return keyword_hits(text, STRONG_PROMO_KEYWORDS)


def deal_signal_hits(text: str) -> Tuple[int, List[str]]:
    return keyword_hits(text, DEAL_SIGNAL_KEYWORDS)


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


def rough_score_candidate(c: Candidate) -> int:
    text = " ".join([c.url, c.title, c.snippet, c.source])
    promo, _ = keyword_hits(text, PROMO_KEYWORDS)
    ai, _ = keyword_hits(text, AI_KEYWORDS)
    action, _ = keyword_hits(text, ACTION_KEYWORDS)
    strong, _ = strong_promo_hits(text)
    signal, _ = deal_signal_hits(text)
    d = domain_of(c.url)
    cat = classify_source(c.url, c.title, c.snippet)

    score = 0
    score += min(strong, 5) * 8
    score += min(signal, 5) * 6
    score += min(promo, 8) * 2
    score += min(action, 5) * 3
    score += min(ai, 5) * 1
    if cat in {"foreign_official", "domestic_official"}:
        score += 3
    if domain_matches(d, DOMESTIC_INTEL_DOMAINS):
        score += 2
    if any(x in text.lower() for x in ["site:blog.csdn.net", "csdn", "掘金", "juejin", "博客园"]):
        score += 2
    return score


def extract_links_from_source_page(url: str, max_links: int = 24) -> Tuple[List[Candidate], Optional[str]]:
    try:
        r = session().get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            return [], f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.text, "lxml")
        base_domain = domain_of(r.url)
        source_cat = classify_source(r.url)
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
            if domain_of(link) != base_domain and not domain_of(link).endswith("." + base_domain):
                continue
            title = norm_space(a.get_text(" "), 250)
            if len(title) < 4:
                continue
            clean = link.split("#")[0]
            if clean in seen:
                continue
            seen.add(clean)
            candidates.append(Candidate(
                url=clean,
                title=title,
                snippet="",
                source=f"Source page: {url}",
                hint_category=source_cat,
            ))
            if len(candidates) >= max_links:
                break
        return candidates, None
    except Exception as exc:
        return [], str(exc)


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


def looks_like_plain_model_release(title: str) -> bool:
    t = title.lower()
    release_words = [
        "introducing", "announcing", "launching", "released", "now available",
        "发布", "推出", "上线", "正式发布", "现已推出", "可用",
    ]
    deal_words = STRONG_PROMO_KEYWORDS + DEAL_SIGNAL_KEYWORDS
    has_release = any(w in t for w in release_words)
    has_deal_in_title = any(w.lower() in t for w in deal_words)
    return has_release and not has_deal_in_title


def score_candidate(c: Candidate, trusted_domains: List[str], extra_keywords: List[str]) -> Optional[ScoredItem]:
    title, desc, body, err = fetch_page(c.url)
    full_title = title or c.title or "无标题"
    full_text = norm_space("\n".join([c.title, c.snippet, title, desc, body]), 30000)
    if not full_text or len(full_text) < 40:
        return None

    promo_hits, promo_words = keyword_hits(full_text, PROMO_KEYWORDS)
    ai_hits, ai_words = keyword_hits(full_text, AI_KEYWORDS)
    action_hits, action_words = keyword_hits(full_text, ACTION_KEYWORDS)
    strong_hits, strong_words = strong_promo_hits(full_text)
    deal_hits, deal_words = deal_signal_hits(full_text)
    neg_hits, _ = keyword_hits(full_text, NEGATIVE_KEYWORDS)
    extra_hits, extra_words = keyword_hits(full_text, extra_keywords)

    title_text = (full_title + " " + c.title).lower()
    title_promo_hits, _ = keyword_hits(title_text, PROMO_KEYWORDS)
    title_ai_hits, _ = keyword_hits(title_text, AI_KEYWORDS)
    title_action_hits, _ = keyword_hits(title_text, ACTION_KEYWORDS)
    title_strong_hits, _ = strong_promo_hits(title_text)
    title_deal_hits, _ = deal_signal_hits(title_text)

    d = domain_of(c.url)
    trusted = any(d == x or d.endswith("." + x) for x in trusted_domains)

    total_hits = promo_hits + ai_hits + action_hits + strong_hits + deal_hits + extra_hits

    if promo_hits < MIN_PROMO_HITS:
        return None
    if ai_hits < MIN_AI_HITS:
        return None
    if total_hits < MIN_TOTAL_KEYWORD_HITS:
        return None
    if strong_hits + title_strong_hits < MIN_STRONG_PROMO_HITS:
        return None
    if deal_hits + title_deal_hits < MIN_DEAL_SIGNAL_HITS:
        return None

    if looks_like_plain_model_release(full_title) and title_deal_hits == 0 and title_strong_hits == 0:
        return None

    score = 0
    # 优惠词主导
    score += min(strong_hits, 10) * 6
    score += min(deal_hits, 10) * 5
    score += title_strong_hits * 8
    score += title_deal_hits * 8
    score += min(promo_hits, 10) * 2
    score += min(action_hits, 8) * 2

    # AI词只作为辅助
    score += min(ai_hits, 8) * 1
    score += title_ai_hits * 1
    score += min(extra_hits, 5) * 2

    if trusted:
        score += 5
    if any(x in full_text for x in ["官方", "官网", "活动规则", "有效期", "截止", "领取地址", "申请入口"]):
        score += 5
    if any(x.lower() in full_text.lower() for x in ["official", "deadline", "terms", "apply", "claim", "redeem"]):
        score += 4
    if "pricing" in full_text.lower() or "价格" in full_text:
        score += 3
    if neg_hits:
        score -= 10
    if len(body) < 120:
        score -= 3

    if score < MIN_SCORE_TO_REPORT:
        return None

    snippet = norm_space(desc or c.snippet or body[:400], 500)
    matched = sorted(set(promo_words + ai_words + action_words + strong_words + deal_words + extra_words))[:30]
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
        strong_hits=strong_hits,
        deal_signal_hits=deal_hits,
        matched_keywords=matched,
        published_guess=guess_date(full_text[:3000]),
        content_hash=chash,
        source_category=source_category,
    )


def dedupe_candidates(candidates: List[Candidate], blocked_domains: List[str]) -> List[Candidate]:
    seen_urls = set()
    clean: List[Candidate] = []
    for c in candidates:
        u = c.url.strip().split("#")[0]
        if not u.startswith("http"):
            continue
        if is_blocked(u, blocked_domains):
            continue
        if re.search(r"\.(jpg|jpeg|png|gif|webp|pdf|zip|rar|7z|mp4|mp3)(\?|$)", u, re.I):
            continue
        if u in seen_urls:
            continue
        seen_urls.add(u)
        c.url = u
        c.rough_score = rough_score_candidate(c)
        clean.append(c)
        if len(clean) >= MAX_CANDIDATES_PER_RUN:
            break
    return clean


def balance_candidates_for_fetch(candidates: List[Candidate]) -> List[Candidate]:
    buckets: Dict[str, List[Candidate]] = {
        "foreign_official": [],
        "foreign_intel": [],
        "domestic_official": [],
        "domestic_intel": [],
    }

    for c in candidates:
        cat = c.hint_category or classify_source(c.url, c.title, c.snippet)
        if cat not in buckets:
            cat = "domestic_intel" if has_chinese(c.title + c.snippet + c.url) else "foreign_intel"
        buckets[cat].append(c)

    for cat in buckets:
        buckets[cat].sort(key=lambda x: x.rough_score, reverse=True)

    selected: List[Candidate] = []
    selected_urls = set()

    # 先强制每类进入一定数量，解决“国外官网占满候选”的问题
    for cat in ["foreign_official", "foreign_intel", "domestic_official", "domestic_intel"]:
        limit = CATEGORY_FETCH_LIMITS.get(cat, 20)
        for c in buckets[cat][:limit]:
            if c.url not in selected_urls:
                selected.append(c)
                selected_urls.add(c.url)

    # 如果总数还没到上限，用所有剩余候选按粗评分补齐
    if len(selected) < MAX_ARTICLES_TO_FETCH:
        rest = []
        for rows in buckets.values():
            for c in rows:
                if c.url not in selected_urls:
                    rest.append(c)
        rest.sort(key=lambda x: x.rough_score, reverse=True)
        for c in rest:
            if len(selected) >= MAX_ARTICLES_TO_FETCH:
                break
            selected.append(c)
            selected_urls.add(c.url)

    return selected[:MAX_ARTICLES_TO_FETCH]


def dedupe_items(items: List[ScoredItem]) -> List[ScoredItem]:
    best: Dict[str, ScoredItem] = {}
    for it in items:
        p = urlparse(it.url)
        base = f"{p.netloc}{p.path}".rstrip("/")
        title_norm = re.sub(r"\W+", "", it.title.lower())[:50]
        key = hashlib.sha256((base + title_norm).encode("utf-8", "ignore")).hexdigest()[:16]
        if key not in best or it.score > best[key].score:
            best[key] = it
    return sorted(best.values(), key=lambda x: x.score, reverse=True)


def select_report_items(scored: List[ScoredItem], state: Dict[str, dict]) -> Tuple[List[ScoredItem], int]:
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
        buckets.setdefault(it.source_category, []).append(it)

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
            "筛选规则：每类来源先保留固定数量候选，再抓正文用强优惠词筛选；"
            "国外官号最多 "
            f"{MAX_FOREIGN_OFFICIAL_REPORT_ITEMS} 条，国外情报最多 {MAX_FOREIGN_INTEL_REPORT_ITEMS} 条；"
            "国内官号最多 "
            f"{MAX_DOMESTIC_OFFICIAL_REPORT_ITEMS} 条，国内情报最多 {MAX_DOMESTIC_INTEL_REPORT_ITEMS} 条。"
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
                lines.append(f"- 强优惠词命中：{it.strong_hits}；活动信号命中：{it.deal_signal_hits}")
                lines.append(f"- 命中词：{', '.join(it.matched_keywords[:16])}")
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
    queries = current_year_queries(read_lines(CONFIG / "search_queries.txt"))[:MAX_SEARCH_QUERIES]
    sources = read_lines(CONFIG / "web_sources.txt")[:MAX_SOURCE_PAGES]

    errors: List[str] = []
    candidates: List[Candidate] = []

    # 1) 先搜索关键词，避免官网首页普通AI新闻占满候选
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
        candidates.extend(merged)
        time.sleep(SLEEP_SECONDS + random.random() * 0.25)

    # 2) 再访问官方/社区入口页，补充官网和固定网站来源
    for idx, src in enumerate(sources, 1):
        if len(candidates) >= MAX_CANDIDATES_PER_RUN:
            break
        print(f"[INFO] Source page {idx}/{len(sources)}: {src}")
        rows, err = extract_links_from_source_page(src, max_links=MAX_SOURCE_LINKS_PER_PAGE)
        if err:
            errors.append(f"source {src} -> {err}")
        candidates.extend(rows)
        time.sleep(SLEEP_SECONDS)

    clean_candidates = dedupe_candidates(candidates, blocked_domains)
    print(f"[INFO] Candidates collected after dedupe: {len(clean_candidates)}")

    selected_candidates = balance_candidates_for_fetch(clean_candidates)
    cat_counts: Dict[str, int] = {"foreign_official": 0, "foreign_intel": 0, "domestic_official": 0, "domestic_intel": 0}
    for c in selected_candidates:
        cat = c.hint_category or classify_source(c.url, c.title, c.snippet)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print(f"[INFO] Candidates selected for full fetch: {len(selected_candidates)}")
    print(f"[INFO] Fetch category quotas: {cat_counts}")

    # 3) 抓正文评分
    scored: List[ScoredItem] = []
    for idx, c in enumerate(selected_candidates, 1):
        print(f"[INFO] Fetch article {idx}/{len(selected_candidates)}: {c.url}")
        try:
            item = score_candidate(c, trusted_domains, extra_keywords)
            if item:
                scored.append(item)
                print(f"[HIT] score={item.score} cat={item.source_category} title={item.title[:70]}")
        except Exception as exc:
            errors.append(f"article {c.url} -> {exc}")
        time.sleep(SLEEP_SECONDS)

    scored = dedupe_items(scored)
    print(f"[INFO] Scored hits: {len(scored)}")

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
