# -*- coding: utf-8 -*-
"""
교통 관제탑 - 데이터 미리 계산 스크립트

각 영상의 _speed.csv (프레임별 차량 속도) 를 읽어
웹에서 바로 쓸 수 있는 작은 JSON 캐시를 cache/ 폴더에 만듭니다.

속도 데이터에는 추적 ID 가 바뀌면서 생기는 튀는 값이 섞여 있어서
 - config.MAX_PLAUSIBLE_SPEED 보다 큰 값은 버리고
 - 위험도 판정은 '초 단위 최고속도의 90퍼센타일(꾸준히 낸 속도)' 로 하고
 - 아주 짧게만 잡힌 차량은 '측정 부족' 으로 따로 표시합니다.

사용법:
    python precompute.py              # 캐시가 없는 것만 계산
    python precompute.py --force      # 전부 다시 계산
    python precompute.py olympicpark1 # 특정 영상만 계산
"""

import json
import sys
import time

import config as C

TOP_N_PER_SECOND = 12   # 1초마다 화면에 보여줄 차량 최대 개수


def get_fps_and_frames(video_path):
    """영상에서 fps 와 총 프레임 수를 읽습니다. (opencv 사용)"""
    try:
        import cv2
    except ImportError:
        return 30.0, 0
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 30.0, 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    if fps <= 0:
        fps = 30.0
    return float(fps), frames


def percentile(sorted_vals, ratio):
    if not sorted_vals:
        return 0.0
    idx = int(len(sorted_vals) * ratio)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


def scan_speed_csv(path, fps, limit):
    """
    _speed.csv 를 한 줄씩 흘려 읽으며
      - 1초 단위 통계 (per_sec)
      - 차량별 요약 (vehicles)
    를 만듭니다. 파일이 1GB 를 넘을 수 있어 csv 모듈 대신 직접 split 합니다.
    """
    cap_speed = C.MAX_PLAUSIBLE_SPEED
    per_sec = {}
    vehicles = {}
    dropped = 0
    n_frames = 0

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        header = f.readline().rstrip("\r\n").split(",")
        n_frames = max(len(header) - 1, 0)

        # 프레임 번호 -> 초 변환표를 미리 만들어 두면 훨씬 빠릅니다.
        sec_of = [int(i / fps) for i in range(n_frames)]

        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                continue
            parts = line.split(",")
            vid = parts[0].strip().strip('"')
            if not vid:
                continue

            local = {}      # 초 -> 그 초 안에서의 최고 속도
            total = 0.0
            count = 0

            for idx in range(1, len(parts)):
                v = parts[idx]
                if not v or v == "NULL":
                    continue
                try:
                    sp = float(v)
                except ValueError:
                    continue
                if sp > cap_speed:      # 측정 오류로 보고 버립니다
                    dropped += 1
                    continue
                total += sp
                count += 1
                sec = sec_of[idx - 1] if idx - 1 < n_frames else int((idx - 1) / fps)
                if sp > local.get(sec, -1.0):
                    local[sec] = sp

            if not local:
                continue

            secs = sorted(local)
            per_sec_max = sorted(local.values())
            stable = percentile(per_sec_max, C.STABLE_PERCENTILE)
            peak = per_sec_max[-1]
            avg = total / count if count else 0.0

            risk = ("unknown" if count < C.MIN_OBSERVED_FRAMES
                    else C.risk_of(stable, limit))

            vehicles[vid] = {
                "id": vid,
                "stable": round(stable, 1),
                "max": round(peak, 1),
                "avg": round(avg, 1),
                "frames": count,
                "seconds": round(count / fps, 1),
                "first": secs[0],
                "last": secs[-1],
                "risk": risk,
            }

            for sec, sp in local.items():
                bucket = per_sec.get(sec)
                if bucket is None:
                    bucket = per_sec[sec] = []
                bucket.append((vid, sp))

    return per_sec, vehicles, n_frames, dropped


def build_timeline(per_sec, duration_sec, limit):
    timeline = []
    for sec in range(duration_sec + 1):
        bucket = per_sec.get(sec)
        if not bucket:
            timeline.append({
                "t": sec, "count": 0, "avg": 0.0, "max": 0.0,
                "safe": 0, "caution": 0, "danger": 0, "vehicles": [],
            })
            continue

        speeds = [sp for _, sp in bucket]
        counts = {"safe": 0, "caution": 0, "danger": 0}
        for sp in speeds:
            counts[C.risk_of(sp, limit)] += 1

        top = sorted(bucket, key=lambda x: -x[1])[:TOP_N_PER_SECOND]
        timeline.append({
            "t": sec,
            "count": len(speeds),
            "avg": round(sum(speeds) / len(speeds), 1),
            "max": round(max(speeds), 1),
            "safe": counts["safe"],
            "caution": counts["caution"],
            "danger": counts["danger"],
            "vehicles": [
                {"id": vid, "speed": round(sp, 1), "risk": C.risk_of(sp, limit)}
                for vid, sp in top
            ],
        })
    return timeline


def build_one(ds, force=False):
    C.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = C.CACHE_DIR / (ds["id"] + ".json")
    if out_path.exists() and not force:
        print("  [건너뜀] 캐시가 이미 있습니다 ->", out_path.name)
        return

    p = C.paths_for(ds)
    limit = ds["speed_limit"]

    missing = [k for k in ("yolo_video", "speed_csv") if not p[k].exists()]
    if missing:
        print("  [경고] 파일이 없어 건너뜁니다:", ", ".join(missing))
        return

    t0 = time.time()
    fps, frames = get_fps_and_frames(p["yolo_video"])
    print("     fps=%.3f, 총 프레임=%d" % (fps, frames))

    per_sec, vehicles, n_frames, dropped = scan_speed_csv(p["speed_csv"], fps, limit)
    if frames <= 0:
        frames = n_frames
    duration = int(frames / fps) if fps else 0

    timeline = build_timeline(per_sec, duration, limit)
    veh_list = sorted(vehicles.values(), key=lambda v: v["id"])

    judged = [v for v in veh_list if v["risk"] != "unknown"]
    stables = [v["stable"] for v in judged] or [0.0]
    peaks = [v["max"] for v in judged] or [0.0]

    summary = {
        "total_vehicles": len(veh_list),
        "judged": len(judged),
        "danger": sum(1 for v in judged if v["risk"] == "danger"),
        "caution": sum(1 for v in judged if v["risk"] == "caution"),
        "safe": sum(1 for v in judged if v["risk"] == "safe"),
        "unknown": len(veh_list) - len(judged),
        "max_speed": round(max(peaks), 1),
        "avg_speed": round(sum(stables) / len(stables), 1),
        "busiest_sec": max(timeline, key=lambda x: x["count"])["t"] if timeline else 0,
        "peak_count": max((x["count"] for x in timeline), default=0),
        "dropped_readings": dropped,
    }

    data = {
        "id": ds["id"],
        "name": ds["name"],
        "place": ds["place"],
        "fps": round(fps, 3),
        "frames": frames,
        "duration": duration,
        "speed_limit": limit,
        "thresholds": {
            "caution": round(limit * C.RISK_CAUTION_RATIO, 1),
            "danger": round(limit * C.RISK_DANGER_RATIO, 1),
            "cap": C.MAX_PLAUSIBLE_SPEED,
            "min_frames": C.MIN_OBSERVED_FRAMES,
        },
        "summary": summary,
        "timeline": timeline,
        "vehicles": veh_list,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    print("  [완료] %s  차량 %d대(판정 %d대), %d초, 버린 측정값 %d개"
          "  (%.1f초 걸림, %.1f MB)" % (
              out_path.name, summary["total_vehicles"], summary["judged"],
              duration, dropped, time.time() - t0,
              out_path.stat().st_size / 1e6))


def main():
    args = list(sys.argv[1:])
    force = "--force" in args
    args = [a for a in args if not a.startswith("--")]

    targets = C.DATASETS
    if args:
        targets = [d for d in C.DATASETS if d["id"] in args]
        if not targets:
            print("그런 이름의 영상이 없습니다:", ", ".join(args))
            return

    print("=" * 60)
    print("교통 관제탑 데이터 준비를 시작합니다. (%d개)" % len(targets))
    print("=" * 60)
    for ds in targets:
        print("\n> %s (%s)" % (ds["name"], ds["id"]))
        build_one(ds, force=force)
    print("\n모든 준비가 끝났습니다. 이제 python app.py 를 실행하세요.")


if __name__ == "__main__":
    main()
