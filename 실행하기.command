#!/bin/bash
# 더블클릭하면 관제탑 서버가 켜지고 브라우저가 열립니다.
cd "$(dirname "$0")" || exit 1

if ! python3 -c "import flask" 2>/dev/null; then
  echo "Flask 를 설치합니다..."
  python3 -m pip install flask
fi

if [ ! -f cache/olympicpark1.json ]; then
  echo "데이터를 준비합니다. 잠시만 기다려 주세요..."
  python3 precompute.py
fi

if [ ! -f web_media/olympicpark1_yolo.mp4 ]; then
  echo "웹 재생용 영상을 변환합니다. 시간이 걸릴 수 있습니다..."
  python3 transcode.py
fi

python3 한번에확인.py
