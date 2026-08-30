# -*- coding: utf-8 -*-
"""
교통 관제탑 - GitHub Pages 용 정적 사이트 만들기

Flask 서버 없이 돌아가는 완성본을 docs/ 폴더에 만듭니다.
  - API 응답을 JSON 파일로 미리 구워 넣고
  - 영상을 가볍게 다시 인코딩하고 (기본 854x480)
  - index.html 을 정적 모드로 바꿉니다.

사용법
    python build_static.py                     기본 (480p)
    python build_static.py --quality 360p      더 가볍게
    python build_static.py --quality 720p      더 선명하게
    python build_static.py --base /repo-name   저장소 하위 경로에 올릴 때
    python build_static.py --skip-video        영상은 그대로 두고 화면만 다시 굽기

만들어진 docs/ 폴더를 그대로 깃허브에 올리고
저장소 Settings > Pages > Source 를 'main 브랜치 / docs 폴더' 로 지정하면 끝입니다.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time

import config as C

OUT = C.APP_DIR / "docs"

# 차량 인식 영상(가로형)과 평면 변환 영상(세로형)은 성격이 달라 따로 잡습니다.
# BEV 는 원근 변환 때문에 화면 전체가 흐릿하게 늘어나 있어 용량을 많이 먹습니다.
# 대신 중요한 정보(빨간 점·속도 글자)는 압축에 잘 견디므로 crf 를 높게 줍니다.
QUALITY = {
    "360p": {"yolo": {"w": 640, "crf": 32}, "bev": {"h": 560, "crf": 34},
             "twin": {"h": 720, "crf": 30}},
    "480p": {"yolo": {"w": 854, "crf": 28}, "bev": {"h": 720, "crf": 32},
             "twin": {"h": 964, "crf": 28}},
    "720p": {"yolo": {"w": 1280, "crf": 30}, "bev": {"h": 900, "crf": 30},
             "twin": {"h": 964, "crf": 26}},
}

TARGET_MAX = 90 * 1024 * 1024   # 파일 하나가 이보다 크면 자동으로 더 압축합니다

GITHUB_FILE_LIMIT = 100 * 1024 * 1024      # 파일 하나 100MB
PAGES_SITE_LIMIT = 1024 * 1024 * 1024      # 사이트 전체 1GB 권장


# ----------------------------------------------------------------------
def build_data():
    """API 응답을 JSON 파일로 굽습니다."""
    data_dir = OUT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    places = C.load_places()
    for pid, pl in places.items():
        pl["items"] = [{"id": d["id"], "name": d["name"], "desc": d["desc"]}
                       for d in C.DATASETS if d.get("place_id") == pid]
    (data_dir / "places.json").write_text(
        json.dumps({"places": list(places.values()), "default_radius": 150},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    videos = []
    for ds in C.DATASETS:
        cache = C.CACHE_DIR / (ds["id"] + ".json")
        if not cache.exists():
            print("  [건너뜀] 분석 데이터 없음:", ds["id"])
            continue
        d = json.loads(cache.read_text(encoding="utf-8"))

        events = read_events(ds)
        predict = C.CACHE_DIR / ("predict-%s.json" % ds["id"])
        has_twin = C.playable(ds, "twin").exists()
        has_twin_spot = C.playable(ds, "twin_spot").exists()

        videos.append({
            "id": ds["id"],
            "place_id": ds.get("place_id"),
            "has_twin": has_twin,
            "has_twin_spot": has_twin_spot,
            "has_predict": predict.exists(),
            "name": ds["name"],
            "place": ds["place"],
            "desc": ds["desc"],
            "speed_limit": ds["speed_limit"],
            "ready": True,
            "web_ready": True,
            "has_bev": True,
            "duration": d["duration"],
            "summary": d["summary"],
        })

        d["desc"] = ds["desc"]
        d["has_bev"] = True
        d["has_twin"] = has_twin
        d["has_twin_spot"] = has_twin_spot
        d["events"] = events
        d["predict"] = {
            "available": predict.exists(),
            "step": 15, "points": 6, "horizon_frames": 30,
            "count": 0,
        }
        if predict.exists():
            pj = json.loads(predict.read_text(encoding="utf-8"))
            d["predict"].update({
                "step": pj["step"], "points": pj["points"],
                "horizon_frames": pj["horizon_frames"],
                "count": sum(len(v) for v in pj["preds"].values()),
            })
            (data_dir / ("predict-%s.json" % ds["id"])).write_text(
                predict.read_text(encoding="utf-8"), encoding="utf-8")
        d["web_ready"] = True
        d["weights"] = C.WEIGHTS_PATH.name
        d["place"] = places.get(ds.get("place_id"))
        d["signal"] = read_signal(ds)
        (data_dir / ("video-%s.json" % ds["id"])).write_text(
            json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    (data_dir / "videos.json").write_text(
        json.dumps({"videos": videos,
                    "weights": "cctv_car_bus_truck/weights/" + C.WEIGHTS_PATH.name,
                    "weights_ok": True},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("  데이터 %d개 지점 구움" % len(videos))
    return videos


def read_events(ds):
    """정지선 위반 / 꼬리물기 요약 CSV 를 읽습니다. (app.py 와 같은 형식)"""
    import csv as _csv
    p = C.paths_for(ds)
    out = {"stopline": [], "tailgate": []}

    def rows(path):
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(_csv.DictReader(f))

    for r in rows(p["stopline_csv"]):
        try:
            out["stopline"].append({
                "kind": "stopline", "id": r.get("ID", ""),
                "sec": float(r.get("start_sec") or 0),
                "end": float(r.get("end_sec") or 0),
                "lane": r.get("lane", ""), "signal": r.get("signal", ""),
                "state": r.get("state", ""),
                "x": float(r.get("x") or 0), "y": float(r.get("y") or 0),
                "note": r.get("note", ""),
            })
        except ValueError:
            continue
    for r in rows(p["tailgate_csv"]):
        try:
            out["tailgate"].append({
                "kind": "tailgate", "id": r.get("ID", ""),
                "sec": float(r.get("start_sec") or 0),
                "end": float(r.get("end_sec") or 0),
                "direction": r.get("direction", ""), "state": r.get("state", ""),
                "stay": float(r.get("stay_sec") or 0),
                "slow": float(r.get("slow_sec") or 0),
                "x": float(r.get("x") or 0), "y": float(r.get("y") or 0),
                "note": r.get("note", ""),
            })
        except ValueError:
            continue
    out["stopline"].sort(key=lambda e: e["sec"])
    out["tailgate"].sort(key=lambda e: e["sec"])
    return out


def read_signal(ds):
    import csv
    path = C.paths_for(ds)["signal_csv"]
    if not path.exists():
        return {"columns": [], "intervals": [], "state_text": C.STATE_TEXT}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = [c for c in (reader.fieldnames or []) if c not in C.SIGNAL_META_COLUMNS]
        intervals = []
        for row in reader:
            try:
                start, end = float(row["start_sec"]), float(row["end_sec"])
            except (KeyError, TypeError, ValueError):
                continue
            states = {}
            for c in cols:
                v = (row.get(c) or "RED").strip().upper()
                states[c] = v if v in C.STATE_TEXT else "UNKNOWN"
            intervals.append({"start": start, "end": end, "states": states,
                              "confidence": (row.get("confidence") or "").strip(),
                              "note": (row.get("note") or "").strip()})
    intervals.sort(key=lambda x: x["start"])
    return {
        "columns": [{"key": c, "label": C.SIGNAL_LABELS.get(c, c),
                     "kind": "crosswalk" if "crosswalk" in c else "vehicle"}
                    for c in cols],
        "intervals": intervals,
        "state_text": C.STATE_TEXT,
    }


# ----------------------------------------------------------------------
def build_shell():
    """
    HTML/CSS/JS/아이콘을 정적 모드로 복사합니다.
    모든 경로를 상대 경로로 바꾸므로
    user.github.io/ 든 user.github.io/저장소이름/ 든 그대로 동작합니다.
    """
    static_src = C.APP_DIR / "static"
    shutil.copytree(static_src, OUT / "static", dirs_exist_ok=True)

    html = (C.APP_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    stamp = str(int(time.time()))
    html = html.replace("{{ asset_version }}", stamp)
    html = html.replace('href="/', 'href="./')
    html = html.replace('src="/', 'src="./')
    html = html.replace('<script src="./static/js/main.js',
                        '<script>window.STATIC_MODE=true;</script>\n'
                        '<script src="./static/js/main.js')
    html = html.replace('<a href="./test">영상 재생 테스트</a> · ', "")
    (OUT / "index.html").write_text(html, encoding="utf-8")

    man = json.loads((static_src / "manifest.webmanifest").read_text(encoding="utf-8"))
    man["start_url"] = "./"
    man["scope"] = "./"
    for ic in man["icons"]:
        ic["src"] = "." + ic["src"]
    (OUT / "manifest.webmanifest").write_text(
        json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")

    sw = (static_src / "sw.js").read_text(encoding="utf-8")
    sw = sw.replace("const CACHE = 'gwanje-v3';", "const CACHE = 'gwanje-static-%s';" % stamp)
    sw = sw.replace("""const SHELL = [
  '/',
  '/static/css/style.css',
  '/static/js/main.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];""", """const SHELL = [
  './',
  './index.html',
  './static/css/style.css',
  './static/js/main.js',
  './manifest.webmanifest',
  './static/icons/icon-192.png',
  './static/icons/icon-512.png',
  './data/videos.json',
  './data/places.json'
];""")
    sw = sw.replace("caches.match('/')", "caches.match('./')")
    (OUT / "sw.js").write_text(sw, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    for junk in OUT.rglob("*.part.mp4"):
        try:
            junk.unlink()
        except OSError:
            pass
    print("  화면 파일 복사 완료 (상대 경로)")


# ----------------------------------------------------------------------
def encode(src, dst, kind, q):
    """
    한 파일을 인코딩합니다.
    결과가 깃허브 제한에 걸릴 만큼 크면 압축을 한 단계씩 올려 다시 시도합니다.
    """
    conf = q["twin" if kind == "twin_spot" else kind]
    crf = conf["crf"]

    # 영상이 길수록 같은 화질이어도 용량이 커집니다. 20분을 넘으면 한 단계 더 압축.
    try:
        import cv2
        cap = cv2.VideoCapture(str(src))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        cap.release()
        if frames / fps > 20 * 60:
            crf += 4
    except Exception:
        pass

    for attempt in range(3):
        if kind == "yolo":
            vf = "scale='min(%d,iw)':-2" % conf["w"]
        elif kind in ("twin", "twin_spot"):
            vf = ("scale=w='min(%d,iw)':h='min(%d,ih)'"
                  ":force_original_aspect_ratio=decrease:force_divisible_by=2"
                  % (conf["h"], conf["h"]))
        else:
            vf = ("scale=w='min(%d,iw)':h='min(%d,ih)'"
                  ":force_original_aspect_ratio=decrease:force_divisible_by=2"
                  % (conf["h"], conf["h"]))

        tmp = dst.with_suffix(".part.mp4")
        r = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(src),
            "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(tmp),
        ])
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return None

        size = tmp.stat().st_size
        if size <= TARGET_MAX or attempt == 2:
            tmp.replace(dst)
            return crf, size
        crf += 4
        print("        %.0fMB 라 압축을 더 올립니다 (crf %d)" % (size / 1e6, crf))
        tmp.unlink(missing_ok=True)
    return None


def build_media(quality, force):
    """영상을 가볍게 다시 인코딩합니다."""
    if shutil.which("ffmpeg") is None:
        print("  ffmpeg 이 없어 영상 변환을 건너뜁니다. brew install ffmpeg")
        return []

    q = QUALITY[quality]
    media = OUT / "media"
    media.mkdir(parents=True, exist_ok=True)
    made = []

    for ds in C.DATASETS:
        for kind in ("yolo", "bev", "twin", "twin_spot"):
            src = C.playable(ds, kind)
            if not src.exists():
                continue
            dst = media / ("%s_%s.mp4" % (ds["id"], kind))
            if dst.exists() and 0 < dst.stat().st_size <= TARGET_MAX and not force:
                print("     건너뜀 (있음): %s  %.1fMB" % (dst.name, dst.stat().st_size / 1e6))
                made.append(dst)
                continue

            t0 = time.time()
            res = encode(src, dst, kind, q)
            if res is None:
                print("     실패:", dst.name)
                continue
            crf, size = res
            made.append(dst)
            print("     %s  %.0fMB -> %.1fMB  crf%d  (%.0f초)" % (
                dst.name, src.stat().st_size / 1e6, size / 1e6, crf, time.time() - t0))
    return made


# ----------------------------------------------------------------------
def report():
    total = 0
    big = []
    for f in OUT.rglob("*"):
        if f.is_file():
            size = f.stat().st_size
            total += size
            if size > GITHUB_FILE_LIMIT:
                big.append((f, size))

    print("\n" + "=" * 62)
    print(" 정적 사이트 완성 -> %s" % OUT)
    print(" 전체 용량 : %.0f MB" % (total / 1e6))
    if big:
        print(" ! 100MB 를 넘는 파일이 있어 깃허브에 올릴 수 없습니다:")
        for f, s in big:
            print("   %-36s %.0f MB" % (f.name, s / 1e6))
        print("   --quality 360p 로 다시 만들어 보세요.")
    else:
        print(" 파일당 100MB 제한 : 통과")
    if total > PAGES_SITE_LIMIT:
        print(" ! 사이트 권장 용량(1GB)을 넘었습니다.")
    else:
        print(" 사이트 1GB 권장 : 통과")
    print("=" * 62)
    print("""
 다음 순서로 올리시면 됩니다.

   cd %s
   git init
   git add docs
   git commit -m "교통 관제탑 배포"
   git branch -M main
   git remote add origin https://github.com/<아이디>/<저장소>.git
   git push -u origin main

 그다음 저장소 Settings > Pages 에서
   Source : Deploy from a branch
   Branch : main  /  폴더 : /docs
 를 고르고 저장하면 몇 분 뒤 주소가 나옵니다.
""" % C.APP_DIR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", default="480p", choices=list(QUALITY))
    ap.add_argument("--skip-video", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    print("=" * 62)
    print(" 정적 사이트 만들기  (화질 %s)" % args.quality)
    print("=" * 62)

    OUT.mkdir(exist_ok=True)
    print("\n[1] 화면 파일")
    build_shell()
    print("\n[2] 분석 데이터")
    build_data()
    print("\n[3] 영상")
    if args.skip_video:
        print("  건너뜀 (--skip-video)")
    else:
        build_media(args.quality, args.force)
    report()


if __name__ == "__main__":
    main()
