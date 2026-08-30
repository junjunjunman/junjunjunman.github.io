# -*- coding: utf-8 -*-
"""
교통 관제탑 - 웹 재생용 영상 변환

final.py 가 만든 결과 영상은 코덱이 MPEG-4 Part 2(fourcc `mp4v`) 입니다.
이 코덱은 크롬·엣지·파이어폭스의 <video> 태그가 재생하지 못합니다.
(HTML5 비디오는 H.264 / VP9 / AV1 만 지원합니다.)

이 스크립트는 각 영상을 H.264 로 다시 인코딩해 web_media/ 폴더에 넣습니다.
용량도 크게 줄어들고(1.8GB -> 100MB 안팎), moov 를 앞으로 옮겨(faststart)
브라우저가 바로 재생을 시작할 수 있게 합니다.

사용법:
    python transcode.py              # 아직 변환 안 된 것만
    python transcode.py --force      # 전부 다시 변환
    python transcode.py walkerhill1  # 특정 지점만

ffmpeg 이 있으면 ffmpeg 을 쓰고(빠르고 화질/용량이 좋습니다),
없으면 OpenCV 로 대신 변환합니다.
    macOS:  brew install ffmpeg
"""

import shutil
import subprocess
import sys
import time

import config as C

CRF = "24"          # 낮을수록 고화질·큰 용량 (18~28 권장)
PRESET = "veryfast"


def has_ffmpeg():
    return shutil.which("ffmpeg") is not None


def convert_ffmpeg(src, dst):
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-c:v", "libx264", "-preset", PRESET, "-crf", CRF,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
        str(dst),
    ]
    r = subprocess.run(cmd)
    return r.returncode == 0


def convert_opencv(src, dst):
    """ffmpeg 이 없을 때의 대비책. 느리지만 추가 설치가 필요 없습니다."""
    import cv2
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        return False
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"avc1"), fps, (w, h))
    if not out.isOpened():
        cap.release()
        return False
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        out.write(frame)
    cap.release()
    out.release()
    return dst.exists() and dst.stat().st_size > 0


def convert(src, dst, use_ffmpeg):
    """중간에 멈춰도 반쪽짜리 파일이 남지 않도록 임시 파일에 쓰고 마지막에 이름을 바꿉니다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part.mp4")
    if tmp.exists():
        tmp.unlink()
    t0 = time.time()
    try:
        ok = convert_ffmpeg(src, tmp) if use_ffmpeg else convert_opencv(src, tmp)
    except KeyboardInterrupt:
        if tmp.exists():
            tmp.unlink()
        raise
    if not ok or not tmp.exists() or tmp.stat().st_size == 0:
        if tmp.exists():
            tmp.unlink()
        print("     실패: %s" % src.name)
        return False
    tmp.replace(dst)
    print("     %s  %.0fMB -> %.0fMB  (%.0f초)" % (
        dst.name, src.stat().st_size / 1e6, dst.stat().st_size / 1e6,
        time.time() - t0))
    return True


def main():
    args = list(sys.argv[1:])
    force = "--force" in args
    args = [a for a in args if not a.startswith("--")]

    targets = C.DATASETS
    if args:
        targets = [d for d in C.DATASETS if d["id"] in args]
        if not targets:
            print("그런 이름의 지점이 없습니다:", ", ".join(args))
            return

    use_ffmpeg = has_ffmpeg()
    print("=" * 62)
    print(" 웹 재생용 H.264 변환 (%d개 지점)" % len(targets))
    print(" 변환 도구 : %s" % ("ffmpeg" if use_ffmpeg else "OpenCV (ffmpeg 미설치)"))
    if not use_ffmpeg:
        print(" 팁: brew install ffmpeg 을 하면 훨씬 빠르고 용량도 작아집니다.")
    print(" 저장 위치 : %s" % C.WEB_MEDIA_DIR)
    print("=" * 62)

    # 이전에 중간에 멈춰서 남은 임시 파일을 정리합니다.
    if C.WEB_MEDIA_DIR.exists():
        for junk in C.WEB_MEDIA_DIR.glob("*.part.mp4"):
            try:
                junk.unlink()
                print(" 임시 파일 정리:", junk.name)
            except OSError:
                pass

    done = skipped = failed = 0
    for ds in targets:
        p = C.paths_for(ds)
        print("\n> %s" % ds["name"])
        for src_key, dst_key in (("yolo_video", "web_yolo"), ("bev_video", "web_bev")):
            src, dst = p[src_key], p[dst_key]
            if not src.exists():
                print("     원본 없음:", src.name)
                continue
            if dst.exists() and dst.stat().st_size > 0 and not force:
                print("     건너뜀 (이미 있음):", dst.name)
                skipped += 1
                continue
            if convert(src, dst, use_ffmpeg):
                done += 1
            else:
                failed += 1

    print("\n변환 %d개 / 건너뜀 %d개 / 실패 %d개" % (done, skipped, failed))
    print("이제 python app.py 를 실행하면 브라우저에서 영상이 재생됩니다.")


if __name__ == "__main__":
    main()
