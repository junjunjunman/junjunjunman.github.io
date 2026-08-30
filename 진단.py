# -*- coding: utf-8 -*-
"""
교통 관제탑 - 문제 진단

영상이 브라우저에서 안 나올 때 원인을 찾아 줍니다.

    python 진단.py
"""

import json
import struct
import sys
import urllib.error
import urllib.request

import config as C

PORT = int(__import__("os").environ.get("PORT", 5050))
BASE = "http://127.0.0.1:%d" % PORT

OK = "  [정상] "
NG = "  [문제] "
IN = "  [안내] "


def read_codec(path):
    """mp4 상자 구조를 따라가 실제 영상 코덱(fourcc)을 읽습니다."""
    try:
        size = path.stat().st_size
        f = open(path, "rb")
    except OSError:
        return None

    def walk(start, end, want, depth=0):
        pos = start
        while pos < end - 8 and depth < 8:
            f.seek(pos)
            head = f.read(8)
            if len(head) < 8:
                return None
            box = struct.unpack(">I", head[:4])[0]
            typ = head[4:8]
            body = pos + 8
            if box == 1:
                box = struct.unpack(">Q", f.read(8))[0]
                body += 8
            if box <= 0:
                return None
            if typ == want:
                return (body, pos + box)
            if typ in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                hit = walk(body, pos + box, want, depth + 1)
                if hit:
                    return hit
            pos += box
        return None

    hit = walk(0, size, b"stsd")
    if not hit:
        f.close()
        return None
    f.seek(hit[0] + 8)          # version/flags(4) + entry_count(4)
    entry = f.read(8)
    f.close()
    if len(entry) < 8:
        return None
    return entry[4:8].decode("latin1", "replace")


def first_box(path):
    """moov 가 앞에 있는지(faststart) 확인합니다."""
    try:
        size = path.stat().st_size
        f = open(path, "rb")
    except OSError:
        return None
    pos = 0
    try:
        while pos < size:
            f.seek(pos)
            head = f.read(8)
            if len(head) < 8:
                break
            box = struct.unpack(">I", head[:4])[0]
            typ = head[4:8].decode("latin1", "replace")
            if typ in ("moov", "mdat"):
                return typ
            if box == 1:
                box = struct.unpack(">Q", f.read(8))[0]
            if box <= 0:
                break
            pos += box
    finally:
        f.close()
    return None


def check_files():
    print("\n[1] 파일 확인")
    problems = 0
    for ds in C.DATASETS:
        p = C.paths_for(ds)
        served_y = C.playable(ds, "yolo")
        served_b = C.playable(ds, "bev")
        line = "  %-18s" % ds["id"]

        bad = []
        for label, path in (("차량 인식", served_y), ("BEV", served_b)):
            if not path.exists():
                bad.append("%s 영상 없음" % label)
                continue
            if path.stat().st_size == 0:
                bad.append("%s 파일이 0바이트" % label)
                continue
            codec = read_codec(path)
            if codec != "avc1":
                bad.append("%s 코덱 %s (브라우저 재생 불가)" % (label, codec))

        if bad:
            problems += 1
            print(line, "X", " / ".join(bad))
        else:
            print(line, "O  H.264 변환본 사용 중 (%s, %s)" % (
                first_box(served_y), first_box(served_b)))
    return problems


def check_server():
    print("\n[2] 실행 중인 서버 확인")
    try:
        with urllib.request.urlopen(BASE + "/api/health", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError:
        print(IN + "서버가 켜져 있지 않습니다. (%s)" % BASE)
        print("        -> python 한번에확인.py 를 실행하면 서버 실행부터 확인까지 한 번에 됩니다.")
        print("           이 진단을 다시 실행하면 전송 단계까지 확인할 수 있습니다.")
        return None
    except Exception as e:
        print(NG + "서버 응답을 읽지 못했습니다: %s" % e)
        return None

    if "web_ready" not in data:
        print(NG + "실행 중인 서버가 예전 코드입니다.")
        print("        -> 터미널에서 Ctrl+C 로 서버를 끄고 python app.py 로 다시 켜세요.")
        print("           (Flask 는 코드를 고쳐도 자동으로 다시 읽지 않습니다.)")
        return False

    print(OK + "서버가 최신 코드로 실행 중입니다. 변환본 %d / %d 지점 인식."
          % (data.get("web_ready", 0), data.get("datasets", 0)))
    return True


def check_stream():
    print("\n[3] 영상 전송 확인")
    ds = C.DATASETS[0]
    url = BASE + "/media/%s/yolo" % ds["id"]
    req = urllib.request.Request(url, headers={"Range": "bytes=0-2047"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
            ctype = r.headers.get("Content-Type")
            crange = r.headers.get("Content-Range")
            head = r.read(2048)
    except urllib.error.URLError:
        print(IN + "서버가 꺼져 있어 건너뜁니다.")
        return
    except Exception as e:
        print(NG + "요청 실패: %s" % e)
        return

    print("  응답 %s / %s / %s" % (status, ctype, crange))
    if status != 206:
        print(NG + "구간 요청(206)이 동작하지 않습니다. 되감기가 안 될 수 있습니다.")
    if b"ftyp" not in head[:16]:
        print(NG + "mp4 헤더가 보이지 않습니다. 잘못된 파일을 보내고 있습니다.")
        return
    if b"avc1" in head:
        print(OK + "서버가 H.264(avc1) 영상을 보내고 있습니다.")
    elif b"mp4v" in head:
        print(NG + "서버가 아직 원본(mp4v)을 보내고 있습니다.")
        print("        -> app.py 를 껐다 다시 켜세요.")
    else:
        print(IN + "코덱을 앞부분에서 확인하지 못했습니다(정상일 수 있음).")


def check_selftest():
    print("\n[4] 서버가 파일을 실제로 열 수 있는지")
    try:
        with urllib.request.urlopen(BASE + "/api/selftest", timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError:
        print(IN + "서버가 꺼져 있어 건너뜁니다.")
        return
    except Exception as e:
        print(NG + "확인 실패: %s" % e)
        return

    if data.get("ok"):
        print(OK + "%d개 파일 모두 정상적으로 열립니다." % len(data["files"]))
        return
    for row in data["files"]:
        if row["result"] != "정상":
            print(NG + "%s / %s -> %s" % (row["id"], row["kind"], row["result"]))
            print("        ", row["path"])


def main():
    print("=" * 62)
    print(" 교통 관제탑 진단")
    print("=" * 62)
    print("\n[0] 경로")
    print("  데이터 폴더 :", C.BASE_DIR)
    print("  변환본 폴더 :", C.WEB_MEDIA_DIR,
          "(있음)" if C.WEB_MEDIA_DIR.exists() else "(없음)")

    problems = check_files()
    alive = check_server()
    if alive is not None:
        check_stream()
        check_selftest()

    print("\n" + "=" * 62)
    if problems:
        print(" 할 일 : python transcode.py 를 실행해 영상을 변환하세요.")
    elif alive is False:
        print(" 할 일 : 서버를 껐다 켜세요.  Ctrl+C  ->  python app.py")
    elif alive is None:
        print(" 할 일 : python app.py 로 서버를 켜세요.")
    else:
        print(" 파일과 서버 모두 정상입니다.")
        print(" 그래도 안 보이면 브라우저에서 강제 새로고침을 해 보세요.")
        print("   맥 : Command + Shift + R   /   윈도우 : Ctrl + Shift + R")
    print("=" * 62)


if __name__ == "__main__":
    main()
