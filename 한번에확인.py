# -*- coding: utf-8 -*-
"""
교통 관제탑 - 한 번에 확인하고 실행

  1) 포트 확인 (맥의 AirPlay 가 5000 번을 쓰는 문제 회피)
  2) 이 컴퓨터의 네트워크 주소를 전부 찾아 인증서에 담고
  3) 방화벽 상태를 확인한 뒤
  4) 서버를 모든 네트워크에 열어 실행하고
  5) 영상 전송까지 확인한 다음
  6) 휴대폰으로 접속할 주소(QR 포함)를 안내합니다.

    python 한번에확인.py            HTTPS (휴대폰 GPS 사용 가능)
    python 한번에확인.py --http     HTTP (노트북에서만 볼 때)
"""

import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import webbrowser

import config as C

PORTS = [5050, 5051, 8443, 8000, 8080]
CERT_DIR = C.APP_DIR / "certs"
CERT = CERT_DIR / "server.crt"
KEY = CERT_DIR / "server.key"


# ----------------------------------------------------------------------
# 네트워크
# ----------------------------------------------------------------------
def port_free(port):
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return False
    except OSError:
        return True


def who_uses(port):
    try:
        out = subprocess.run(["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5).stdout
        lines = [l for l in out.splitlines()[1:] if l.strip()]
        return lines[0].split()[0] if lines else None
    except Exception:
        return None


def primary_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def all_ipv4():
    """이 컴퓨터가 가진 모든 사설망 주소를 찾습니다. (와이파이/유선/핫스팟)"""
    found = []

    def add(ip, label):
        if not ip or ip.startswith(("127.", "169.254.")):
            return
        if not any(ip == f[0] for f in found):
            found.append((ip, label))

    # ifconfig 로 인터페이스 이름까지 얻습니다.
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=6).stdout
        iface = None
        for line in out.splitlines():
            m = re.match(r"^(\w+):", line)
            if m:
                iface = m.group(1)
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
            if m and iface:
                name = {"en0": "와이파이", "en1": "유선/썬더볼트",
                        "bridge100": "핫스팟"}.get(iface, iface)
                add(m.group(1), name)
    except Exception:
        pass

    add(primary_ip(), "기본 경로")
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0], "호스트명")
    except Exception:
        pass

    # 기본 경로로 나가는 주소를 맨 앞으로
    p = primary_ip()
    found.sort(key=lambda f: (f[0] != p,))
    return found


def firewall_state():
    """맥 방화벽이 켜져 있으면 파이썬의 수신 허용 여부를 확인합니다."""
    fw = "/usr/libexec/ApplicationFirewall/socketfilterfw"
    if not os.path.exists(fw):
        return None
    try:
        state = subprocess.run([fw, "--getglobalstate"],
                               capture_output=True, text=True, timeout=6).stdout
        if "disabled" in state.lower():
            return {"on": False}
        block = subprocess.run([fw, "--getblockall"],
                               capture_output=True, text=True, timeout=6).stdout
        return {"on": True, "block_all": "enabled" in block.lower()}
    except Exception:
        return None


# ----------------------------------------------------------------------
# 인증서
# ----------------------------------------------------------------------
def make_cert(ips):
    CERT_DIR.mkdir(exist_ok=True)
    if subprocess.run(["which", "openssl"], capture_output=True).returncode != 0:
        print("  openssl 이 없어 HTTPS 를 쓸 수 없습니다. HTTP 로 실행합니다.")
        return False

    if CERT.exists() and KEY.exists():
        try:
            out = subprocess.run(["openssl", "x509", "-in", str(CERT), "-noout", "-text"],
                                 capture_output=True, text=True, timeout=10).stdout
            if all(ip in out for ip in ips):
                print("  기존 인증서 사용 (%d개 주소 포함)" % len(ips))
                return True
            print("  새 네트워크 주소가 있어 인증서를 다시 만듭니다.")
        except Exception:
            pass

    alt = "\n".join("IP.%d=%s" % (i + 1, ip) for i, ip in enumerate(ips))
    conf = CERT_DIR / "openssl.cnf"
    conf.write_text(
        "[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n"
        "[dn]\nCN=%s\n"
        "[v3]\nsubjectAltName=@alt\nbasicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
        "[alt]\n%s\nIP.%d=127.0.0.1\nDNS.1=localhost\n"
        % (ips[0] if ips else "127.0.0.1", alt, len(ips) + 1),
        encoding="utf-8")

    r = subprocess.run([
        "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
        "-keyout", str(KEY), "-out", str(CERT), "-days", "825",
        "-config", str(conf),
    ], capture_output=True, text=True)

    if r.returncode != 0:
        print("  인증서 생성 실패:", (r.stderr or "").strip()[:200])
        return False
    print("  인증서 준비 완료 (%d개 주소 포함)" % len(ips))
    return True


def get(url, timeout=10, headers=None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.status, r.headers, r.read()


# ----------------------------------------------------------------------
def main():
    use_https = "--http" not in sys.argv

    print("=" * 68)
    print(" 교통 관제탑 - 한 번에 확인")
    print("=" * 68)

    # 1. 포트 ----------------------------------------------------------
    print("\n[1] 포트")
    holder = who_uses(5000)
    if holder:
        print("  5000 번은 '%s' 이(가) 사용 중" % holder, end="")
        print(" (맥 AirPlay - 액세스 거부의 원인)"
              if ("Control" in holder or "AirPlay" in holder) else "")
    port = next((p for p in PORTS if port_free(p)), None)
    if port is None:
        print("  쓸 수 있는 포트가 없습니다.")
        return
    print("  사용할 포트 : %d" % port)

    # 2. 네트워크 주소 --------------------------------------------------
    print("\n[2] 이 컴퓨터의 네트워크 주소")
    addrs = all_ipv4()
    if not addrs:
        print("  사설망 주소를 찾지 못했습니다. 와이파이에 연결되어 있는지 확인해 주세요.")
    for ip, label in addrs:
        print("  %-16s %s" % (ip, label))
    ips = [ip for ip, _ in addrs] or ["127.0.0.1"]

    # 3. 방화벽 --------------------------------------------------------
    print("\n[3] 방화벽")
    fw = firewall_state()
    if fw is None:
        print("  확인할 수 없습니다.")
    elif not fw["on"]:
        print("  꺼져 있음 - 문제 없습니다.")
    else:
        print("  켜져 있습니다.")
        if fw.get("block_all"):
            print("  ! '모든 수신 연결 차단' 이 켜져 있어 휴대폰이 접속할 수 없습니다.")
            print("    시스템 설정 > 네트워크 > 방화벽 > 옵션 에서 꺼 주세요.")
        else:
            print("    처음 실행할 때 '들어오는 네트워크 연결을 허용하시겠습니까?' 창이 뜨면")
            print("    반드시 [허용] 을 눌러 주세요. 거부하면 휴대폰이 접속하지 못합니다.")

    # 4. 인증서 --------------------------------------------------------
    if use_https:
        print("\n[4] HTTPS 인증서 (휴대폰 GPS 용)")
        if not make_cert(ips):
            use_https = False
    else:
        print("\n[4] HTTPS 건너뜀 (--http)")

    scheme = "https" if use_https else "http"
    local = "%s://127.0.0.1:%d" % (scheme, port)

    # 5. 서버 ----------------------------------------------------------
    print("\n[5] 서버 실행")
    env = dict(os.environ, PORT=str(port), BIND_HOST="0.0.0.0")
    if use_https:
        env["USE_HTTPS"] = "1"
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=str(C.APP_DIR), env=env)

    for _ in range(50):
        time.sleep(0.4)
        try:
            get(local + "/api/health", timeout=2)
            break
        except Exception:
            if proc.poll() is not None:
                print("  서버가 곧바로 종료되었습니다. 위 오류를 확인해 주세요.")
                return
    else:
        print("  서버가 응답하지 않습니다.")
        proc.terminate()
        return
    print("  실행됨 (0.0.0.0:%d - 모든 네트워크에 열림)" % port)

    ok = True
    try:
        # 6. 외부 주소로 실제 접속 -------------------------------------
        print("\n[6] 네트워크 주소로 접속 확인")
        reachable = []
        for ip, label in addrs:
            url = "%s://%s:%d" % (scheme, ip, port)
            try:
                get(url + "/api/health", timeout=4)
                print("  가능   %s  (%s)" % (url, label))
                reachable.append(url)
            except Exception as e:
                print("  실패   %s  (%s) - %s" % (url, label, str(e)[:60]))
        if not reachable:
            ok = False
            print("  ! 이 컴퓨터에서조차 외부 주소로 접속되지 않습니다. 방화벽을 확인해 주세요.")

        # 7. 영상 -------------------------------------------------------
        print("\n[7] 영상 전송")
        data = json.loads(get(local + "/api/selftest", timeout=25)[2].decode())
        print("  파일 열기 : %s" % ("정상 (%d개)" % len(data["files"]) if data["ok"] else "문제 있음"))
        if not data["ok"]:
            ok = False
            for row in data["files"]:
                if row["result"] != "정상":
                    print("    - %s/%s : %s" % (row["id"], row["kind"], row["result"]))
        st, hdrs, chunk = get(local + "/media/%s/yolo" % C.DATASETS[0]["id"],
                              headers={"Range": "bytes=0-65535"}, timeout=25)
        codec = ("H.264" if b"avc1" in chunk else
                 "mp4v (변환 필요)" if b"mp4v" in chunk else "확인 못함")
        print("  전송      : %s / %s / %s" % (st, hdrs.get("Content-Type"), codec))

        # 8. 안내 -------------------------------------------------------
        print("\n" + "=" * 68)
        print(" 노트북에서 : %s" % local)
        if reachable:
            print(" 휴대폰에서 : 아래 주소 중 하나를 여세요")
            for url in reachable:
                print("      %s" % url)
            print("")
            print(" 주소 치기 번거로우면 노트북에서 이 페이지를 열고 QR 을 찍으세요")
            print("      %s/connect" % local)
        print("")
        print(" 휴대폰이 접속되지 않으면")
        print("   1. 휴대폰과 노트북이 같은 와이파이인지 (게스트망 아닌지)")
        print("   2. 휴대폰의 VPN / 사설 릴레이가 켜져 있지 않은지")
        print("   3. 방화벽 허용 창에서 [허용] 을 눌렀는지")
        print("   4. 공유기의 '단말 간 통신 차단(AP isolation)' 설정")
        if use_https:
            print("")
            print(" 첫 접속 때 '비공개 연결이 아닙니다' 경고 -> 고급 -> 이동")
        print("=" * 68)
        print("\n종료하려면 Ctrl + C\n")

        try:
            webbrowser.open(local + "/connect")
        except Exception:
            pass
        proc.wait()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("\n확인 중 오류: %s" % e)
    finally:
        if proc.poll() is None:
            proc.terminate()
        print("서버를 종료했습니다.")


if __name__ == "__main__":
    main()
