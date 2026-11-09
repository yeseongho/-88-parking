from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import os
import asyncio
import sqlite3
import csv
import io
import json
import math
import time
import re
import html
import xml.etree.ElementTree as ET

from pathlib import Path
from html.parser import HTMLParser

import httpx

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse


# ======================================
# 1. 환경변수 불러오기
# ======================================

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

PERFORMANCE_API_KEY = os.getenv(
    "OLPARK_PERFORMANCE_API_KEY"
)

PERFORMANCE_API_URL = (
    "https://api.kcisa.kr"
    "/openapi/service/rest/meta/KSCperf"
)


# ======================================
# 2. FastAPI 서버 설정
# ======================================

app = FastAPI(
    title="OLPARK 88 FLOW API",
    description="올림픽공원 AI 주차 혼잡 예측 서비스",
    version="1.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "https://yeseongho.github.io"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)


# ======================================
# 3. 서버 작동 확인
# ======================================

@app.get("/")
def home():
    return {
        "service": "OLPARK 88 FLOW",
        "message": "백엔드 서버가 정상적으로 실행 중입니다.",
        "status": "success"
    }


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "message": "API 서버 연결 성공"
    }


# ======================================
# 4. HTML 태그 제거 기능
# ======================================

class HTMLTextExtractor(HTMLParser):

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):

        if tag in ("script", "style"):
            self.skip_depth += 1

        elif tag in ("br", "p", "div", "li"):
            self.text_parts.append(" ")

    def handle_endtag(self, tag):

        if tag in ("script", "style"):
            self.skip_depth = max(
                0,
                self.skip_depth - 1
            )

        elif tag in ("p", "div", "li"):
            self.text_parts.append(" ")

    def handle_data(self, data):

        if self.skip_depth == 0:
            self.text_parts.append(data)

    def get_text(self):
        return " ".join(self.text_parts)


# ======================================
# 5. HTML 텍스트 정제 함수
# ======================================

def clean_html_text(raw_text):

    if not raw_text:
        return ""

    # HTML 특수문자 변환
    text = html.unescape(raw_text)

    # HTML 태그 제거
    parser = HTMLTextExtractor()
    parser.feed(text)

    text = parser.get_text()

    # 연속 공백 제거
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ======================================
# 6. 공연정보 XML 데이터 처리
# ======================================

def parse_performance_xml(xml_text):

    root = ET.fromstring(xml_text)

    # XML 네임스페이스 제거
    for element in root.iter():

        if isinstance(element.tag, str):
            element.tag = element.tag.split("}")[-1]

    # API 응답 상태 확인
    result_code = root.findtext(".//resultCode")
    result_message = root.findtext(".//resultMsg")

    # 00과 0000 모두 정상 응답
    if result_code and result_code not in ("00", "0000"):

        raise HTTPException(
            status_code=502,
            detail={
                "result_code": result_code,
                "message": result_message
            }
        )

    # 공연 데이터 저장 리스트
    items = []

    # 공연 데이터 반복 처리
    for item in root.findall(".//item"):

        def get_value(name):
            return (
                item.findtext(name) or ""
            ).strip()

        # 공연정보 정제
        performance = {

            "title": clean_html_text(
                get_value("title")
            ),

            "place": clean_html_text(
                get_value("spatial")
            ),

            "period": clean_html_text(
                get_value("temporalCoverage")
            ),

            "description": clean_html_text(
                get_value("description")
            ),

            "creator": clean_html_text(
                get_value("creator")
            ),

            "registration_date": get_value(
                "regDate"
            )
        }

        # 정제된 공연 데이터 추가
        items.append(performance)

    return items


# ======================================
# 7. 올림픽공원 공연정보 API 호출
# ======================================

@app.get("/api/performances")
async def get_performances():

    # 인증키 확인
    if not PERFORMANCE_API_KEY:

        raise HTTPException(
            status_code=500,
            detail="공연정보 API 인증키가 설정되지 않았습니다."
        )

    # API 요청 파라미터
    params = {
        "serviceKey": PERFORMANCE_API_KEY,
        "numOfRows": "10",
        "pageNo": "1"
    }

    # 외부 API 호출
    try:

        async with httpx.AsyncClient(
            timeout=20.0
        ) as client:

            response = await client.get(
                PERFORMANCE_API_URL,
                params=params
            )

            response.raise_for_status()

    except httpx.HTTPError:

        raise HTTPException(
            status_code=502,
            detail="공연정보 API 호출에 실패했습니다."
        )

    # XML 데이터 분석
    try:

        performances = parse_performance_xml(
            response.text
        )

    except ET.ParseError:

        raise HTTPException(
            status_code=502,
            detail="공연정보 API 응답을 XML로 해석할 수 없습니다."
        )

    # JSON 결과 반환
    return {
        "status": "success",
        "count": len(performances),
        "performances": performances
    }

# ======================================
# 8. 공연정보 원본 필드 확인 (개발용)
# ======================================

@app.get("/api/performances/debug-fields")
async def debug_performance_fields():

    if not PERFORMANCE_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="API 인증키가 없습니다."
        )

    params = {
        "serviceKey": PERFORMANCE_API_KEY,
        "numOfRows": "3",
        "pageNo": "1"
    }

    try:
        async with httpx.AsyncClient(
            timeout=20.0
        ) as client:

            response = await client.get(
                PERFORMANCE_API_URL,
                params=params
            )

            response.raise_for_status()

    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="공연정보 API 호출 실패"
        )

    try:
        root = ET.fromstring(response.text)

    except ET.ParseError:
        raise HTTPException(
            status_code=502,
            detail="XML 응답 분석 실패"
        )

    # XML 네임스페이스 제거
    for element in root.iter():
        if isinstance(element.tag, str):
            element.tag = element.tag.split("}")[-1]

    result = []

    # 첫 3개 공연의 원본 필드 확인
    for item in root.findall(".//item"):

        fields = {}

        for child in item:

            value = child.text or ""

            # HTML 태그 제거
            value = clean_html_text(value)

            # 너무 긴 설명은 일부만 표시
            if len(value) > 150:
                value = value[:150] + "..."

            fields[child.tag] = value

        result.append(fields)

    return {
        "status": "success",
        "count": len(result),
        "raw_fields": result
    }


# ======================================
# 9. 올림픽공원 연계 데이터 API 확인
# ======================================

LINKED_API_URL = (
    "https://api.kcisa.kr"
    "/openapi/API_CPM_009/request"
)


@app.get("/api/linked-data")
async def get_linked_data():

    linked_api_key = os.getenv(
        "OLPARK_LINKED_API_KEY"
    )

    if not linked_api_key:
        raise HTTPException(
            status_code=500,
            detail="연계 데이터 API 인증키가 없습니다."
        )

    params = {
        "serviceKey": linked_api_key,
        "numOfRows": "5",
        "pageNo": "1"
    }

    try:
        async with httpx.AsyncClient(
            timeout=20.0
        ) as client:

            response = await client.get(
                LINKED_API_URL,
                params=params
            )

            response.raise_for_status()


    except httpx.HTTPStatusError as error:

        # 공공 API 서버가 반환한 HTTP 상태 코드
        status = error.response.status_code

        raise HTTPException(
            status_code=502,
            detail={
                "message": "공공 API 서버가 오류를 반환했습니다.",
                "external_status_code": status
            }
        )

    except httpx.RequestError as error:

        # 네트워크 연결 관련 오류
        raise HTTPException(
            status_code=502,
            detail={
                "message": "공공 API 서버 연결에 실패했습니다.",
                "error_type": type(error).__name__
            }
        )

    # 응답 XML을 그대로 JSON 문자열로 반환
    # 실제 데이터 구조 확인용
    return {
        "status": "success",
        "response_preview": response.text[:5000]
    }


# ======================================
# 10. 기상청 단기예보 API 연결
# ======================================

KMA_API_URL = (
    "https://apis.data.go.kr"
    "/1360000/VilageFcstInfoService_2.0"
    "/getVilageFcst"
)


@app.get("/api/weather/test")
async def test_weather_api():

    load_dotenv(BASE_DIR / ".env", override=True)

    weather_api_key = os.getenv("KMA_API_KEY")

    print("ENV 파일 존재:", (BASE_DIR / ".env").is_file())
    print("기상청 인증키 설정:", bool(weather_api_key))

    if not weather_api_key:
        raise HTTPException(
            status_code=500,
            detail="기상청 API 인증키가 없습니다."
        )

    # 한국 시간 기준
    now = datetime.now(ZoneInfo("Asia/Seoul"))

    # 안정적으로 조회하기 위해 05시 발표 예보 이용
    forecast_date = now

    if now.hour < 6:
        forecast_date = now - timedelta(days=1)

    base_date = forecast_date.strftime("%Y%m%d")
    base_time = "0500"

    params = {
        "serviceKey": weather_api_key,
        "pageNo": "1",
        "numOfRows": "1000",
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": "62",
        "ny": "126"
    }

    try:
        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:

            response = await client.get(
                KMA_API_URL,
                params=params
            )

            response.raise_for_status()

    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "기상청 API가 오류를 반환했습니다.",
                "external_status_code": error.response.status_code
            }
        )

    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "기상청 API 연결에 실패했습니다.",
                "error_type": type(error).__name__
            }
        )

    try:
        data = response.json()

    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="기상청 응답이 JSON 형식이 아닙니다."
        )

    header = data.get("response", {}).get("header", {})

    if header.get("resultCode") != "00":
        raise HTTPException(
            status_code=502,
            detail={
                "result_code": header.get("resultCode"),
                "message": header.get("resultMsg")
            }
        )

    body = data["response"]["body"]

    items = body.get("items", {}).get("item", [])

  
    # ======================================
    # 가장 가까운 미래 예보 추출
    # ======================================

    # 현재 한국 날짜와 시각
    current_time = now.strftime("%Y%m%d%H%M")

    # 날짜·시간별 예보 데이터를 그룹화
    forecast_groups = {}

    for item in items:

        forecast_datetime = (
            item["fcstDate"] + item["fcstTime"]
        )

        if forecast_datetime not in forecast_groups:
            forecast_groups[forecast_datetime] = {}

        category = item["category"]
        value = item["fcstValue"]

        forecast_groups[forecast_datetime][category] = value

    # 현재 이후 예보 중 가장 가까운 시간 선택
    future_times = sorted(
        time for time in forecast_groups
        if time >= current_time
    )

    if not future_times:
        raise HTTPException(
            status_code=404,
            detail="현재 이후의 날씨 예보가 없습니다."
        )

    selected_time = future_times[0]

    selected_weather = forecast_groups[selected_time]

    # ======================================
    # 날씨 코드 변환
    # ======================================

    sky_codes = {
        "1": "맑음",
        "3": "구름 많음",
        "4": "흐림"
    }

    rain_codes = {
        "0": "없음",
        "1": "비",
        "2": "비/눈",
        "3": "눈",
        "4": "소나기"
    }

    sky_value = selected_weather.get("SKY", "")
    rain_value = selected_weather.get("PTY", "")

    sky_description = sky_codes.get(
        sky_value,
        "정보 없음"
    )

    rain_description = rain_codes.get(
        rain_value,
        "정보 없음"
    )

    # ======================================
    # 최종 JSON 반환
    # ======================================

    return {
        "status": "success",
        "location": "올림픽공원 주변",
        "forecast_date": selected_time[:8],
        "forecast_time": selected_time[8:],
        "weather": {
            "temperature": selected_weather.get("TMP"),
            "sky": sky_description,
            "rain_probability": selected_weather.get("POP"),
            "precipitation_type": rain_description,
            "humidity": selected_weather.get("REH"),
            "wind_speed": selected_weather.get("WSD")
        }
    }
# ======================================
# 올림픽공원 입출차정보 API 테스트
# ======================================

@app.get("/api/parking/test")
async def test_parking_api():

    parking_api_key = os.getenv("OLPARK_LINKED_API_KEY")

    if not parking_api_key:
        raise HTTPException(
            status_code=500,
            detail="올림픽공원 입출차정보 API 인증키가 없습니다."
        )

    api_url = (
        "https://api.kcisa.kr"
        "/openapi/API_CPM_008/request"
    )

    params = {
        "serviceKey": parking_api_key,
        "numOfRows": "10",
        "pageNo": "1"
    }

    try:
        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:

            response = await client.get(
                api_url,
                params=params
            )

        return {
            "status": "received",
            "external_status_code": response.status_code,
            "content_type": response.headers.get(
                "content-type", ""
            ),
            "response_preview": response.text[:1500]
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="공공데이터 API 서버 응답 시간이 초과되었습니다."
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="공공데이터 API 서버에 연결하지 못했습니다."
        )
# ======================================
# AI 주차 혼잡도 예측 API
# ======================================

import joblib
from datetime import datetime
from pydantic import BaseModel, Field


# 학습한 AI 모델 위치
PARKING_MODEL_PATH = (
    Path(__file__).resolve().parent
    / "models"
    / "parking_model.pkl"
)


# 예측 요청 데이터 형식
class ScheduledEvent(BaseModel):
    title: str = ""
    place: str = ""
    start_time: str | None = None
    end_time: str | None = None


class ParkingPredictionRequest(BaseModel):
    hour: int
    weekday: int
    temperature: float
    rain_probability: int
    visit_date: str | None = None
    performance: int = 0  # 이전 화면과의 호환용. 새 모델에서는 사용하지 않습니다.
    events: list[ScheduledEvent] = Field(default_factory=list, max_length=30)


def event_venue_weight(place: str) -> float:
    """공식 공연장 수용규모에서 도출한 가상 영향. 실제 티켓 판매량은 아님."""
    capacity = event_venue_capacity(place)
    if capacity is None:
        return 0.45  # 공식 수용 인원 미확인 시설의 임시 약한 영향
    return round(capacity * 0.70 / 10000, 4)


def event_venue_capacity(place: str) -> int | None:
    """한국체육산업개발 공식 시설 안내 기준. 공연별 무대 배치에 따라 달라질 수 있음."""
    p = place.lower().replace(" ", "")
    if "kspodome" in p or "체조경기장" in p:
        return 15000
    if "핸드볼" in p or "티켓링크라이브아레나" in p:
        return 5003
    if "뮤즈라이브" in p:
        return 237
    if "올림픽홀" in p:
        return 3000  # 시설 안내: 고정석+가변 플로어, 약 3천 석
    if "우리금융아트홀" in p or "우리아트홀" in p or "역도경기장" in p:
        return 1184
    return None


def event_pressure_at_hour(events: list[ScheduledEvent], hour: int) -> float:
    pressure = 0.0
    for item in events:
        weight = event_venue_weight(item.place)
        try:
            if not item.start_time:
                pressure += weight * 0.3  # 회차 시간 정보가 없으면 약한 불확실 영향
                continue
            sh, sm = (int(x) for x in item.start_time.split(":")[:2])
            start = sh + sm / 60
            end = start + 2  # 종료 정보가 없으면 공연 2시간을 가정
            if item.end_time:
                eh, em = (int(x) for x in item.end_time.split(":")[:2])
                end = eh + em / 60
                if end < start:
                    end += 24
            distance = hour - start
            if -2 <= distance <= 0:
                proximity = 1.0 if distance >= -1 else 0.65
            elif start < hour <= end:
                proximity = 0.55
            elif end < hour <= end + 2:
                proximity = 0.2
            else:
                proximity = 0.0
            pressure += weight * proximity
        except (ValueError, TypeError):
            pressure += weight * 0.3
    return round(min(5.0, pressure), 2)


@app.post("/api/parking/predict")
def predict_parking(data: ParkingPredictionRequest):

    # 입력값 검증
    if not 0 <= data.hour <= 23:
        raise HTTPException(
            status_code=400,
            detail="hour는 0~23 사이여야 합니다."
        )

    if not 0 <= data.weekday <= 6:
        raise HTTPException(
            status_code=400,
            detail="weekday는 0~6 사이여야 합니다."
        )

    if not 0 <= data.rain_probability <= 100:
        raise HTTPException(
            status_code=400,
            detail="rain_probability는 0~100 사이여야 합니다."
        )

    if data.performance not in (0, 1):
        raise HTTPException(
            status_code=400,
            detail="performance는 0 또는 1이어야 합니다."
        )

    # AI 모델 파일 확인
    if not PARKING_MODEL_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail="AI 모델 파일이 없습니다."
        )

    # 학습된 모델 불러오기
    saved = joblib.load(PARKING_MODEL_PATH)
    if not isinstance(saved, dict) or saved.get("version") != 4:
        raise HTTPException(status_code=500, detail="신규 train_model.py로 모델을 다시 학습해 주세요.")
    model = saved.get("model")

    # 예측 입력값
    features = [[
        data.hour,
        data.weekday,
        data.temperature,
        data.rain_probability,
        min(len(data.events), 5),
        event_pressure_at_hour(data.events, data.hour)
    ]]

    # 회귀 모델은 시뮬레이션 점유율(0~100)을 출력합니다.
    # 과거 3단계 분류 모델을 실수로 사용하지 않도록 모델 유형을 확인합니다.
    if not hasattr(model, "estimators_") or not hasattr(model, "predict"):
        raise HTTPException(status_code=500, detail="모델을 다시 학습해 주세요.")
    from sklearn.ensemble import RandomForestRegressor
    if not isinstance(model, RandomForestRegressor) or model.n_features_in_ != 6:
        raise HTTPException(status_code=500, detail="새 train_model.py를 실행해 모델을 다시 학습해 주세요.")
    raw_occupancy = round(max(0.0, min(100.0, float(model.predict(features)[0]))), 1)
    historical = _historical_parking_estimate(data)
    history_adjusted = (round(raw_occupancy * (1-historical["weight"]) +
                              historical["estimate"] * historical["weight"], 1)
                        if historical else raw_occupancy)
    calibration = _recent_global_reference(data.hour, data.weekday, data.visit_date)
    occupancy = round(max(0.0, min(100.0,
        calibration["weight"] * calibration["ratio"] + (1-calibration["weight"]) * history_adjusted
    )), 1) if calibration else history_adjusted
    if occupancy >= 90:
        prediction, label = 3, "만차 수준"
    elif occupancy >= 70:
        prediction, label = 2, "혼잡"
    elif occupancy >= 50:
        prediction, label = 1, "다소혼잡"
    else:
        prediction, label = 0, "여유"

    return {
        "status": "success",
        "prediction": label,
        "prediction_code": prediction,
        "occupancy_rate": occupancy,
        "simulation_only_rate": raw_occupancy,
        "historical_adjusted_rate": history_adjusted,
        "historical_support": historical,
        "calibration": calibration,
        "model_type": "simulation",
        "model_version": 4,
        "event_count": len(data.events),
        "event_pressure": features[0][-1],
        "estimated_audience_proxy": int(sum(
            event_venue_capacity(e.place) * 0.70
            for e in data.events if event_venue_capacity(e.place) is not None
        )),
        "audience_note": "공연장 수용 인원 × 가정 객석 점유율 70%. 실제 관객 수나 주차 차량 수가 아닙니다.",
        "message": "가상 모델에 누적 공식 API 조회 이력을 날짜·시간·요일·공연·날씨 유사도에 따라 점진 반영한 추정입니다. 원본 측정 시각과 모델 정확도는 검증되지 않았습니다."
    }


# ======================================
# 주차 구역별 시뮬레이션 (실제 잔여 대수는 제공하지 않음)
# ======================================
# 공식 주차 안내의 시설 기준 규모입니다. P2는 올림픽홀 지하와 합산한 표기입니다.
AREA_DATA = [
    {"id": "P1", "name": "P1 · K-아트홀 인근", "capacity": 562, "near": "K-아트홀", "group": "k_art"},
    {"id": "P2", "name": "P2 · 올림픽홀·지하 주차장", "capacity": 320, "near": "올림픽홀", "group": "olympic_hall"},
    {"id": "P4", "name": "P4 · 올림픽수영장 인근", "capacity": 117, "near": "올림픽수영장", "group": "pool"},
    {"id": "P5", "name": "P5 · KSPO DOME 인근", "capacity": 176, "near": "KSPO DOME", "group": "dome"},
    {"id": "P6", "name": "P6 · 티켓링크 라이브 아레나 인근", "capacity": 167, "near": "티켓링크 라이브 아레나", "group": "arena"},
    {"id": "P7", "name": "P7 · 우리금융아트홀 인근", "capacity": 137, "near": "우리금융아트홀", "group": "art_hall"},
    {"id": "P11", "name": "P11 · 올림픽테니스경기장 인근", "capacity": 190, "near": "올림픽테니스경기장", "group": "tennis"},
]

# 공연장→주차 구역 영향도. 실제 통행량이나 주차 선택 행태로 검증하지 않은 가정입니다.
VENUE_TO_AREA = {
    "dome": {"P5": 1.0, "P4": .60, "P2": .42, "P6": .25, "P7": .18, "P1": .16, "P11": .15},
    "arena": {"P6": 1.0, "P7": .55, "P2": .45, "P1": .35, "P5": .28, "P4": .22, "P11": .25},
    "olympic_hall": {"P2": 1.0, "P6": .42, "P5": .32, "P1": .28, "P4": .30, "P7": .22, "P11": .20},
    "art_hall": {"P7": 1.0, "P6": .52, "P1": .35, "P2": .27, "P5": .18, "P4": .15, "P11": .22},
    "muse": {"P7": .85, "P6": .60, "P1": .30, "P2": .25, "P5": .16, "P4": .14, "P11": .20},
    "k_art": {"P1": 1.0, "P2": .37, "P6": .32, "P7": .27, "P5": .20, "P4": .15, "P11": .25},
    "tennis": {"P11": 1.0, "P6": .28, "P1": .28, "P2": .25, "P7": .22, "P5": .15, "P4": .12},
}


def event_venue_group(place: str) -> str | None:
    p = place.lower().replace(" ", "")
    if "뮤즈라이브" in p:
        return "muse"
    if "kspodome" in p or "체조경기장" in p:
        return "dome"
    if "핸드볼" in p or "티켓링크라이브아레나" in p:
        return "arena"
    if "올림픽홀" in p:
        return "olympic_hall"
    if "우리금융아트홀" in p or "우리아트홀" in p or "역도경기장" in p:
        return "art_hall"
    if "k-아트홀" in p or "k아트홀" in p:
        return "k_art"
    if "테니스" in p:
        return "tennis"
    return None


def event_time_factor(event: ScheduledEvent, hour: int) -> float:
    if not event.start_time:
        return 0.25  # 회차 시간 미확인
    try:
        sh, sm = map(int, event.start_time.split(":")[:2])
        start = sh + sm / 60
        end = start + 2
        if event.end_time:
            eh, em = map(int, event.end_time.split(":")[:2])
            end = eh + em / 60
            if end < start:
                end += 24
        if start - 2 <= hour <= start:
            return 1.0 if hour >= start - 1 else .6
        if start < hour <= end:
            return .52
        if end < hour <= end + 2:
            return .22
        return 0.0
    except (ValueError, TypeError):
        return .25


class AreaPredictionRequest(ParkingPredictionRequest):
    destination: str = "dome"


def _area_activity_offset(group: str, hour: int, weekday: int) -> float:
    """공연이 없어도 시설 용도별 이용 패턴이 다르다는 시연용 가정.

    실제 구역별 주차대수를 관측한 계수가 아니므로 작은 차이만 부여합니다.
    """
    weekend = weekday >= 5
    return {
        "k_art": 1.5 if 14 <= hour <= 20 else -0.5,
        "olympic_hall": 2.0 if 15 <= hour <= 21 else 0.0,
        "pool": 7.0 if 7 <= hour <= 13 else 3.0 if 14 <= hour <= 20 else 0.0,
        "dome": -2.5 if 9 <= hour <= 20 else -1.0,
        "arena": -1.5 if 9 <= hour <= 20 else -0.5,
        "art_hall": 2.0 if 16 <= hour <= 21 else 0.0,
        "tennis": 6.0 if weekend and 8 <= hour <= 17 else 3.0 if 8 <= hour <= 17 else 0.0,
    }.get(group, 0.0)


def _recent_global_reference(hour: int, weekday: int, visit_date: str | None):
    """오늘의 최근 전체 합산 API 조회값으로 가까운 미래 지수를 보정합니다.

    주차 구역별 점유율을 측정한 것이 아니며 보정 가중치는 미검증 가정입니다.
    """
    try:
        if not PARKING_HISTORY_DB.exists():
            return None
        with sqlite3.connect(f"file:{PARKING_HISTORY_DB.as_posix()}?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT observed_at, occupied FROM observations ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        timestamp, occupied = row
        observed = datetime.fromisoformat(timestamp).astimezone(ZoneInfo("Asia/Seoul"))
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        age_seconds = (now - observed).total_seconds()
        if not (0 <= age_seconds <= 900 and observed.date() == now.date()):
            return None
        if visit_date != now.date().isoformat() or weekday != now.weekday():
            return None
        horizon_hours = hour - now.hour
        if not 0 <= horizon_hours <= 6:
            return None
        # 단기(최대 6시간) 변화는 알 수 없으므로 현재 전체 혼잡 상태의 영향을
        # 점진적으로 낮추는 완만한 감쇠를 사용합니다. 검증된 예측 계수는 아닙니다.
        weight = round(math.exp(-horizon_hours / 12.0), 3)
        return {"occupied": int(occupied), "observed_at": timestamp,
                "ratio": round(int(occupied) / OFFICIAL_PARKING_REFERENCE_CAPACITY * 100, 1),
                "horizon_hours": horizon_hours, "weight": weight,
                "note": "전체 합산 API 조회값의 참고 기준 대비 비율입니다. 구역별 실측 점유율이 아닙니다."}
    except (sqlite3.Error, ValueError, TypeError, OSError):
        return None


@app.post("/api/parking/areas/predict")
def predict_parking_areas(data: AreaPredictionRequest):
    if data.destination not in VENUE_TO_AREA and data.destination != "pool":
        raise HTTPException(status_code=400, detail="목적지 코드가 올바르지 않습니다.")
    if data.visit_date is not None:
        try:
            selected = datetime.strptime(data.visit_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="방문 날짜 형식은 YYYY-MM-DD입니다.") from exc
        if selected.weekday() != data.weekday:
            raise HTTPException(status_code=422, detail="방문 날짜와 요일 정보가 일치하지 않습니다.")
    # 전체 공원 수준의 시뮬레이션 값은 공통 출발점으로만 활용합니다.
    baseline = predict_parking(ParkingPredictionRequest(
        hour=data.hour, weekday=data.weekday, temperature=data.temperature,
        rain_probability=data.rain_probability, visit_date=data.visit_date,
        events=data.events
    ))["historical_adjusted_rate"]
    global_reference = _recent_global_reference(data.hour, data.weekday, data.visit_date)
    # 당일 가까운 미래만 보정합니다. 오래되거나 다른 날짜의 수치는 미반영합니다.
    # 전체 차량 수를 구역별 차량 수로 나누거나 구역별 잔여 대수를 추정하지 않습니다.
    reference_baseline = (global_reference["weight"] * global_reference["ratio"] +
                          (1-global_reference["weight"]) * baseline
                          if global_reference else baseline)
    results = []
    unmatched = []
    for e in data.events:
        if not event_venue_group(e.place):
            unmatched.append(e.title)
    for area in AREA_DATA:
        influence = 0.0
        influencing = []
        for e in data.events:
            group = event_venue_group(e.place)
            if not group:
                continue
            cap = event_venue_capacity(e.place)
            if cap is None:
                continue
            proximity = VENUE_TO_AREA[group].get(area["id"], .1)
            temporal = event_time_factor(e, data.hour)
            estimated_audience = cap * .70  # 실제 관객 수가 아닌 가정
            relative_size = min(2.0, estimated_audience / 7000)
            capacity_factor = max(.7, min(1.6, (180 / area["capacity"]) ** .35))
            contribution = 28 * relative_size * proximity * temporal * capacity_factor
            influence += contribution
            if contribution >= 1.0:
                influencing.append(e.title)
        # 기존 동일 점수의 원인: 공연 영향이 0일 때 공통 baseline만 사용했기 때문.
        # 시설 이용 성격과 공식 공개 주차 규모에 따른 작은 차이를 시연 가정으로 둡니다.
        activity_offset = _area_activity_offset(area["group"], data.hour, data.weekday)
        capacity_offset = max(-5.0, min(5.0, 5.0 * math.log(200 / area["capacity"])))
        score = round(max(0, min(99.9, reference_baseline + activity_offset + capacity_offset + influence)), 1)
        level = "만차 수준" if score >= 90 else "혼잡" if score >= 70 else "다소혼잡" if score >= 50 else "여유"
        distance_factor = VENUE_TO_AREA.get(data.destination, {}).get(area["id"], .15)
        # 가까운 목적지 주차장을 우선하되 혼잡 예상이 큰 경우 대안을 고려
        rank = score + (1 - distance_factor) * 34
        results.append({
            "id": area["id"], "name": area["name"], "capacity": area["capacity"],
            "near": area["near"], "score": score, "level": level,
            "nearby_priority": round(distance_factor, 2), "rank": rank,
            "influencing_events": influencing,
            "breakdown": {"activity_assumption": round(activity_offset, 1),
                          "capacity_assumption": round(capacity_offset, 1),
                          "event_effect_assumption": round(influence, 1)},
        })
    ordered = sorted(results, key=lambda r: r["rank"])
    for r in results:
        r.pop("rank")
    return {
        "status": "success", "model_type": "simulation", "area_results": results,
        "recommended": [item["id"] for item in ordered[:2]],
        "unmatched_events": unmatched, "baseline_simulation": baseline,
        "global_reference": global_reference,
        "source": "https://www.ksponco.or.kr/olympicpark/parkingInfo?mid=a20111000000",
        "message": "전체 주차 차량 수 공개 API는 구역별 수치를 제공하지 않습니다. 구역별 점수는 시설 용도·공식 공개 주차 규모·공연장 인접도를 가정한 비교 지수입니다. 실제 구역별 점유율이나 잔여 대수가 아닙니다."
    }


# ======================================
# 공식 공개 페이지 조회 (인증키 불필요)
# ======================================
from html.parser import HTMLParser as _HTMLParser
from datetime import timezone as _timezone
from fastapi import Query

OFFICIAL_PARKING_URL = "https://www.ksponco.or.kr/online/main/parking.do"
OFFICIAL_PARKING_API_URL = "https://www.ksponco.or.kr/online/main/parkingorsApi.do"
OFFICIAL_PARKING_API_KEY = "PARKING21803504"  # 공식 공개 조회용 키
OFFICIAL_PARKING_REFERENCE_CAPACITY = 2200  # 안내 페이지의 기준 대수. API 응답에는 없음.
PARKING_HISTORY_DB = BASE_DIR / "data" / "parking_observations.sqlite3"
PARKING_COLLECT_INTERVAL = 60  # 서버 실행 중 60초 간격으로 공식 API 관측
PARKING_API_ATTEMPTS = 2
PARKING_API_RETRY_DELAY_SECONDS = 1.0
_parking_collection_lock = asyncio.Lock()
_parking_context_cache = {"events": None, "weather": None}
_historical_hour_cache = {"loaded_at": 0.0, "db_path": None, "rows": []}


def _korean_holiday_flag(day):
    """설·추석·대체공휴일은 선택적 holidays 패키지가 있을 때만 확정합니다.

    패키지가 없으면 모르는 날을 일반 평일로 단정하지 않습니다.
    """
    try:
        import holidays
        return day in holidays.KR(years=day.year)
    except ImportError:
        fixed = {(1, 1), (3, 1), (5, 5), (6, 6),
                 (8, 15), (10, 3), (10, 9), (12, 25)}
        return True if (day.month, day.day) in fixed else None


def _historical_hourly_rows():
    """원본 분당 조회값을 '날짜×시간' 단위로 집계해 표본 중복을 막습니다.

    1일 1시간이 단 하나의 표본입니다. 원본은 보존하고 최근 400일만 조회합니다.
    """
    now = time.monotonic()
    cache = _historical_hour_cache
    db_path = str(PARKING_HISTORY_DB)
    if cache["db_path"] == db_path and now - cache["loaded_at"] < 300:
        return cache["rows"]
    if not PARKING_HISTORY_DB.exists():
        return []
    try:
        cutoff = (datetime.now(_timezone.utc) - timedelta(days=400)).isoformat()
        with sqlite3.connect(f"file:{PARKING_HISTORY_DB.as_posix()}?mode=ro", uri=True) as conn:
            rows = conn.execute("""
                SELECT strftime('%Y-%m-%d', observed_at, '+9 hours') local_date,
                       CAST(strftime('%H', observed_at, '+9 hours') AS INTEGER) local_hour,
                       AVG(occupied) mean_occupied, COUNT(*) samples,
                       (julianday(MAX(observed_at))-julianday(MIN(observed_at)))*1440 span_minutes,
                       AVG(event_count) event_count, AVG(event_pressure) event_pressure,
                       AVG(forecast_temperature) forecast_temperature,
                       AVG(forecast_rain_probability) forecast_rain
                  FROM observations WHERE observed_at >= ?
              GROUP BY local_date, local_hour
                HAVING samples >= 3 AND span_minutes >= 10
              ORDER BY local_date, local_hour
            """, (cutoff,)).fetchall()
        cache.update({"loaded_at": now, "db_path": db_path, "rows": rows})
        return rows
    except (sqlite3.Error, ValueError, OSError):
        return []


def _historical_parking_estimate(data: ParkingPredictionRequest):
    """누적 공개 API 조회값으로 학습하는 가벼운 유사 사례 기반 예측.

    훈련/평가 누수를 피하기 위해 예측 대상 날짜 이전 관측만 사용합니다.
    이 추정은 센서 측정값·기상 실측값을 뜻하지 않습니다.
    """
    if not data.visit_date:
        return None
    try:
        target = datetime.strptime(data.visit_date, "%Y-%m-%d").date()
        if target.weekday() != data.weekday:
            return None
    except ValueError:
        return None
    rows = _historical_hourly_rows()
    if not rows:
        return None
    target_holiday = _korean_holiday_flag(target)
    target_weekend = target.weekday() >= 5
    target_pressure = event_pressure_at_hour(data.events, data.hour)
    per_day = {}
    for (date_text, hour, avg_count, samples, span_minutes, events,
         pressure, temp, rain) in rows:
        if not date_text or avg_count is None:
            continue
        day = datetime.strptime(date_text, "%Y-%m-%d").date()
        if day >= target:
            continue  # 같은 날의 실측은 가까운 미래 공식 보정에서만 사용
        age_days = (target-day).days
        if age_days > 400:
            continue
        hour_diff = abs(hour-data.hour)
        if hour_diff > 2:
            continue
        day_holiday = _korean_holiday_flag(day)
        if target_holiday is not None and day_holiday is not None and target_holiday != day_holiday:
            continue
        same_weekday = day.weekday() == target.weekday()
        same_day_type = (day.weekday() >= 5) == target_weekend
        weekday_factor = 1.8 if same_weekday else 1.0 if same_day_type else 0.28
        hour_factor = (1.0, .42, .13)[hour_diff]
        recency_factor = math.exp(-age_days / 220)
        weather_factor = math.exp(-abs(temp-data.temperature)/18) if temp is not None else 1.0
        rain_factor = math.exp(-abs(rain-data.rain_probability)/65) if rain is not None else 1.0
        event_factor = 1/(1+abs(events-len(data.events))*.30) if events is not None else 1.0
        pressure_factor = 1/(1+abs(pressure-target_pressure)*.28) if pressure is not None else 1.0
        coverage_factor = min(1.0, max(.25, span_minutes/40))
        weight = (weekday_factor*hour_factor*recency_factor*weather_factor*
                  rain_factor*event_factor*pressure_factor*coverage_factor)
        if weight <= 0:
            continue
        # 공원 전체의 참고 기준 대비 비율이지 구역별 실제 점유율은 아닙니다.
        value = max(0.0, min(100.0, avg_count/OFFICIAL_PARKING_REFERENCE_CAPACITY*100))
        record = per_day.setdefault(date_text, {"weighted": 0.0, "sum": 0.0,
                                                 "max_weight": 0.0, "same_weekday": same_weekday})
        record["weighted"] += value*weight
        record["sum"] += weight
        record["max_weight"] = max(record["max_weight"], weight)
    if not per_day:
        return None
    # 한 날짜의 인접한 여러 시간대가 여러 날치 학습량으로 과대계산되지 않게 합니다.
    total_weight = sum(day["max_weight"] for day in per_day.values())
    estimate = sum((day["weighted"]/day["sum"])*day["max_weight"]
                   for day in per_day.values())/total_weight
    days = len(per_day)
    # 수십~수백 일 누적 전에는 가상 모델에 일부만 반영하고 상한도 제한합니다.
    blend = round(min(.80, .18 + .16*math.log1p(days)), 3)
    return {"estimate": round(estimate, 1), "weight": blend,
            "sample_days": days,
            "same_weekday_days": sum(bool(v["same_weekday"]) for v in per_day.values()),
            "source": "공식 API 조회 기록의 날짜×시간 집계(미검증 측정 시각)",
            "note": "같은 요일·시간대, 주말 여부, 최근성, 공연 건수/시간 영향, 기상 예보 유사도를 적용한 추정입니다. 정확도 검증 전이며 공휴일은 선택적 달력 설치 여부에 따라 미확인일 수 있습니다."}


def _parking_db():
    PARKING_HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(PARKING_HISTORY_DB, timeout=10)
    conn.execute("CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY AUTOINCREMENT, observed_at TEXT NOT NULL, occupied INTEGER NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_observed_at ON observations(observed_at)")
    # 기존 v8/v9 DB를 삭제하지 않고 필요한 컬럼만 추가합니다.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(observations)")}
    for name, sql_type in (
        ("event_count", "INTEGER"), ("event_pressure", "REAL"),
        ("event_titles_json", "TEXT"), ("event_source_checked_at", "TEXT"),
        ("forecast_temperature", "REAL"), ("forecast_rain_probability", "REAL"),
        ("forecast_target_at", "TEXT"), ("weather_source_checked_at", "TEXT"),
    ):
        if name not in existing:
            conn.execute(f"ALTER TABLE observations ADD COLUMN {name} {sql_type}")
    conn.execute("""CREATE TABLE IF NOT EXISTS hybrid_forecasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forecast_bucket TEXT NOT NULL,
        created_at TEXT NOT NULL,
        source_observed_at TEXT NOT NULL,
        due_at TEXT NOT NULL,
        horizon_minutes INTEGER NOT NULL,
        baseline_occupied INTEGER NOT NULL,
        projected_occupied INTEGER NOT NULL,
        predicted_ratio REAL NOT NULL,
        scenario_context_used INTEGER NOT NULL,
        matched_observed_at TEXT,
        observed_occupied INTEGER,
        observed_ratio REAL,
        absolute_error_pp REAL,
        UNIQUE(forecast_bucket, horizon_minutes)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hybrid_due ON hybrid_forecasts(due_at)")
    return conn


def _reconcile_hybrid_forecasts(connection, newest_observed_at: str):
    """예측 목표 시각 뒤 5분 이내의 첫 공식 API 관측값과만 비교합니다."""
    pending = connection.execute("""SELECT id, due_at FROM hybrid_forecasts
        WHERE matched_observed_at IS NULL AND due_at <= ?
        ORDER BY due_at LIMIT 500""", (newest_observed_at,)).fetchall()
    for forecast_id, due_at in pending:
        window_end = (datetime.fromisoformat(due_at) + timedelta(minutes=5)).isoformat()
        actual = connection.execute("""SELECT observed_at, occupied FROM observations
            WHERE observed_at >= ? AND observed_at <= ? ORDER BY observed_at LIMIT 1""",
            (due_at, window_end)).fetchone()
        if not actual:
            continue  # 해당 시각에 관측이 없으면 '미검증' 상태로 남깁니다.
        observed_at, occupied = actual
        ratio = round(occupied / OFFICIAL_PARKING_REFERENCE_CAPACITY * 100, 3)
        prediction = connection.execute("SELECT predicted_ratio FROM hybrid_forecasts WHERE id=?", (forecast_id,)).fetchone()[0]
        connection.execute("""UPDATE hybrid_forecasts SET matched_observed_at=?, observed_occupied=?,
            observed_ratio=?, absolute_error_pp=? WHERE id=?""",
            (observed_at, occupied, ratio, round(abs(prediction-ratio), 3), forecast_id))


def _record_parking_observation(occupied: int, observed_at: str):
    with _parking_db() as conn:
        # 동시에 열린 브라우저 여러 개가 1분 내 조회해도 표본은 분당 최대 1건.
        last = conn.execute("SELECT observed_at FROM observations ORDER BY id DESC LIMIT 1").fetchone()
        if last and (datetime.fromisoformat(observed_at) - datetime.fromisoformat(last[0])).total_seconds() < 60:
            return
        clock = datetime.fromisoformat(observed_at).astimezone(ZoneInfo("Asia/Seoul"))
        events_cache = _parking_context_cache.get("events") or {}
        weather_cache = _parking_context_cache.get("weather") or {}
        events = events_cache.get("events") if events_cache.get("date") == clock.date().isoformat() else None
        weather = weather_cache.get("weather") or {}
        # 가장 가까운 기상청 예보가 현재 시각과 2시간 이상 떨어져 있으면 기록에 사용하지 않습니다.
        target = weather_cache.get("target")
        valid_forecast = bool(target and abs((target - clock).total_seconds()) <= 7200)
        conn.execute("""INSERT INTO observations(
            observed_at, occupied, event_count, event_pressure, event_titles_json, event_source_checked_at,
            forecast_temperature, forecast_rain_probability, forecast_target_at, weather_source_checked_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)""", (
            observed_at, occupied,
            len(events) if events is not None else None,
            event_pressure_at_hour([ScheduledEvent(**event) for event in events], clock.hour) if events is not None else None,
            json.dumps([{"title": e.get("title"), "place": e.get("place"), "start_time": e.get("start_time")} for e in events], ensure_ascii=False) if events is not None else None,
            events_cache.get("checked_at") if events is not None else None,
            _safe_float(weather.get("temperature")) if valid_forecast else None,
            _safe_float(weather.get("rain_probability")) if valid_forecast else None,
            target.isoformat() if valid_forecast else None,
            weather_cache.get("checked_at") if valid_forecast else None,
        ))
        _reconcile_hybrid_forecasts(conn, observed_at)


def _safe_float(value):
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _parking_history_summary(hours: int = 24):
    with _parking_db() as conn:
        records = conn.execute("SELECT observed_at, occupied FROM observations WHERE observed_at >= ? ORDER BY id ASC", (
            (datetime.now(_timezone.utc) - timedelta(hours=hours)).isoformat(),
        )).fetchall()
    last_changed_at = None
    previous = None
    for observed_at, occupied in records:
        if previous is not None and occupied != previous:
            last_changed_at = observed_at
        previous = occupied
    return {
        "sample_count": len(records),
        "last_change_observed_at": last_changed_at,
        "first_observed_at": records[0][0] if records else None,
        "last_observed_at": records[-1][0] if records else None,
        "note": "수집 기록에서 차량 수가 달라진 것을 처음 관찰한 시각입니다. 공식 데이터 생성 시각과 다릅니다.",
    }


def _parking_rows(hours: int):
    with _parking_db() as conn:
        return conn.execute(
            "SELECT observed_at, occupied FROM observations WHERE observed_at >= ? ORDER BY id ASC",
            ((datetime.now(_timezone.utc) - timedelta(hours=hours)).isoformat(),),
        ).fetchall()


def _parking_rows_enriched(hours: int):
    with _parking_db() as conn:
        return conn.execute("""SELECT observed_at, occupied, event_count, event_pressure,
             event_titles_json, event_source_checked_at, forecast_temperature,
             forecast_rain_probability, forecast_target_at, weather_source_checked_at
             FROM observations WHERE observed_at >= ? ORDER BY id ASC""", (
            (datetime.now(_timezone.utc) - timedelta(hours=hours)).isoformat(),
        )).fetchall()


def _parking_quality_report(rows):
    """관측 빈도 및 기본 데이터 품질 검사. 실제 주차 정확도 검증은 아님."""
    from collections import defaultdict

    dates = set()
    weekend_dates = set()
    hourly = defaultdict(list)
    changed = 0
    previous_count = None
    last_changed_at = None
    gaps_over_5m = 0
    previous_time = None
    for timestamp, occupied in rows:
        instant = datetime.fromisoformat(timestamp)
        seoul = instant.astimezone(ZoneInfo("Asia/Seoul"))
        dates.add(seoul.date().isoformat())
        if seoul.weekday() >= 5:
            weekend_dates.add(seoul.date().isoformat())
        hourly[seoul.hour].append(occupied)
        if previous_count is not None and occupied != previous_count:
            changed += 1
            last_changed_at = timestamp
        if previous_time is not None and (instant - previous_time).total_seconds() > 300:
            gaps_over_5m += 1
        previous_count, previous_time = occupied, instant

    # 이는 학습 준비를 판단하는 임시 기준일 뿐 모델의 예측력 보장이 아닙니다.
    ready = len(rows) >= 2000 and len(dates) >= 28 and len(weekend_dates) >= 4 and changed >= 30
    return {
        "samples": len(rows), "days": len(dates), "weekend_days": len(weekend_dates),
        "changes_observed": changed, "last_change_observed_at": last_changed_at,
        "gaps_over_5_minutes": gaps_over_5m,
        "min_occupied": min((r[1] for r in rows), default=None),
        "max_occupied": max((r[1] for r in rows), default=None),
        "hourly_average": [{"hour": hour, "average_occupied": round(sum(values) / len(values), 1), "samples": len(values)} for hour, values in sorted(hourly.items())],
        "basic_training_ready": ready,
        "readiness_note": "시간·요일만 활용하는 기초 실측 기반 모델의 임시 준비 기준입니다. 날씨·공연 이력과 정확한 원본 측정 시각은 미포함이며, API 값이 오래된 값인지 별도 검증해야 합니다.",
    }
OFFICIAL_EVENTS_URL = "https://www.ksponco.or.kr/olympicpark/eventInfo/eventInfoListText?mid=a20301010200"
_page_cache = {}


class _PlainPage(_HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("td", "th", "tr", "p", "h4"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th", "tr", "p", "h4"):
            self.parts.append(" ")

    def handle_data(self, data):
        if self.skip == 0:
            self.parts.append(data)


class _TableRows(_HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row_links = []
        self.row = None
        self.cell = None
        self.link = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
            self.link = None
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "a" and self.cell is not None and self.row is not None and not self.row:
            self.link = dict(attrs).get("href")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", " ".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
                self.row_links.append(self.link)
            self.row = None


def _detail_schedule(page: str, selected):
    """공식 상세 공지에서 해당 날짜 회차의 시작 시각과 소요시간을 추출한다.

    날짜별 회차가 확인되지 않으면 시작/종료 시각을 만들지 않는다.
    """
    parser = _PlainPage()
    parser.feed(page)
    plain = re.sub(r"\s+", " ", " ".join(parser.parts))
    section = re.search(r"기간\s*\d{4}-\d{2}-\d{2}\s*[~〜-]+\s*\d{4}-\d{2}-\d{2}\s*시간\s*(.*?)\s*티켓가격", plain)
    if not section:
        return None, None, "공식 상세 페이지에서 회차 시간 확인 필요"
    schedule = section.group(1)
    chosen = None
    weekday = ["월", "화", "수", "목", "금", "토", "일"][selected.weekday()]
    for part in re.split(r"\s*/\s*|\s*,\s*", schedule):
        # '2026년 11월 7일(토) 18:00', '11월 7일(토) 16시'
        month_day = re.search(r"(\d{1,2})월\s*(\d{1,2})일", part)
        if month_day:
            if (int(month_day.group(1)), int(month_day.group(2))) == (selected.month, selected.day):
                chosen = part[month_day.end():]
                break
        # '금 오후 7시 / 토 오후 6시 / 일 오후 5시'
        elif re.search(rf"(?:^|\s){weekday}(?:요일)?\s", part):
            chosen = part
            break
    # 단일 회차의 시간만 표시된 경우. 여러 날짜에 걸친 일정이면 시간 매칭 불가.
    if chosen is None:
        return None, None, schedule or "공식 상세 페이지에서 회차 시간 확인 필요"
    value = re.search(r"(오전|오후)?\s*(?<!\d)(\d{1,2})(?!\d)(?::(\d{2}))?\s*(?:시)?", chosen)
    if not value:
        return None, None, schedule
    hour, minute = int(value.group(2)), int(value.group(3) or 0)
    if value.group(1) == "오후" and hour < 12:
        hour += 12
    if value.group(1) == "오전" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None, None, schedule
    start_time = f"{hour:02d}:{minute:02d}"
    duration = re.search(r"소요시간\s*(\d+)\s*분", plain)
    if not duration:
        return start_time, None, schedule
    minutes = int(duration.group(1))
    if minutes <= 0 or minutes > 720:
        return start_time, None, schedule
    end_dt = datetime.combine(selected, datetime.min.time()) + timedelta(hours=hour, minutes=minute + minutes)
    return start_time, end_dt.strftime("%H:%M"), schedule


async def _fetch_official(url: str, ttl: int = 300):
    now = datetime.now(_timezone.utc).timestamp()
    cached = _page_cache.get(url)
    if cached and now - cached[0] < ttl:
        return cached[1], cached[2]
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "OLPARK88FLOW/1.0 (public-info viewer)"})
            response.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="공식 사이트 데이터를 조회하지 못했습니다. 공식 페이지에서 확인해 주세요.")
    # 제공 사이트에서 인코딩 헤더를 잘못 주는 경우를 대비
    response.encoding = response.encoding or "utf-8"
    _page_cache[url] = (now, response.text, now)
    return response.text, now


@app.get("/api/parking/live")
async def public_parking_snapshot():
    # 공식 JSON API에서 제공되는 것은 합산 주차 차량 수(parking_sum)뿐입니다.
    # 요청에 성공한 시각은 데이터 측정/갱신 시각과 다를 수 있습니다.
    # 수집기와 브라우저의 요청이 겹치더라도 외부 API에 동시 요청을 쏟아붓지 않습니다.
    async with _parking_collection_lock:
        occupied = None
        fetched_at = None
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            for attempt in range(PARKING_API_ATTEMPTS):
                try:
                    response = await client.get(
                        OFFICIAL_PARKING_API_URL,
                        params={"apiKey": OFFICIAL_PARKING_API_KEY},
                        headers={"User-Agent": "OLPARK88/1.0 (public parking information)"},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    record = payload[0] if isinstance(payload, list) and payload else payload
                    if not isinstance(record, dict):
                        raise ValueError("invalid parking record")
                    raw_count = record.get("parking_sum")
                    if isinstance(raw_count, bool) or raw_count is None or str(raw_count).strip() == "":
                        raise ValueError("empty parking_sum")
                    candidate = int(str(raw_count).replace(",", ""))
                    if not 0 <= candidate <= 100000:
                        raise ValueError("invalid parking count")
                    occupied = candidate
                    fetched_at = datetime.now(_timezone.utc)
                    break
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    print(f"[parking live] API 요청 {attempt + 1}/{PARKING_API_ATTEMPTS} 실패: {type(exc).__name__}")
                    if attempt + 1 < PARKING_API_ATTEMPTS:
                        await asyncio.sleep(PARKING_API_RETRY_DELAY_SECONDS)
        if occupied is not None:
            _record_parking_observation(occupied, fetched_at.isoformat())

    is_stale = occupied is None
    last_observed_at = None
    if is_stale:
        with _parking_db() as conn:
            last = conn.execute("SELECT observed_at, occupied FROM observations ORDER BY id DESC LIMIT 1").fetchone()
        if not last:
            raise HTTPException(status_code=503, detail="공식 주차 API가 응답하지 않았으며 저장된 조회 기록도 없습니다.")
        last_observed_at, occupied = last
        fetched_at = datetime.now(_timezone.utc)

    capacity = OFFICIAL_PARKING_REFERENCE_CAPACITY
    over_capacity = occupied > capacity
    age_seconds = max(0, int((fetched_at - datetime.fromisoformat(last_observed_at)).total_seconds())) if is_stale else 0
    return {
        "status": "stale" if is_stale else "success", "occupied": occupied, "capacity": capacity,
        "is_stale": is_stale, "last_successful_fetch_at": last_observed_at if is_stale else fetched_at.isoformat(),
        "observation_age_seconds": age_seconds,
        "available_estimate": None if over_capacity else capacity - occupied,
        "occupancy_percent": round(occupied / capacity * 100, 1),
        "over_capacity": over_capacity,
        "scope": "동2문·남2문·북2문", "source": OFFICIAL_PARKING_URL,
        "api_source": OFFICIAL_PARKING_API_URL,
        "capacity_source": "공식 안내 페이지 기준 대수 (API에서 제공되지 않음)",
        "fetched_at": fetched_at.isoformat(),
        "history": _parking_history_summary(),
        "note": ("공식 API 조회 실패로 마지막 저장된 과거 조회값을 표시합니다. 현재 주차현황이 아닙니다. " if is_stale else "")
                + "API 조회 성공 시각은 실제 측정 시각이 아닙니다. 기준 2,200대는 참고값이며 실제 입차 가능 대수를 보장하지 않습니다."
    }


@app.get("/api/parking/history")
def parking_history(hours: int = Query(24, ge=1, le=168)):
    rows = _parking_rows(hours)
    return {
        "status": "success", "hours": hours,
        "samples": [{"observed_at": timestamp, "occupied": count} for timestamp, count in rows],
        "summary": _parking_history_summary(hours),
        "note": "서버가 켜진 동안 수집한 공식 API 응답 기록입니다. 실제 측정·갱신 시각은 확인할 수 없습니다.",
    }


@app.get("/api/parking/analysis")
def parking_observation_analysis(hours: int = Query(168, ge=1, le=720)):
    rows = _parking_rows(hours)
    enriched = _parking_rows_enriched(hours)
    return {
        "status": "success", "hours": hours, "quality": _parking_quality_report(rows),
        "context_coverage": {
            "event_context_rows": sum(1 for row in enriched if row[2] is not None),
            "weather_forecast_rows": sum(1 for row in enriched if row[6] is not None and row[7] is not None),
            "total_rows": len(enriched),
            "note": "공연은 현재 공식 목록 조회 결과이고 날씨는 기상청 예보입니다. 실제 관객 수나 실측 기온이 아닙니다.",
        },
    }


@app.get("/api/parking/context-status")
def parking_context_status():
    events = _parking_context_cache.get("events") or {}
    weather = _parking_context_cache.get("weather") or {}
    return {
        "status": "success", "events_checked_at": events.get("checked_at"),
        "event_date": events.get("date"),
        "event_count": len(events["events"]) if isinstance(events.get("events"), list) else None,
        "weather_checked_at": weather.get("checked_at"),
        "weather_forecast_target": weather["target"].isoformat() if weather.get("target") else None,
        "note": "미조회 또는 실패 시 null입니다. 예보/공연 정보는 실측이 아닌 참고 맥락입니다.",
    }


@app.get("/api/parking/hybrid-preview")
def parking_hybrid_preview():
    """최근 공식 관측값을 기준으로 한 단기 실험 전망 (검증된 AI 예측이 아님)."""
    now = datetime.now(_timezone.utc)
    with _parking_db() as conn:
        rows = conn.execute(
            "SELECT observed_at, occupied FROM observations WHERE observed_at >= ? ORDER BY observed_at",
            ((now - timedelta(minutes=65)).isoformat(),),
        ).fetchall()

    status = {
        "status": "insufficient_history", "model_type": "hybrid_experimental_unvalidated",
        "observation_count": len(rows), "horizons": [],
        "note": "실제 관측 기록을 기준으로 한 가상 추정이며 정확도는 검증되지 않았습니다. 공식 API의 데이터 생성·갱신 시각은 제공되지 않습니다.",
    }
    if not rows:
        status["reason"] = "공식 주차 API 관측 기록이 아직 없습니다."
        return status

    latest_at = datetime.fromisoformat(rows[-1][0])
    latest_count = rows[-1][1]
    age = max(0, (now - latest_at).total_seconds())
    status.update({"occupied_now": latest_count, "observation_at": latest_at.isoformat(),
                   "observation_age_seconds": round(age)})
    if age > 180:
        status["status"] = "stale_observation"
        status["reason"] = "최근 3분 안에 조회된 공식 API 기록이 없습니다."
        return status

    # 너무 짧거나 단조로운 기록을 미래 순증감 추정의 근거로 사용하지 않습니다.
    span = (latest_at - datetime.fromisoformat(rows[0][0])).total_seconds() / 60
    status["history_span_minutes"] = round(span, 1)
    changed = sum(1 for index in range(1, len(rows)) if rows[index][1] != rows[index-1][1])
    status["changes_observed"] = changed
    if len(rows) < 8 or span < 15 or changed < 2:
        status["reason"] = "최근 15분 이상·8건 이상·차량 수 2회 이상 변경된 기록이 필요합니다."
        return status

    # 앞뒤 5분 구간 평균의 차이로 시간당 순증감 추정. 최대 ±120대/시간 제한.
    start_at = datetime.fromisoformat(rows[0][0])
    first_window = [count for timestamp, count in rows if (datetime.fromisoformat(timestamp) - start_at).total_seconds() <= 300]
    last_window = [count for timestamp, count in rows if (latest_at - datetime.fromisoformat(timestamp)).total_seconds() <= 300]
    from statistics import mean as _mean
    raw_change_per_hour = (_mean(last_window) - _mean(first_window)) / span * 60
    trend_per_hour = max(-120.0, min(120.0, raw_change_per_hour))

    context = _parking_context_cache.get("events") or {}
    weather_context = _parking_context_cache.get("weather") or {}
    local_now = latest_at.astimezone(ZoneInfo("Asia/Seoul"))
    events = context.get("events") if context.get("date") == local_now.date().isoformat() else None
    weather = weather_context.get("weather") or {}
    temperature = _safe_float(weather.get("temperature"))
    rain_probability = _safe_float(weather.get("rain_probability"))
    target = weather_context.get("target")
    usable_context = (
        isinstance(events, list) and temperature is not None and rain_probability is not None and
        target is not None and abs((target - local_now).total_seconds()) <= 7200
    )

    def simulated_rate_at(instant):
        payload = ParkingPredictionRequest(
            hour=instant.hour, weekday=instant.weekday(), temperature=temperature,
            rain_probability=int(round(rain_probability)),
            events=[ScheduledEvent(**event) for event in events],
        )
        return float(predict_parking(payload)["occupancy_rate"])

    scenario_now = None
    if usable_context:
        try:
            scenario_now = simulated_rate_at(local_now)
        except Exception:
            usable_context = False

    for horizon in (30, 60, 120):
        future = local_now + timedelta(minutes=horizon)
        # 가상 모델의 '미래-현재 차이'만 낮은 가중치(20%)로 더하며, 수준 자체는 섞지 않습니다.
        scenario_delta_vehicles = 0.0
        if usable_context and future.date() == local_now.date():
            try:
                scenario_delta_vehicles = max(-100.0, min(100.0,
                    (simulated_rate_at(future) - scenario_now) / 100 * OFFICIAL_PARKING_REFERENCE_CAPACITY * 0.20
                ))
            except Exception:
                scenario_delta_vehicles = 0.0
        projected = max(0, round(latest_count + trend_per_hour * (horizon / 60) + scenario_delta_vehicles))
        ratio = round(projected / OFFICIAL_PARKING_REFERENCE_CAPACITY * 100, 1)
        status["horizons"].append({
            "minutes_ahead": horizon, "at_kst": future.isoformat(),
            "projected_occupied": projected, "reference_occupancy_percent": ratio,
            "level": "만차 수준" if ratio >= 90 else "혼잡" if ratio >= 70 else "다소혼잡" if ratio >= 50 else "여유",
            "scenario_effect_vehicles": round(scenario_delta_vehicles),
        })

    status.update({
        "status": "experimental_preview", "trend_vehicles_per_hour": round(trend_per_hour, 1),
        "scenario_context_used": usable_context,
        "scenario_event_count": len(events) if usable_context else None,
        "reason": "최근 관측값의 변화량을 단순 연장하고, 가능한 경우 가상 공연·시간 시나리오 변화의 20%를 합산합니다. 이는 임의 규칙이며 학습으로 검증되지 않았습니다.",
    })
    # 10분 버킷당 각 미래 시점 1건만 기록하여 화면 새로고침으로 생길 중복을 막습니다.
    bucket_minute = latest_at.minute // 10 * 10
    bucket = latest_at.replace(minute=bucket_minute, second=0, microsecond=0).isoformat()
    with _parking_db() as conn:
        for forecast in status["horizons"]:
            due = (latest_at + timedelta(minutes=forecast["minutes_ahead"])).isoformat()
            conn.execute("""INSERT OR IGNORE INTO hybrid_forecasts(
                forecast_bucket, created_at, source_observed_at, due_at,
                horizon_minutes, baseline_occupied, projected_occupied,
                predicted_ratio, scenario_context_used
            ) VALUES (?,?,?,?,?,?,?,?,?)""", (
                bucket, now.isoformat(), latest_at.isoformat(), due,
                forecast["minutes_ahead"], latest_count, forecast["projected_occupied"],
                forecast["reference_occupancy_percent"], int(bool(usable_context)),
            ))
    return status


@app.get("/api/parking/hybrid-evaluation")
def parking_hybrid_evaluation(hours: int = Query(168, ge=1, le=720)):
    now = datetime.now(_timezone.utc)
    with _parking_db() as conn:
        newest = conn.execute("SELECT observed_at FROM observations ORDER BY observed_at DESC LIMIT 1").fetchone()
        if newest:
            _reconcile_hybrid_forecasts(conn, newest[0])
        forecasts = conn.execute("""SELECT horizon_minutes, due_at, predicted_ratio,
            matched_observed_at, observed_ratio, absolute_error_pp, baseline_occupied
            FROM hybrid_forecasts WHERE created_at >= ? ORDER BY created_at DESC""", (
            (now - timedelta(hours=hours)).isoformat(),
        )).fetchall()

    summaries = []
    for horizon in (30, 60, 120):
        relevant = [item for item in forecasts if item[0] == horizon]
        matched = [item for item in relevant if item[3] is not None]
        expired = [item for item in relevant if item[3] is None and
                   (datetime.fromisoformat(item[1]) + timedelta(minutes=5)) < now]
        pending = len(relevant) - len(matched) - len(expired)
        mae = round(sum(item[5] for item in matched) / len(matched), 2) if matched else None
        baseline_mae = round(sum(abs(item[6] / OFFICIAL_PARKING_REFERENCE_CAPACITY * 100 - item[4])
                                 for item in matched) / len(matched), 2) if matched else None
        gain = round(baseline_mae - mae, 2) if mae is not None else None
        summaries.append({
            "minutes_ahead": horizon,
            "forecast_count": len(relevant), "matched_count": len(matched),
            "pending_count": pending, "unmatched_count": len(expired),
            "mae_percentage_points": mae,
            "unchanged_current_baseline_mae_pp": baseline_mae,
            "hybrid_improvement_pp": gain,
            "hybrid_beats_baseline": gain > 0 if gain is not None else None,
            "enough_for_initial_review": len(matched) >= 20,
        })
    recent_matches = [
        {"horizon_minutes": h, "target_at": due, "predicted_ratio": pred,
         "matched_observed_at": actual_time, "observed_ratio": observed,
         "absolute_error_pp": error,
         "unchanged_current_absolute_error_pp": round(abs(baseline / OFFICIAL_PARKING_REFERENCE_CAPACITY * 100 - observed), 2)}
        for h, due, pred, actual_time, observed, error, baseline in forecasts
        if actual_time is not None
    ][:8]
    from collections import defaultdict as _defaultdict
    time_bucket_errors = _defaultdict(list)
    for h, due, pred, actual_time, observed, error, baseline in forecasts:
        if actual_time is None:
            continue
        hour = datetime.fromisoformat(due).astimezone(ZoneInfo("Asia/Seoul")).hour
        time_bucket_errors[hour].append(error)
    hourly_errors = [
        {"hour_kst": hour, "matches": len(errors),
         "hybrid_mae_pp": round(sum(errors) / len(errors), 2)}
        for hour, errors in sorted(time_bucket_errors.items()) if len(errors) >= 3
    ]
    highest_error_hours = sorted(hourly_errors, key=lambda item: item["hybrid_mae_pp"], reverse=True)[:3]
    return {
        "status": "success", "hours": hours, "by_horizon": summaries,
        "recent_matches": recent_matches,
        "hourly_errors": hourly_errors, "highest_error_hours": highest_error_hours,
        "note": "단순 기준은 현재 차량 수가 미래에도 그대로라고 가정합니다. 대상 시각 후 5분 이내의 첫 공식 API 기록과 비교하며 실제 센서 측정 시각은 알 수 없습니다. 같은 날 근접한 예측은 서로 독립된 표본이 아니므로 적은 표본의 우열 해석에 주의하세요.",
    }


@app.get("/api/parking/export.csv")
def export_parking_observations(hours: int = Query(168, ge=1, le=720)):
    rows = _parking_rows_enriched(hours)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["observed_at_utc", "observed_at_kst", "occupied", "reference_capacity",
                     "reference_occupancy_percent", "event_count", "event_pressure_simulated",
                     "event_titles_and_places_json", "event_list_checked_at", "forecast_temperature_c",
                     "forecast_rain_probability_percent", "forecast_target_at_kst", "forecast_checked_at"])
    for (timestamp, count, event_count, event_pressure, event_titles, events_checked,
         forecast_temp, forecast_rain, forecast_target, weather_checked) in rows:
        instant = datetime.fromisoformat(timestamp)
        writer.writerow([
            timestamp, instant.astimezone(ZoneInfo("Asia/Seoul")).isoformat(),
            count, OFFICIAL_PARKING_REFERENCE_CAPACITY,
            round(count / OFFICIAL_PARKING_REFERENCE_CAPACITY * 100, 2),
            event_count, event_pressure, event_titles, events_checked,
            forecast_temp, forecast_rain, forecast_target, weather_checked,
        ])
    data = '\ufeff' + buffer.getvalue()  # Windows Excel에서 한글 컬럼 깨짐 예방
    return StreamingResponse(
        iter([data.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="olpark_parking_observations.csv"',
                 "Cache-Control": "no-store"},
    )


async def _refresh_observation_context():
    now = datetime.now(_timezone.utc)
    seoul = now.astimezone(ZoneInfo("Asia/Seoul"))
    today = seoul.date().isoformat()
    previous_events = _parking_context_cache.get("events") or {}
    previous_weather = _parking_context_cache.get("weather") or {}
    # 공연 일정은 매 30분 또는 날짜 변경 시 새로 조회합니다.
    if (previous_events.get("date") != today or
        not previous_events.get("checked_at") or
        (now - datetime.fromisoformat(previous_events["checked_at"])).total_seconds() >= 1800):
        try:
            result = await events_by_date(date=today)
            _parking_context_cache["events"] = {
                "date": today, "events": result["events"], "checked_at": now.isoformat(),
            }
        except Exception as exc:
            # 실패를 공연 0건으로 기록하면 안 됩니다.
            _parking_context_cache["events"] = {"date": today, "events": None, "checked_at": now.isoformat()}
            print(f"[parking context] 공연 조회 실패: {type(exc).__name__}")

    # 날씨는 기상청의 '미래 예보'를 별도 저장하며 실측 기온으로 표시하지 않습니다.
    if (not previous_weather.get("checked_at") or
        (now - datetime.fromisoformat(previous_weather["checked_at"])).total_seconds() >= 1800):
        try:
            result = await test_weather_api()
            raw = result["forecast_date"] + result["forecast_time"]
            target = datetime.strptime(raw, "%Y%m%d%H%M").replace(tzinfo=ZoneInfo("Asia/Seoul"))
            _parking_context_cache["weather"] = {
                "weather": result["weather"], "target": target, "checked_at": now.isoformat(),
            }
        except Exception as exc:
            _parking_context_cache["weather"] = {"weather": None, "target": None, "checked_at": now.isoformat()}
            print(f"[parking context] 날씨 예보 조회 실패: {type(exc).__name__}")


async def _parking_background_collector():
    while True:
        try:
            await _refresh_observation_context()
            snapshot = await public_parking_snapshot()
            if not snapshot["is_stale"]:
                parking_hybrid_preview()  # 새 공식 조회가 성공한 경우에만 예측을 생성합니다.
        except Exception as exc:
            # 외부 API의 일시적 장애가 웹서버를 중단시키지 않게 합니다.
            print(f"[parking collector] 조회 실패: {type(exc).__name__}")
        await asyncio.sleep(PARKING_COLLECT_INTERVAL)


@app.on_event("startup")
async def start_parking_collection():
    app.state.parking_collector = asyncio.create_task(_parking_background_collector())


@app.on_event("shutdown")
async def stop_parking_collection():
    task = getattr(app.state, "parking_collector", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@app.get("/api/events/by-date")
async def events_by_date(date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    import asyncio
    try:
        selected = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="올바른 날짜를 입력해 주세요.")
    page, fetched_at = await _fetch_official(OFFICIAL_EVENTS_URL, 300)
    parser = _TableRows()
    parser.feed(page)
    events = []
    for index, row in enumerate(parser.rows):
        if len(row) < 3:
            continue
        found = re.search(r"(\d{4}-\d{2}-\d{2})\s*[~〜-]+\s*(\d{4}-\d{2}-\d{2})", row[1])
        if not found:
            continue
        try:
            start = datetime.strptime(found.group(1), "%Y-%m-%d").date()
            end = datetime.strptime(found.group(2), "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= selected <= end:
            link = parser.row_links[index]
            match = re.search(r"evtSeq=(\d+)", link or "")
            detail_url = ("https://www.ksponco.or.kr/olympicpark/eventInfo/eventInfoView.es"
                          f"?evtSeq={match.group(1)}&mid=a20301010200") if match else None
            capacity = event_venue_capacity(row[2])
            events.append({"title": row[0], "start_date": start.isoformat(),
                           "end_date": end.isoformat(), "place": row[2],
                           "detail_url": detail_url, "start_time": None,
                           "end_time": None, "time_note": "공식 상세 일정 확인 필요",
                           "venue_capacity": capacity,
                           "estimated_audience_proxy": round(capacity * 0.70) if capacity is not None else None})

    async def add_schedule(event):
        if not event["detail_url"]:
            return
        try:
            detail_page, _ = await _fetch_official(event["detail_url"], 1800)
            start_time, end_time, raw = _detail_schedule(detail_page, selected)
            event["start_time"] = start_time
            event["end_time"] = end_time
            if start_time and end_time:
                event["time_note"] = "종료 시각은 공식 소요시간을 더한 예상 시각입니다."
            elif start_time:
                event["time_note"] = "종료 시각은 공식 안내에서 확인되지 않았습니다."
            else:
                event["time_note"] = "해당 날짜의 회차 시간을 확인하지 못했습니다."
        except Exception:
            # 상세 페이지가 실패해도 목록 및 날짜 조회는 계속 제공
            event["time_note"] = "상세 공연 시간 조회 실패 · 공식 사이트에서 확인 필요"

    await asyncio.gather(*(add_schedule(event) for event in events))
    return {
        "status": "success", "date": date, "count": len(events), "events": events,
        "source": OFFICIAL_EVENTS_URL,
        "note": "현재 공식 목록을 검색합니다. 공연장 수용 인원은 시설의 최대·가변 규모로 공연별 판매 좌석과 다릅니다. 예상 관객 규모는 객석 점유율 70%를 가정한 시뮬레이션입니다."
    }
