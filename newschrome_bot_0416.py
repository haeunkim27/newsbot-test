import os
import requests
import feedparser
from datetime import datetime, timedelta
from openai import OpenAI
import time
import html

print("시작됨")

# ✅ API 키
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

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

# ✅ 완화된 필터 (핵심)
def pre_filter(news):
    result = []

    for title, link, category in news:

        if not title or not link:
            continue

        if len(title) < 15 or len(title) > 120:
            continue

        if any(x in link for x in [
            "blog", "cafe", "sports", "entertain"
        ]):
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
        "display": 50,
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

        # 🔥 네이버 원문 링크 우선
        if "n.news.naver.com" in link:
            link = item.get("originallink", link)

        results.append((title, link))

    return results

print("\n===== 뉴스 수집 시작 =====\n")

for category, keywords in KEYWORDS.items():
    print(f"\n===== {category} =====\n")

    for keyword in keywords:
        print(f"[수집 키워드] {keyword}")

        news_list = get_naver_news(keyword)

        for title, link in news_list:
            try:
                norm = normalize_title(title)

                if norm in seen_titles:
                    continue

                if link in seen_links:
                    continue

                seen_titles.add(norm)
                seen_links.add(link)
                all_news.append((title, link, category))

            except:
                continue

print("\n===== 수집 완료 =====")
print("총 기사 개수:", len(all_news))

# 🔥 필터 적용
all_news = pre_filter(all_news)
print("필터링 후 기사 개수:", len(all_news))

if not all_news:
    print("수집된 기사가 없습니다.")
    raise SystemExit

# 🔹 GPT 호출
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
            time.sleep(3)

    return ""

def chunk_list(data, size):
    for i in range(0, len(data), size):
        yield data[i:i + size]

today = (datetime.utcnow() + timedelta(hours=9)).strftime("%y%m%d")

print("\n===== GPT 1차 선별 시작 =====\n")

chunks = list(chunk_list(all_news, 50))
partial_results = []

for idx, chunk in enumerate(chunks, start=1):
    print(f"[{idx}/{len(chunks)}] 처리 중...")

    news_text = "\n".join([
        f"{category} | {title} | {link}"
        for title, link, category in chunk
    ])

    prompt = f"""
다음 뉴스 리스트에서 티맵모빌리티 홍보팀 기준으로 "이슈 단위 브리핑 가치"가 높은 기사만 선별하라.

중요: 기사 단위가 아니라 "이슈 단위"로 판단하라.

단, 과도하게 제거하지 말고 활용 가능성이 있는 기사는 최대한 포함하라.

선별 원칙:
1. 동일 기사뿐 아니라 "같은 이슈"도 하나만 남겨라.
   - 동일 상품/서비스/발표/사건이면 1건만 선택
   - 가장 정보량 많고 대표성 있는 기사만 남겨라

2. 아래 기준 중 하나라도 충족하면 포함:
   - 사업 영향 (매출, 전략, 제휴, 규제 영향)
   - 시장 변화 신호 (경쟁 구도 변화, 기술 방향성)
   - PR 활용 가능성 (이슈 대응, 메시지 활용 가능)

3. 특히 제거:
   - 완전히 동일한 기사 (같은 링크)
   - 명백히 중복되는 단순 반복 기사

4. 반드시 포함 고려:
   - 티맵 직접 기사
   - 경쟁사 전략 변화
   - 플랫폼/지도/데이터 경쟁
   - 규제 및 정책 변화

우선순위:
1) 티맵 직접 영향
2) 경쟁사 전략 변화
3) 시장 구조 변화
4) 규제 / 정책
5) 기술 트렌드 (사업 영향 있는 경우만)

출력:
카테고리 | 기사 제목 | URL

출력:
카테고리 | 기사 제목 | URL

뉴스:
{news_text}
"""

    result = call_gpt(prompt)
    if result:
        partial_results.append(result)

    time.sleep(1.5)

print("\n===== 최종 브리핑 생성 =====\n")

final_input = "\n".join(partial_results)

final_prompt = f"""
다음은 1차 선별된 뉴스 목록이다.
이를 "이슈 중심 미디어 브리핑"으로 재구성하라.

핵심:
- 같은 이슈는 반드시 1건만 남길 것 (중복 기사 제거)
- 기사 요약 금지
- 설명 문장 금지
- 반드시 "기사 제목 + URL" 형태로만 출력

중요:
- 지나치게 많이 제거하지 말고, 브리핑 활용 가치가 있는 기사는 최대한 포함하라

선별 기준:
1. 동일 이슈 중복 금지 (대표 기사 1개만 선택)

2. 아래 중 최소 1개 충족해야 포함:
   - 사업 영향
   - 경쟁 구도 변화
   - 규제 / 정책 영향
   - 기술 변화가 사업에 미치는 영향

3. 반드시 포함:
   - 티맵 관련 핵심 기사 (있을 경우 최상단 배치)
   - 경쟁사 전략 변화
   - 플랫폼/데이터/지도 경쟁
   - 규제 및 정책 변화

4. 반드시 제거:
   - 완전히 동일한 기사
   - 단순 발표 / 할인 / 이벤트 / 반복 기사
   - PR 활용 가치 없는 기사

기사 수 규칙:
- 자사 및 경쟁사 동향: 최대 7건
- 모빌리티 동향: 최대 5건
- IT 업계 동향: 최대 5건
- 총 15건 내외 (너무 적거나 많지 않게 균형 맞출 것)

정렬 규칙:
1. 자사 기사 최상단
2. 같은 이슈끼리 묶기
3. 중요도 순 정렬

출력 형식 (절대 변경 금지):

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

⚠️ 절대 규칙:
- 위 형식에서 한 글자도 바꾸지 말 것
- 설명, 요약, 추가 문장 절대 금지
- 기사 제목과 URL 외 아무 것도 출력하지 말 것

뉴스:
{final_input}
"""

final_result = call_gpt(final_prompt)

print("\n===== 결과 =====\n")
print(final_result)

requests.post(
    SLACK_WEBHOOK_URL,
    json={"text": final_result},
    timeout=30
)

print("Slack 전송 완료")