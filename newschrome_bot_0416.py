import requests
import feedparser
from datetime import datetime, timedelta
from openai import OpenAI
import time
import html
from urllib.parse import quote

print("시작됨")

# ✅ API 키
client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)

print(client.models.list())

# ✅ 네이버 API 키
NAVER_CLIENT_ID = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]

# ✅ Slack Webhook
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

# 🔥 키워드 그대로 유지
KEYWORDS = {
    "자사 및 경쟁사 동향": [
        "티맵", "티맵모빌리티", "TMAP", "우버",
        "카카오모빌리티", "카카오T", "쏘카",
        "네이버 지도", "카카오맵", "구글맵", "구글지도",
        "네이버 내비", "카카오 내비", "현대오토에버",
        "지도 데이터", "위치정보", "로보택시"
    ],
    "모빌리티 동향": [
        "현대차", "테슬라", "수입차",
        "전기차", "전기차 충전",
        "대리운전", "자율주행", "인포테인먼트", "SDV",
        "모빌리티 정책", "택시 규제", "자율주행 허가"
    ],
    "IT 업계 동향": [
        "AI", "빅테크", "엔비디아", "삼성전자",
        "구글", "애플", "쿠팡", "배민", "토스",
        "카카오", "네이버",
        "플랫폼 규제", "개인정보", "해킹",
        "데이터 정책", "검색 점유율", "지도 경쟁"
    ]
}

all_news = []
seen_links = set()
seen_titles = set()

def normalize_title(title):
    return html.unescape(title).replace(" ", "").lower()

# 🔹 1차 필터 (추가)
def pre_filter(news):
    result = []

    FILTER_KEYWORDS = [
        "티맵", "카카오", "자율주행", "전기차",
        "AI", "지도", "플랫폼", "데이터", "로보택시"
    ]

    EXCLUDE_WORDS = [
        "이벤트", "오픈", "기념", "화제", "눈길", "인기",
        "출시", "단순", "공개", "참여"
    ]

    IMPORTANT = [
        "규제", "정책", "자율주행", "전기차",
        "데이터", "AI", "플랫폼", "지도",
        "로보택시", "투자", "협력", "MOU"
    ]

    for title, link, category in news:

        if not any(k in title for k in FILTER_KEYWORDS):
            continue

        if any(x in title for x in EXCLUDE_WORDS):
            continue

        if len(title) < 15 or len(title) > 100:
            continue

        score = sum(1 for k in IMPORTANT if k in title)
        if score == 0:
            continue

        result.append((title, link, category))

    return result

# 🔹 네이버 뉴스
def get_naver_news(keyword):
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {
        "query": keyword,
        "display": 30,
        "sort": "date"
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        data = res.json()
    except:
        return []

    results = []
    for item in data.get("items", []):
        title = html.unescape(item["title"])
        link = item["link"]

        if "n.news.naver.com" in link:
            link = item.get("originallink", link)

        results.append((title, link))

    return results

# 🔹 Google News
def get_google_news(keyword):
    try:
        encoded_keyword = quote(keyword)
        url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(url)

        results = []
        for entry in feed.entries[:5]:
            results.append((entry.title, entry.link))

        return results
    except:
        return []

print("\n===== 뉴스 수집 시작 =====\n")

for category, keywords in KEYWORDS.items():
    print(f"\n===== {category} =====\n")

    for keyword in keywords:
        print(f"[수집 키워드] {keyword}")

        naver_news = get_naver_news(keyword)
        google_news = get_google_news(keyword)

        combined = naver_news + google_news

        for title, link in combined:
            try:
                norm = normalize_title(title)

                if not title or not link:
                    continue

                # 🔥 버그 수정
                if len(title) < 15 or len(title) > 100:
                    continue

                if norm in seen_titles:
                    continue

                if link in seen_links:
                    continue

                if any(x in link for x in [
                    "blog", "cafe", "help", "search",
                    "sports", "entertain"
                ]):
                    continue

                seen_titles.add(norm)
                seen_links.add(link)
                all_news.append((title, link, category))

            except:
                continue

print("\n===== 수집 완료 =====")
print("총 기사 개수:", len(all_news))

# 🔥 여기 추가 (핵심)
all_news = pre_filter(all_news)
print("필터링 후 기사 개수:", len(all_news))

if not all_news:
    print("수집된 기사가 없습니다.")
    raise SystemExit

# 🔹 GPT 재시도 함수
def call_gpt(prompt):
    for i in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"재시도 {i+1}:", e)
            time.sleep(5)

    return ""

def chunk_list(data, size):
    for i in range(0, len(data), size):
        yield data[i:i + size]

today = (datetime.utcnow() + timedelta(hours=9)).strftime("%y%m%d")

partial_results = []

print("\n===== GPT 1차 선별 시작 =====\n")

# 🔥 chunk 축소
chunks = list(chunk_list(all_news, 30))

for idx, chunk in enumerate(chunks, start=1):
    print(f"[{idx}/{len(chunks)}] GPT 1차 선별 중...")

    news_text = "\n".join([
        f"{category} | {title} | {link}"
        for title, link, category in chunk
    ])

    prompt = f"""
다음 뉴스 리스트에서 티맵모빌리티 홍보팀 기준으로 "이슈 단위 브리핑 가치"가 높은 기사만 선별하라.

중요: 기사 단위가 아니라 "이슈 단위"로 판단하라.

출력:
카테고리 | 기사 제목 | URL

뉴스:
{news_text}
"""

    result = call_gpt(prompt)

    if result:
        partial_results.append(result)

    time.sleep(2)

print("\n===== GPT 1차 선별 완료 =====\n")

if not partial_results:
    print("GPT 실패 → 원본 뉴스 출력")
    for title, link, category in all_news[:20]:
        print(category, title, link)
    raise SystemExit

final_input = "\n".join(partial_results)

final_prompt = f"""
다음은 1차 선별된 뉴스 목록이다.
이를 이슈 중심 미디어 브리핑으로 재구성하라.

[미디어브리핑-{today}]

■ 자사 및 경쟁사 동향
기사 제목
URL

■ 모빌리티 동향
기사 제목
URL

■ IT 업계 동향
기사 제목
URL

뉴스:
{final_input}
"""

print("\n===== 최종 브리핑 생성 중 =====\n")

final_result = call_gpt(final_prompt)

print("\n===== 최종 미디어브리핑 =====\n")
print(final_result)

requests.post(
    SLACK_WEBHOOK_URL,
    json={"text": final_result},
    timeout=30
)

print("Slack 전송 완료")