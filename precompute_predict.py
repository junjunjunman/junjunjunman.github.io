# -*- coding: utf-8 -*-
"""
관제탑 - 이동경로 예측(LSTM) 결과를 웹용으로 줄이기

'이동경로 예측' 폴더의 예측 CSV 는 31~136MB 라 웹에서 그대로 못 씁니다.
필요한 것만 뽑아 지점별 JSON 으로 만듭니다.

  - 예측 결과는 30프레임 입력 -> 30프레임 예측이고, 1프레임씩 밀며 만든 표본입니다.
  - 전부 쓰면 너무 많으므로 STEP 프레임마다 하나씩만 남깁니다.
  - 예측 경로 30점도 6점으로 줄입니다. (점선으로 그리기에 충분)

사용법
    python precompute_predict.py
    python precompute_predict.py --force
"""

import csv
import json
import os
import re
import sys
import time

import config as C

STEP = 15          # 몇 프레임마다 예측 하나를 남길지
PATH_POINTS = 6    # 예측 경로를 몇 점으로 줄일지 (30점 -> 6점)

POINT = re.compile(r"\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)")

# 예측 폴더 -> 이 폴더가 담당하는 데이터셋들 (id 앞자리 -> dataset id)
SOURCES = [
    {"dir": "이동경로 예측/워커힐_낮",
     "csv": "워커힐_낮_lstm_prediction_result.csv",
     "map": {"1": "walkerhill1", "2": "walkerhill2", "3": "walkerhill3"}},
    {"dir": "이동경로 예측/올림픽공원_낮",
     "csv": "올림픽공원_낮_lstm_prediction_result.csv",
     "map": {"1": "olympicpark1", "2": "olympicpark2", "3": "olympicpark3"}},
    {"dir": "이동경로 예측/올림픽공원남단_낮",
     "csv": "올림픽공원남단_낮_lstm_prediction_result.csv",
     "map": {"1": "olympicpark_south"}},
]


def coord_index(ds_id):
    """차량별 (x,y) -> 프레임 번호. 예측 표본의 시각을 알아내는 데 씁니다."""
    ds = C.DATASET_BY_ID.get(ds_id)
    if not ds:
        return {}
    path = C.paths_for(ds)["coord_csv"]
    if not path.exists():
        return {}

    index = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        f.readline()
        for line in f:
            cells = next(csv.reader([line]))
            vid = cells[0].strip()
            if not vid:
                continue
            d = {}
            for col in range(1, len(cells)):
                c = cells[col].strip()
                if not c or c in ("NULL", "None", "nan"):
                    continue
                m = POINT.match(c)
                if m:
                    key = (round(float(m.group(1)), 1), round(float(m.group(2)), 1))
                    d.setdefault(key, col)
            index[vid] = d
    return index


def build(src, force=False):
    base = C.BASE_DIR / src["dir"] / src["csv"]
    if not base.exists():
        print("  파일 없음:", base.name)
        return

    targets = sorted(set(src["map"].values()))
    if not force and all((C.CACHE_DIR / ("predict-%s.json" % t)).exists()
                         for t in targets):
        print("  건너뜀 (캐시 있음):", ", ".join(targets))
        return

    print("\n  %s  (%.0f MB)" % (src["csv"], base.stat().st_size / 1e6))
    t0 = time.time()

    indexes = {t: coord_index(t) for t in targets}
    print("     좌표 색인 완료 (%.1f초)" % (time.time() - t0))

    out = {t: {} for t in targets}      # ds_id -> {frame: [ [id, x,y, ...], ... ]}
    last_kept = {}                      # (ds, vid) -> 마지막으로 남긴 프레임
    total = kept = unmatched = 0

    with open(base, "r", encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader([f.readline()]))
        col = {c: i for i, c in enumerate(header)}
        anchor_x, anchor_y = col["in_frame30_x"], col["in_frame30_y"]
        pick = [1 + round(i * 29 / (PATH_POINTS - 1)) for i in range(PATH_POINTS)]
        px = [col["pred_out_frame%d_x" % i] for i in pick]
        py = [col["pred_out_frame%d_y" % i] for i in pick]

        for line in f:
            row = next(csv.reader([line]))
            total += 1
            rid = row[0]
            if "_" not in rid:
                continue
            pref, vid = rid.split("_", 1)
            ds_id = src["map"].get(pref)
            if not ds_id:
                continue

            try:
                ax = round(float(row[anchor_x]), 1)
                ay = round(float(row[anchor_y]), 1)
            except (ValueError, IndexError):
                continue

            frame = indexes[ds_id].get(vid, {}).get((ax, ay))
            if frame is None:
                unmatched += 1
                continue

            key = (ds_id, vid)
            if frame - last_kept.get(key, -10 ** 9) < STEP:
                continue
            last_kept[key] = frame

            try:
                path = []
                for i in range(PATH_POINTS):
                    path.append(round(float(row[px[i]]), 1))
                    path.append(round(float(row[py[i]]), 1))
            except (ValueError, IndexError):
                continue

            out[ds_id].setdefault(frame, []).append([vid] + path)
            kept += 1

    for ds_id in targets:
        data = {
            "id": ds_id,
            "step": STEP,
            "points": PATH_POINTS,
            "horizon_frames": 30,
            "preds": {str(k): v for k, v in sorted(out[ds_id].items())},
        }
        p = C.CACHE_DIR / ("predict-%s.json" % ds_id)
        p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
        print("     %-22s 예측 %5d개  %5.1f MB"
              % (p.name, sum(len(v) for v in out[ds_id].values()),
                 p.stat().st_size / 1e6))

    print("     표본 %d개 중 %d개 사용, 프레임 못 찾음 %d개 (%.0f초)"
          % (total, kept, unmatched, time.time() - t0))


def main():
    force = "--force" in sys.argv
    C.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 66)
    print(" 이동경로 예측 데이터 줄이기  (%d프레임마다 1개, 경로 %d점)"
          % (STEP, PATH_POINTS))
    print("=" * 66)
    for src in SOURCES:
        build(src, force)
    print("\n완료")


if __name__ == "__main__":
    main()
