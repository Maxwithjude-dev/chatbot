#!/usr/bin/env python3
"""현행 챗봇 원 응답(data/live_raw/) 복원·분류.
- queries.json: [세트, ID, 질문] 순서 (개발용 407 + 블라인드1~4 920 + 블라인드5 240)
- tables.json / rows.txt: 브라우저에서 받은 응답을 중복 제거해 압축 저장 (information, keywordMenu, provideCount, answer)
수집: 2026-10-14 04:00~04:20, GET /web/shp/mik/chatbotQuestion.do?query=… (X-CSRF-TOKEN: 메인 페이지 input[name=_csrf]), 순차 호출
"""
import json, os, csv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data", "live_raw")
A_FALLBACK, A_CLOSED, A_NOTHELD, A_REALTIME, A_PRIVACY, A_REQ = 0, 34, 41, 67, 68, 79


def load():
    T = json.load(open(os.path.join(D, "tables.json"), encoding="utf-8"))
    rows = open(os.path.join(D, "rows.txt"), encoding="utf-8").read().split()
    qs = json.load(open(os.path.join(D, "queries.json"), encoding="utf-8"))
    out = []
    for (s, i, q), r in zip(qs, rows):
        a, b, c, d = r.split(".")
        out.append(dict(세트=s, ID=i, 질문=q, information=T["I"][int(a)], keywordMenu=T["K"][int(b)], provideCount=c, answer=T["A"][int(d)]))
    return out


def code(r):
    """score_live.interpret 가 읽는 분류 코드"""
    info, ans = r["information"], r["answer"]
    if info == "참고 문서 없음": return "NODOC"
    if info and "|" not in info: return ("NOTHELD:" if "보유" in r["answer"] else "RESTRICTED:") + info  # 별도문의·미보유·배달 등 제한 안내
    if info: return info
    if ans.startswith("현재 답변이 어려운"): return "FALLBACK"
    if "개방하고 있지 않은" in ans: return "RESTRICTED:"
    if "보유하고 있지 않습니다" in ans and "실시간" not in ans: return "NOTHELD:"
    if "실시간" in ans: return "REALTIME"
    if "개인정보" in ans: return "PRIVACY"
    if ans.startswith("자료요청"): return "DOC:자료요청"
    return "?" + ans[:20]


if __name__ == "__main__":
    rs = load(); print(len(rs))
