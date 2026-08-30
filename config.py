# -*- coding: utf-8 -*-
"""
교통 관제탑 - 데이터셋 설정

BASE_DIR 는 이 폴더(관제탑)의 상위 폴더인 '한이음' 폴더를 가리킵니다.
영상/CSV 파일의 실제 위치가 바뀌면 아래 DATASETS 의 dir/prefix 만 고쳐주세요.
"""

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent          # .../Documents/한이음
CACHE_DIR = APP_DIR / "cache"
WEB_MEDIA_DIR = APP_DIR / "web_media"   # 브라우저 재생용 H.264 변환본
PLACES_FILE = APP_DIR / "places.json"   # 현장에서 고친 좌표를 저장하는 곳
WEIGHTS_PATH = BASE_DIR / "cctv_car_bus_truck" / "weights" / "best.pt"

# 속도 위험도 판정 기준
# 안전: 제한속도 미만 / 주의: 제한속도 ~ 제한속도x1.3 / 위험: 제한속도x1.3 이상
RISK_CAUTION_RATIO = 1.0
RISK_DANGER_RATIO = 1.3

# 측정 신뢰도 보정
# CCTV + BEV 좌표 계산은 추적 ID 가 바뀌거나 화면 먼 쪽에서 좌표가 튈 때
# 실제로는 불가능한 속도가 나옵니다. 아래 값보다 큰 수치는 측정 오류로 보고 버립니다.
MAX_PLAUSIBLE_SPEED = 150.0

# 이 프레임 수보다 짧게 잡힌 차량은 속도를 믿기 어려워 '측정 부족' 으로 표시합니다.
MIN_OBSERVED_FRAMES = 15

# 위험도 판정에 쓰는 값: 순간 최고속도는 한 프레임만 튀어도 과대평가되므로
# '초 단위 최고속도의 90퍼센타일(= 꾸준히 낸 속도)' 을 기준으로 삼습니다.
STABLE_PERCENTILE = 0.9

# ----------------------------------------------------------------------
# 장소(현장) 정의
#   여러 영상이 같은 교차로를 찍은 경우 하나의 장소로 묶습니다.
#   올림픽공원 ①②③ -> 한 장소 / 워커힐 ①②③ -> 한 장소
#   radius_m : 이 거리 안으로 들어오면 해당 장소로 자동 전환합니다.
# ----------------------------------------------------------------------
PLACES = {
    "olympicpark": {
        "id": "olympicpark",
        "name": "올림픽공원 교차로",
        "short": "올림픽공원",
        # 출처: bev_v2_위경도.py 의 기준점 4개 평균 (실측값)
        "lat": 37.517686,
        "lon": 127.112864,
        "radius_m": 150,
        "source": "measured",
    },
    "olympicpark_south": {
        "id": "olympicpark_south",
        "name": "올림픽공원 남단 교차로",
        "short": "올림픽공원 남단",
        "lat": 37.514500,
        "lon": 127.123000,
        "radius_m": 150,
        "source": "approx",
    },
    "walkerhill": {
        "id": "walkerhill",
        "name": "워커힐 교차로",
        "short": "워커힐",
        "lat": 37.547700,
        "lon": 127.098300,
        "radius_m": 150,
        "source": "approx",
    },
}

DATASETS = [
    {
        "id": "olympicpark1",
        "place_id": "olympicpark",
        "name": "올림픽공원 ①",
        "place": "올림픽공원 교차로",
        "desc": "낮 시간 · 10분",
        "dir": "올림픽공원_낮-002/올림픽공원_낮1",
        "prefix": "올림픽공원_낮1",
        "signal_csv": "signal_time/olympicpark1_signal_time.csv",
        "speed_limit": 50,
    },
    {
        "id": "olympicpark2",
        "place_id": "olympicpark",
        "name": "올림픽공원 ②",
        "place": "올림픽공원 교차로",
        "desc": "낮 시간 · 10분",
        "dir": "올림픽공원_낮-002/올림픽공원_낮2",
        "prefix": "올림픽공원_낮2",
        "signal_csv": "signal_time/olympicpark2_signal_time.csv",
        "speed_limit": 50,
    },
    {
        "id": "olympicpark3",
        "place_id": "olympicpark",
        "name": "올림픽공원 ③",
        "place": "올림픽공원 교차로",
        "desc": "낮 시간 · 10분",
        "dir": "올림픽공원_낮-002/올림픽공원_낮3",
        "prefix": "올림픽공원_낮3",
        "signal_csv": "signal_time/olympicpark3_signal_time.csv",
        "speed_limit": 50,
    },
    {
        "id": "olympicpark_south",
        "place_id": "olympicpark_south",
        "name": "올림픽공원 남단",
        "place": "올림픽공원 남단 교차로",
        "desc": "낮 시간 · 30분",
        "dir": "올림픽공원남단_낮1",
        "prefix": "올림픽공원남단_낮1",
        "signal_csv": "signal_time/olympicpark_south_signal_time.csv",
        "speed_limit": 50,
    },
    {
        "id": "walkerhill1",
        "place_id": "walkerhill",
        "name": "워커힐 ①",
        "place": "워커힐 교차로",
        "desc": "낮 시간 · 10분",
        "dir": "워커힐_낮-001/워커힐_낮1",
        "prefix": "워커힐_낮1",
        "signal_csv": "signal_time/walkerhill1_signal_time.csv",
        "speed_limit": 50,
    },
    {
        "id": "walkerhill2",
        "place_id": "walkerhill",
        "name": "워커힐 ②",
        "place": "워커힐 교차로",
        "desc": "낮 시간 · 10분",
        "dir": "워커힐_낮-001/워커힐_낮2",
        "prefix": "워커힐_낮2",
        "signal_csv": "signal_time/walkerhill2_signal_time.csv",
        "speed_limit": 50,
    },
    {
        "id": "walkerhill3",
        "place_id": "walkerhill",
        "name": "워커힐 ③",
        "place": "워커힐 교차로",
        "desc": "낮 시간 · 10분",
        "dir": "워커힐_낮-001/워커힐_낮3",
        "prefix": "워커힐_낮3",
        "signal_csv": "signal_time/walkerhill3_signal_time.csv",
        "speed_limit": 50,
    },
]

DATASET_BY_ID = {d["id"]: d for d in DATASETS}

# 신호 CSV 컬럼 -> 화면에 보여줄 한글 이름
SIGNAL_LABELS = {
    "NE_straight": "북동쪽 직진",
    "SW_straight": "남서쪽 직진",
    "NW_straight": "북서쪽 직진",
    "SE_straight": "남동쪽 직진",
    "NE_left": "북동쪽 좌회전",
    "SW_left": "남서쪽 좌회전",
    "NW_left": "북서쪽 좌회전",
    "SE_left": "남동쪽 좌회전",
    "NE_crosswalk": "북동쪽 횡단보도",
    "SW_crosswalk": "남서쪽 횡단보도",
    "NW_crosswalk": "북서쪽 횡단보도",
    "SE_crosswalk": "남동쪽 횡단보도",
    "crosswalk": "횡단보도",
}

SIGNAL_META_COLUMNS = {"start_sec", "end_sec", "confidence", "note"}

RISK_TEXT = {
    "safe": "안전",
    "caution": "주의",
    "danger": "위험",
    "unknown": "측정 부족",
}

STATE_TEXT = {
    "GREEN": "초록불",
    "YELLOW": "노란불",
    "RED": "빨간불",
    "OFF": "꺼짐",
    "UNKNOWN": "확인중",
}


def paths_for(ds):
    """데이터셋의 파일 경로 묶음을 돌려줍니다."""
    d = BASE_DIR / ds["dir"]
    p = ds["prefix"]
    return {
        "yolo_video": d / (p + "_yolo.mp4"),
        "bev_video": d / (p + "_bev_velocity.mp4"),
        "result_csv": d / (p + "_result.csv"),
        "speed_csv": d / (p + "_speed.csv"),
        "break_csv": d / (p + "_break.csv"),
        "coord_csv": d / (p + "_coordinates.csv"),
        "signal_csv": BASE_DIR / ds["signal_csv"],
        "web_yolo": WEB_MEDIA_DIR / (ds["id"] + "_yolo.mp4"),
        "web_bev": WEB_MEDIA_DIR / (ds["id"] + "_bev.mp4"),
        "web_twin": WEB_MEDIA_DIR / (ds["id"] + "_twin.mp4"),
        "twin_video": d / (p + "_twin.mp4"),
        "stopline_csv": d / (p + "_stopline_summary.csv"),
        "tailgate_csv": d / (p + "_tailgate_summary.csv"),
    }


def playable(ds, kind):
    """
    브라우저에 보낼 영상 경로.
    web_media/ 에 H.264 변환본이 있으면 그것을, 없으면 원본을 씁니다.
    (원본은 mp4v 코덱이라 크롬에서는 재생되지 않습니다.)
    """
    p = paths_for(ds)
    key = {"yolo": ("web_yolo", "yolo_video"),
           "bev": ("web_bev", "bev_video"),
           "twin": ("web_twin", "twin_video")}.get(kind)
    if key is None:
        return p["yolo_video"]
    web, raw = p[key[0]], p[key[1]]
    return web if web.exists() else raw


def load_places():
    """places.json 에 저장된 보정 좌표를 얹어서 돌려줍니다."""
    import copy
    import json

    places = copy.deepcopy(PLACES)
    if PLACES_FILE.exists():
        try:
            saved = json.loads(PLACES_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            saved = {}
        for pid, val in (saved or {}).items():
            if pid in places and isinstance(val, dict):
                for key in ("lat", "lon", "radius_m"):
                    if key in val:
                        try:
                            places[pid][key] = float(val[key])
                        except (TypeError, ValueError):
                            pass
                places[pid]["source"] = "saved"
    for pid, pl in places.items():
        pl["videos"] = [d["id"] for d in DATASETS if d.get("place_id") == pid]
    return places


def save_place(place_id, lat, lon, radius_m=None):
    """현장에서 잡은 좌표를 places.json 에 기록합니다."""
    import json

    if place_id not in PLACES:
        raise KeyError(place_id)
    data = {}
    if PLACES_FILE.exists():
        try:
            data = json.loads(PLACES_FILE.read_text(encoding="utf-8")) or {}
        except (ValueError, OSError):
            data = {}
    entry = data.get(place_id, {})
    entry["lat"] = float(lat)
    entry["lon"] = float(lon)
    if radius_m is not None:
        entry["radius_m"] = float(radius_m)
    data[place_id] = entry
    PLACES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return load_places()[place_id]


def distance_m(lat1, lon1, lat2, lon2):
    """두 위경도 사이 거리(m). 하버사인 공식."""
    import math

    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def risk_of(speed, limit):
    """속도(km/h) 하나를 안전/주의/위험으로 분류합니다."""
    if speed >= limit * RISK_DANGER_RATIO:
        return "danger"
    if speed >= limit * RISK_CAUTION_RATIO:
        return "caution"
    return "safe"
