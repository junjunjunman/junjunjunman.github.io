# -*- coding: utf-8 -*-
"""
교통 관제탑 (Traffic Control Tower)

CCTV 영상에 YOLO 를 적용한 결과 영상, BEV(위에서 본 화면) 영상, 신호 타임라인,
차량별 속도 데이터를 하나의 웹 화면에서 보여줍니다.

실행:
    pip install flask
    python precompute.py     (처음 한 번, 데이터 준비)
    python app.py
    브라우저에서 http://127.0.0.1:5050 접속

한 번에 확인하고 실행하려면:
    python 한번에확인.py
"""

import csv
import json
import mimetypes
import os
import socket

from flask import (Flask, abort, jsonify, render_template, request, send_file,
                   send_from_directory)

import config as C

app = Flask(__name__)
# 화면 파일(css/js)을 고쳤을 때 브라우저가 옛날 것을 쓰지 않도록 캐시를 끕니다.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["TEMPLATES_AUTO_RELOAD"] = True

_cache = {}          # dataset_id -> 미리 계산된 데이터
_signal_cache = {}   # dataset_id -> 신호 타임라인


# ----------------------------------------------------------------------
# 데이터 읽기
# ----------------------------------------------------------------------
def load_dataset(ds_id):
    if ds_id in _cache:
        return _cache[ds_id]
    path = C.CACHE_DIR / (ds_id + ".json")
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _cache[ds_id] = data
    return data


def load_signal(ds_id):
    if ds_id in _signal_cache:
        return _signal_cache[ds_id]

    ds = C.DATASET_BY_ID.get(ds_id)
    if not ds:
        return None
    path = C.paths_for(ds)["signal_csv"]
    if not path.exists():
        return {"columns": [], "intervals": []}

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        cols = [c for c in fields if c not in C.SIGNAL_META_COLUMNS]

        intervals = []
        for row in reader:
            try:
                start = float(row["start_sec"])
                end = float(row["end_sec"])
            except (TypeError, ValueError, KeyError):
                continue
            states = {}
            for c in cols:
                v = (row.get(c) or "RED").strip().upper()
                states[c] = v if v in C.STATE_TEXT else "UNKNOWN"
            intervals.append({
                "start": start,
                "end": end,
                "states": states,
                "confidence": (row.get("confidence") or "").strip(),
                "note": (row.get("note") or "").strip(),
            })

    intervals.sort(key=lambda x: x["start"])
    result = {
        "columns": [
            {"key": c,
             "label": C.SIGNAL_LABELS.get(c, c),
             "kind": "crosswalk" if "crosswalk" in c else "vehicle"}
            for c in cols
        ],
        "intervals": intervals,
        "state_text": C.STATE_TEXT,
    }
    _signal_cache[ds_id] = result
    return result


def read_events(ds):
    """정지선 위반 / 꼬리물기 요약 CSV 를 읽습니다."""
    p = C.paths_for(ds)
    out = {"stopline": [], "tailgate": []}

    def rows(path):
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        except OSError:
            return []

    for r in rows(p["stopline_csv"]):
        try:
            out["stopline"].append({
                "kind": "stopline",
                "id": r.get("ID", ""),
                "sec": float(r.get("start_sec") or 0),
                "end": float(r.get("end_sec") or 0),
                "lane": r.get("lane", ""),
                "signal": r.get("signal", ""),
                "state": r.get("state", ""),
                "x": float(r.get("x") or 0),
                "y": float(r.get("y") or 0),
                "note": r.get("note", ""),
            })
        except ValueError:
            continue

    for r in rows(p["tailgate_csv"]):
        try:
            out["tailgate"].append({
                "kind": "tailgate",
                "id": r.get("ID", ""),
                "sec": float(r.get("start_sec") or 0),
                "end": float(r.get("end_sec") or 0),
                "direction": r.get("direction", ""),
                "state": r.get("state", ""),
                "stay": float(r.get("stay_sec") or 0),
                "slow": float(r.get("slow_sec") or 0),
                "x": float(r.get("x") or 0),
                "y": float(r.get("y") or 0),
                "note": r.get("note", ""),
            })
        except ValueError:
            continue

    out["stopline"].sort(key=lambda e: e["sec"])
    out["tailgate"].sort(key=lambda e: e["sec"])
    return out


def read_predict(ds_id):
    """이동경로 예측 캐시."""
    p = C.CACHE_DIR / ("predict-%s.json" % ds_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


# ----------------------------------------------------------------------
# 영상 스트리밍 (구간 요청 지원 - 되감기/빨리감기용)
# ----------------------------------------------------------------------
def send_video(path):
    """
    영상 파일을 보냅니다.
    구간 요청(Range)은 Flask/Werkzeug 의 conditional=True 가 처리합니다.
    직접 구현하는 것보다 브라우저 호환성이 훨씬 좋습니다.
    """
    if not path.exists():
        app.logger.error("영상 파일이 없습니다: %s", path)
        abort(404)
    if path.stat().st_size == 0:
        app.logger.error("영상 파일이 0바이트입니다: %s", path)
        abort(404)

    # 실제로 열 수 있는지 먼저 확인합니다. (권한 문제를 여기서 잡습니다)
    try:
        with open(path, "rb") as f:
            f.read(16)
    except PermissionError as e:
        app.logger.error("영상 파일 권한 없음: %s (%s)", path, e)
        return jsonify({
            "error": "영상 파일을 읽을 권한이 없습니다.",
            "path": str(path),
            "hint": "터미널에서  chmod -R u+rw '%s'  를 실행해 보세요." % path.parent,
        }), 403
    except OSError as e:
        app.logger.error("영상 파일을 열 수 없습니다: %s (%s)", path, e)
        return jsonify({"error": "영상 파일을 열 수 없습니다.",
                        "path": str(path), "detail": str(e)}), 500

    mime = mimetypes.guess_type(str(path))[0] or "video/mp4"
    resp = send_file(str(path), mimetype=mime, conditional=True)

    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ----------------------------------------------------------------------
# 라우트
# ----------------------------------------------------------------------
def asset_version():
    """css/js 파일이 바뀌면 값이 달라져 브라우저가 새로 받아옵니다."""
    stamp = 0
    for rel in ("static/css/style.css", "static/js/main.js"):
        f = C.APP_DIR / rel
        if f.exists():
            stamp = max(stamp, int(f.stat().st_mtime))
    return stamp


@app.route("/")
def index():
    return render_template("index.html", asset_version=asset_version())


# ---------- 웹앱(PWA) ----------
@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(str(C.APP_DIR / "static"), "manifest.webmanifest",
                               mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    """서비스 워커는 최상위에서 받아야 사이트 전체를 담당할 수 있습니다."""
    resp = send_from_directory(str(C.APP_DIR / "static"), "sw.js",
                               mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ---------- 장소(현장 위치) ----------
@app.route("/api/places")
def api_places():
    places = C.load_places()
    for pid, pl in places.items():
        pl["items"] = [
            {"id": d["id"], "name": d["name"], "desc": d["desc"]}
            for d in C.DATASETS if d.get("place_id") == pid
        ]
    return jsonify({
        "places": list(places.values()),
        "default_radius": 150,
    })


@app.route("/api/places/<place_id>", methods=["POST"])
def api_save_place(place_id):
    body = request.get_json(silent=True) or {}
    try:
        lat = float(body["lat"])
        lon = float(body["lon"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "lat, lon 값이 필요합니다."}), 400
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return jsonify({"error": "위경도 범위를 벗어났습니다."}), 400

    radius = body.get("radius_m")
    try:
        radius = float(radius) if radius is not None else None
    except (TypeError, ValueError):
        radius = None
    if radius is not None and not (20 <= radius <= 2000):
        return jsonify({"error": "반경은 20~2000m 사이여야 합니다."}), 400

    try:
        saved = C.save_place(place_id, lat, lon, radius)
    except KeyError:
        abort(404)
    app.logger.info("장소 좌표 저장: %s -> %.6f, %.6f", place_id, lat, lon)
    return jsonify({"ok": True, "place": saved})


@app.route("/api/nearest")
def api_nearest():
    """위경도를 주면 가장 가까운 장소와 거리를 돌려줍니다. (확인용)"""
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "lat, lon 쿼리가 필요합니다."}), 400

    rows = []
    for pl in C.load_places().values():
        d = C.distance_m(lat, lon, pl["lat"], pl["lon"])
        rows.append({"id": pl["id"], "name": pl["name"],
                     "distance_m": round(d, 1),
                     "inside": d <= pl["radius_m"],
                     "videos": pl["videos"]})
    rows.sort(key=lambda r: r["distance_m"])
    return jsonify({"nearest": rows[0] if rows else None, "places": rows})


@app.route("/api/videos")
def api_videos():
    """선택할 수 있는 영상 목록."""
    items = []
    for ds in C.DATASETS:
        p = C.paths_for(ds)
        cached = (C.CACHE_DIR / (ds["id"] + ".json")).exists()
        data = load_dataset(ds["id"]) if cached else None
        items.append({
            "id": ds["id"],
            "place_id": ds.get("place_id"),
            "web_ready": p["web_yolo"].exists(),
            "name": ds["name"],
            "place": ds["place"],
            "desc": ds["desc"],
            "speed_limit": ds["speed_limit"],
            "ready": bool(cached and p["yolo_video"].exists()),
            "has_yolo": p["yolo_video"].exists(),
            "has_bev": p["bev_video"].exists(),
            "duration": data["duration"] if data else 0,
            "summary": data["summary"] if data else None,
            "has_twin": C.playable(ds, "twin").exists(),
            "has_twin_spot": C.playable(ds, "twin_spot").exists(),
            "has_predict": (C.CACHE_DIR / ("predict-%s.json" % ds["id"])).exists(),
        })
    return jsonify({
        "videos": items,
        "weights": str(C.WEIGHTS_PATH),
        "weights_ok": C.WEIGHTS_PATH.exists(),
    })


@app.route("/api/video/<ds_id>")
def api_video(ds_id):
    """선택한 영상의 전체 분석 데이터."""
    ds = C.DATASET_BY_ID.get(ds_id)
    if not ds:
        abort(404)
    data = load_dataset(ds_id)
    if not data:
        return jsonify({
            "error": "데이터가 아직 준비되지 않았습니다. "
                     "터미널에서 python precompute.py 를 먼저 실행해 주세요."
        }), 503

    p = C.paths_for(ds)
    payload = dict(data)
    payload["desc"] = ds["desc"]
    payload["signal"] = load_signal(ds_id)
    payload["has_bev"] = p["bev_video"].exists() or p["web_bev"].exists()
    payload["web_ready"] = p["web_yolo"].exists()
    payload["place"] = C.load_places().get(ds.get("place_id"))
    payload["has_twin"] = C.playable(ds, "twin").exists()
    payload["has_twin_spot"] = C.playable(ds, "twin_spot").exists()
    payload["events"] = read_events(ds)
    pred = read_predict(ds_id)
    payload["predict"] = {
        "available": pred is not None,
        "step": pred["step"] if pred else 0,
        "points": pred["points"] if pred else 0,
        "horizon_frames": pred["horizon_frames"] if pred else 0,
        "count": sum(len(v) for v in pred["preds"].values()) if pred else 0,
    }
    payload["weights"] = C.WEIGHTS_PATH.name
    return jsonify(payload)


@app.route("/api/signal/<ds_id>")
def api_signal(ds_id):
    if ds_id not in C.DATASET_BY_ID:
        abort(404)
    return jsonify(load_signal(ds_id))


@app.route("/media/<ds_id>/yolo")
def media_yolo(ds_id):
    ds = C.DATASET_BY_ID.get(ds_id)
    if not ds:
        abort(404)
    return send_video(C.playable(ds, "yolo"))


@app.route("/media/<ds_id>/bev")
def media_bev(ds_id):
    ds = C.DATASET_BY_ID.get(ds_id)
    if not ds:
        abort(404)
    return send_video(C.playable(ds, "bev"))


@app.route("/media/<ds_id>/twin")
def media_twin(ds_id):
    ds = C.DATASET_BY_ID.get(ds_id)
    if not ds:
        abort(404)
    return send_video(C.playable(ds, "twin"))


@app.route("/media/<ds_id>/twin_spot")
def media_twin_spot(ds_id):
    ds = C.DATASET_BY_ID.get(ds_id)
    if not ds:
        abort(404)
    return send_video(C.playable(ds, "twin_spot"))


@app.route("/api/predict/<ds_id>")
def api_predict(ds_id):
    if ds_id not in C.DATASET_BY_ID:
        abort(404)
    pred = read_predict(ds_id)
    if pred is None:
        return jsonify({"error": "예측 데이터가 없습니다. "
                                 "python precompute_predict.py 를 실행하세요."}), 404
    return jsonify(pred)


@app.route("/api/media-info/<ds_id>")
def api_media_info(ds_id):
    """어떤 파일을 어떤 코덱으로 보내고 있는지 확인용."""
    ds = C.DATASET_BY_ID.get(ds_id)
    if not ds:
        abort(404)
    out = {}
    for kind in ("yolo", "bev"):
        p = C.playable(ds, kind)
        info = {"path": str(p), "exists": p.exists()}
        if p.exists():
            info["size"] = p.stat().st_size
            info["readable"] = os.access(str(p), os.R_OK)
            with open(p, "rb") as f:
                head = f.read(4096)
            info["codec"] = ("avc1" if b"avc1" in head else
                             "mp4v" if b"mp4v" in head else "?")
            info["first_box"] = ("moov" if b"moov" in head[:64] else "mdat/기타")
        out[kind] = info
    return jsonify(out)


TEST_PAGE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>영상 재생 테스트</title>
<style>
 body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:0;padding:32px;
      background:#fff;color:#122234;line-height:1.6}
 h1{font-size:22px;margin:0 0 4px} p{margin:4px 0 20px;color:#5C6B7A;font-size:14px}
 video{width:100%;max-width:900px;background:#000;display:block}
 .box{border:1px solid #E3EAF1;border-radius:10px;padding:16px;margin-bottom:20px}
 .log{font-family:ui-monospace,Menlo,monospace;font-size:12px;background:#F2F6F9;
      border-radius:6px;padding:12px;white-space:pre-wrap;color:#122234}
 a{color:#1C68AE} ul{font-size:14px;padding-left:20px}
</style></head><body>
<h1>영상 재생 테스트</h1>
<p>이 페이지에는 CSS 겹침도, 자바스크립트 제어도 없습니다. 브라우저 기본 재생기만 있습니다.</p>

<div class="box">
  <video id="v" controls preload="auto" src="/media/__ID__/yolo"></video>
</div>

<div class="box">
  <strong style="font-size:14px">상태</strong>
  <div class="log" id="log">기다리는 중…</div>
</div>

<div class="box">
  <strong style="font-size:14px">직접 열어보기</strong>
  <ul>
    <li><a href="/media/__ID__/yolo">차량 인식 영상 원본 주소</a> (브라우저가 단독으로 열 수 있는지 확인)</li>
    <li><a href="/api/media-info/__ID__">서버가 보내는 파일 정보</a></li>
  </ul>
</div>

<script>
var v=document.getElementById('v'), log=document.getElementById('log'), lines=[];
function put(t){ lines.push(t); log.textContent=lines.slice(-14).join('\n'); }
['loadstart','loadedmetadata','loadeddata','canplay','playing','error','stalled','suspend']
  .forEach(function(e){ v.addEventListener(e, function(){
    put(e + '  | readyState=' + v.readyState + ' networkState=' + v.networkState +
        ' 크기=' + v.videoWidth + 'x' + v.videoHeight);
    if(e==='error' && v.error) put('  !! error code=' + v.error.code + ' ' + (v.error.message||''));
  }); });
setInterval(function(){
  var r=v.getBoundingClientRect();
  document.title = '화면크기 ' + Math.round(r.width) + 'x' + Math.round(r.height);
}, 1000);
</script>
</body></html>"""


CONNECT_PAGE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>휴대폰으로 접속하기</title>
<style>
 body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:0;padding:40px 24px;
      background:#F5F8FB;color:#122234;line-height:1.6}
 .wrap{max-width:560px;margin:0 auto}
 h1{font-size:24px;margin:0 0 6px;letter-spacing:-.03em}
 p.lead{margin:0 0 28px;color:#5C6B7A;font-size:15px}
 .card{background:#fff;border:1px solid #E3EAF1;border-radius:14px;padding:24px;margin-bottom:16px}
 .qr{display:flex;justify-content:center;padding:8px 0 16px}
 .url{font-family:ui-monospace,Menlo,monospace;font-size:15px;word-break:break-all;
      background:#F2F6F9;border-radius:8px;padding:12px 14px;text-align:center;color:#122234}
 .label{font-size:12px;color:#7C8B99;letter-spacing:.08em;text-transform:uppercase;
        font-weight:600;margin-bottom:10px}
 ol{font-size:14px;color:#5C6B7A;padding-left:20px;margin:0}
 ol li{margin-bottom:8px}
 .warn{background:#FDF2EA;border-color:#F3D5BE}
 .warn b{color:#CD5A11}
</style></head><body><div class="wrap">
<h1>휴대폰으로 접속하기</h1>
<p class="lead">아래 QR 을 휴대폰 카메라로 찍으면 바로 열립니다.</p>
<div id="cards"></div>
<div class="card warn">
  <b>접속이 안 될 때</b>
  <ol style="margin-top:10px">
    <li>휴대폰과 이 컴퓨터가 같은 와이파이인지 (게스트망은 서로 통신이 막혀 있습니다)</li>
    <li>휴대폰의 VPN, 아이폰의 '비공개 릴레이' 끄기</li>
    <li>맥 방화벽이 처음 물어볼 때 [허용] 을 눌렀는지</li>
    <li>공유기의 '단말 간 통신 차단' 설정 끄기</li>
    <li>'비공개 연결이 아닙니다' 경고는 정상입니다. 고급 → 이동</li>
  </ol>
</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<script>
var URLS = __URLS__;
var box = document.getElementById('cards');
if (!URLS.length) {
  box.innerHTML = '<div class="card">네트워크 주소를 찾지 못했습니다. 와이파이 연결을 확인해 주세요.</div>';
}
URLS.forEach(function(item, i){
  var card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = '<div class="label">' + item.label + '</div>' +
                   '<div class="qr" id="qr' + i + '"></div>' +
                   '<div class="url">' + item.url + '</div>';
  box.appendChild(card);
  try {
    new QRCode(document.getElementById('qr' + i),
               { text: item.url, width: 200, height: 200,
                 colorDark: '#0B1B2B', colorLight: '#ffffff' });
  } catch (e) {
    document.getElementById('qr' + i).textContent = 'QR 을 만들지 못했습니다. 주소를 직접 입력해 주세요.';
  }
});
</script>
</body></html>"""


def lan_addresses():
    """서버가 실제로 열려 있는 이 컴퓨터의 사설망 주소들."""
    import re as _re
    import subprocess as _sp

    found = []

    def add(ip, label):
        if not ip or ip.startswith(("127.", "169.254.")):
            return
        if not any(ip == f[0] for f in found):
            found.append((ip, label))

    try:
        out = _sp.run(["ifconfig"], capture_output=True, text=True, timeout=6).stdout
        iface = None
        for line in out.splitlines():
            m = _re.match(r"^(\w+):", line)
            if m:
                iface = m.group(1)
            m = _re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
            if m and iface:
                add(m.group(1), {"en0": "와이파이", "en1": "유선",
                                 "bridge100": "핫스팟"}.get(iface, iface))
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        add(s.getsockname()[0], "기본 경로")
        s.close()
    except Exception:
        pass
    return found


@app.route("/connect")
def connect_page():
    scheme = "https" if request.environ.get("wsgi.url_scheme") == "https" else "http"
    port = request.host.split(":")[-1] if ":" in request.host else "80"
    urls = [{"label": label, "url": "%s://%s:%s" % (scheme, ip, port)}
            for ip, label in lan_addresses()]
    return CONNECT_PAGE.replace("__URLS__", json.dumps(urls, ensure_ascii=False))


@app.route("/test")
def test_page():
    return TEST_PAGE.replace("__ID__", C.DATASETS[0]["id"])


@app.route("/api/selftest")
def api_selftest():
    """서버 프로세스가 실제로 각 영상 파일을 열 수 있는지 확인합니다."""
    rows = []
    for ds in C.DATASETS:
        for kind in ("yolo", "bev"):
            p = C.playable(ds, kind)
            row = {"id": ds["id"], "kind": kind, "path": str(p)}
            if not p.exists():
                row["result"] = "파일 없음"
            else:
                try:
                    with open(p, "rb") as f:
                        head = f.read(4096)
                    row["result"] = "정상"
                    row["size"] = p.stat().st_size
                    row["codec"] = ("avc1" if b"avc1" in head else
                                    "mp4v" if b"mp4v" in head else "?")
                except PermissionError as e:
                    row["result"] = "권한 없음: %s" % e
                except OSError as e:
                    row["result"] = "열기 실패: %s" % e
            rows.append(row)
    bad = [r for r in rows if r["result"] != "정상"]
    return jsonify({"ok": not bad, "problems": len(bad), "files": rows})


@app.route("/api/health")
def api_health():
    ready = sum(1 for d in C.DATASETS
                if (C.CACHE_DIR / (d["id"] + ".json")).exists())
    web = sum(1 for d in C.DATASETS if C.paths_for(d)["web_yolo"].exists())
    return jsonify({
        "ok": True,
        "web_ready": web,
        "base_dir": str(C.BASE_DIR),
        "datasets": len(C.DATASETS),
        "ready": ready,
        "weights_ok": C.WEIGHTS_PATH.exists(),
    })


if __name__ == "__main__":
    print("=" * 62)
    print(" 교통 관제탑 서버를 시작합니다")
    print(" 데이터 폴더 : %s" % C.BASE_DIR)
    print(" 가중치 파일 : %s (%s)" % (
        C.WEIGHTS_PATH.name, "확인됨" if C.WEIGHTS_PATH.exists() else "없음"))
    ready = sum(1 for d in C.DATASETS
                if (C.CACHE_DIR / (d["id"] + ".json")).exists())
    print(" 준비된 영상 : %d / %d" % (ready, len(C.DATASETS)))
    web = sum(1 for d in C.DATASETS if C.paths_for(d)["web_yolo"].exists())
    print(" 웹 변환본  : %d / %d" % (web, len(C.DATASETS)))
    if ready == 0:
        print(" ! 먼저 python precompute.py 를 실행해 데이터를 준비하세요.")
    if web == 0:
        print(" ! 원본 영상은 mp4v 코덱이라 브라우저에서 재생되지 않습니다.")
        print(" ! python transcode.py 를 실행해 H.264 로 변환하세요.")
    port = int(os.environ.get("PORT", 5050))
    print(" 주소        : http://127.0.0.1:%d" % port)
    if port == 5000:
        print(" ! 맥에서 5000번은 AirPlay 가 쓰는 경우가 많습니다(액세스 거부 원인).")
    print("=" * 62)
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    ssl_ctx = None
    if os.environ.get("USE_HTTPS") == "1":
        cert = C.APP_DIR / "certs" / "server.crt"
        key = C.APP_DIR / "certs" / "server.key"
        if cert.exists() and key.exists():
            ssl_ctx = (str(cert), str(key))
            print(" HTTPS      : 켜짐 (자체 서명 인증서)")
        else:
            print(" ! 인증서가 없어 HTTP 로 실행합니다. python 한번에확인.py 를 쓰세요.")
    app.run(host=host, port=port, debug=False, threaded=True, ssl_context=ssl_ctx)
