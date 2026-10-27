#!/usr/bin/env python3
"""개선 엔진 HTTP 서비스 (표준 라이브러리만 사용, 시연·연동 시험용)

실행:  python3 proto/serve.py --port 8765
호출:  curl -s -X POST localhost:8765/analyze -H 'Content-Type: application/json' -d '{"query":"노인 운전자 사고"}'
응답:  {"label": "1당노인", "menus": ["1당노인"], "route": "슬롯", "answer": "...", "links": [...], "suggest": [], "elapsed_ms": 1.2}

- label    : 채점용 정답 형식 (메뉴, 'A+B', '답변불가')
- route    : 사전 / 슬롯 / 복수(병렬) / 유사도 / 되묻기 / 업무밖 / 업무밖(유사도) / 포괄
- answer   : respond.py 형식의 사용자 안내 문장
- 기존 챗봇 연동 시: 기존 /web/shp/mik/chatbotQuestion.do 앞단에서 이 서비스를 먼저 호출하고,
  route 가 '되묻기'일 때만 기존 엔진 결과를 함께 보여 주는 단계적 전환을 권장
"""
import json, os, sys, time, argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from taas_nlu import Engine
from respond import respond, link

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = Engine(os.path.join(ROOT, "sources"), examples_csv=os.path.join(ROOT, "data", "example_questions.csv"),
                aug_csv=os.path.join(ROOT, "data", "example_questions_aug_v2.csv"))


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        if self.path != "/analyze": return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            q = json.loads(self.rfile.read(n) or b"{}").get("query", "")
        except Exception:
            return self._send(400, {"error": "invalid json"})
        if not isinstance(q, str) or len(q) > 300:
            return self._send(400, {"error": "query must be a string up to 300 chars"})
        t = time.time()
        r = ENGINE.analyze(q)
        ans = respond(ENGINE, q)
        links = [link(ENGINE.docs[m]) for m in r["menus"] if m in ENGINE.docs]
        self._send(200, {"label": r["label"], "menus": r["menus"], "route": r["route"], "answer": ans,
                         "links": [u for u in links if u], "suggest": r["suggest"], "elapsed_ms": round((time.time() - t) * 1000, 1)})

    def log_message(self, *a):  # 질문 원문은 로그에 남기지 않음 (개인정보 보호)
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8765); ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"listening on http://{a.host}:{a.port}/analyze")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
