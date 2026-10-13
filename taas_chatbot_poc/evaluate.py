"""
평가 스크립트 (현행 챗봇 / 개선 챗봇 공통)

평가셋 CSV 컬럼: 질문, 정답메뉴, 질문유형
  - 정답메뉴: TERTIARY_MENU 값, 답변하면 안 되는 질문은 "답변불가"
             복수 의도 질문은 "음주운전|이륜차"처럼 | 로 구분 (모두 안내해야 정답)
  - 질문유형: 쉼표로 여러 개 가능 (예: "동의어,구어체")

실행 예:
  python evaluate.py --url http://127.0.0.1:8000/chat --eval eval_sample.csv --out result_new.csv
  python evaluate.py --url http://현행서버:포트/chat --eval eval_sample.csv --out result_old.csv

현행 챗봇은 응답에 메뉴명이 없어서, 답변 문구를 지식 DB의 DOCUMENT와 대조해 메뉴를 역추적합니다.
"""
import argparse
import time

import numpy as np
import pandas as pd
import requests

from data_loader import load_all

UNANSWERABLE = "답변불가"
FALLBACK_MARKERS = ("참고 문서 없음", "답변이 어려운")


def build_doc_to_menu():
    kn = load_all()["knowledge"]
    pairs = list(zip(kn["DOCUMENT"], kn["TERTIARY_MENU"]))
    pairs.sort(key=lambda p: -len(p[0]))  # 긴 문서부터 대조 ('고령운전자'가 '운전자'보다 먼저)
    return pairs


def doc_to_menu(doc, pairs):
    for text, menu in pairs:
        if text and text in doc:
            return menu
    return ""


def parse_response(resp, pairs):
    """응답 -> (상태, 예측 메뉴 리스트, 후보 메뉴 리스트)"""
    docs = [d for d in resp.get("document", []) if d]
    status = resp.get("status")
    if status is None:  # 현행 챗봇
        valid = [d for d in docs if not any(m in d for m in FALLBACK_MARKERS)]
        status = "answer" if valid else "fallback"
        menus = [m for m in (doc_to_menu(d, pairs) for d in valid) if m]
        return status, menus, menus
    menus = resp.get("tertiary_menu", [])
    cands = [c["menu"] for c in resp.get("candidates", [])]
    return status, menus, cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--out", default="eval_result.csv")
    ap.add_argument("--ip", default="EVAL_TEST", help="로그에서 걸러낼 수 있도록 넣는 식별값")
    args = ap.parse_args()

    df = pd.read_csv(args.eval, encoding="utf-8-sig").fillna("")
    pairs = build_doc_to_menu()
    rows = []

    for r in df.itertuples(index=False):
        t0 = time.perf_counter()
        try:
            res = requests.post(args.url, json={"query": r.질문, "conectrIp": args.ip}, timeout=30)
            res.raise_for_status()
            resp = res.json()
            error = ""
        except Exception as e:
            resp, error = {}, str(e)
        latency = (time.perf_counter() - t0) * 1000

        status, menus, cands = parse_response(resp, pairs) if resp else ("error", [], [])
        top1 = menus[0] if menus else ""
        # 임계값 분석용 (현행 챗봇은 이 키가 없어 빈 값)
        scores = [c.get("score", "") for c in resp.get("candidates", [])] + ["", ""]
        gold = r.정답메뉴
        golds = [g.strip() for g in gold.split("|") if g.strip()]
        answerable = gold != UNANSWERABLE
        if len(golds) > 1:   # 복수 의도: 정답 메뉴를 모두 안내했는지
            hit = set(golds) <= set(menus)
        else:                # 단일 의도: 첫 번째 안내 메뉴가 정답인지
            hit = top1 == gold

        rows.append({
            "질문": r.질문, "정답메뉴": gold, "질문유형": r.질문유형,
            "상태": status, "예측메뉴_top1": top1, "예측메뉴_전체": ",".join(menus),
            "후보_top3": ",".join(cands[:3]),
            "매칭단계": resp.get("match_stage", ""), "점수_top1": scores[0], "점수_top2": scores[1],
            "정답여부": answerable and status == "answer" and hit,
            "오답여부": status == "answer" and not hit,
            "되묻기_top3적중": status == "clarify" and any(g in cands[:3] for g in golds),
            "거절성공": (not answerable) and status != "answer",
            "응답시간_ms": round(latency, 1), "오류": error,
        })

    out = pd.DataFrame(rows)
    out.to_csv(args.out, index=False, encoding="utf-8-sig")  # 엑셀에서 한글 안 깨지게

    # ---------------- 요약 지표 ----------------
    ans = out[out["정답메뉴"] != UNANSWERABLE]
    unans = out[out["정답메뉴"] == UNANSWERABLE]
    answered = out[out["상태"] == "answer"]
    clarified = out[out["상태"] == "clarify"]

    def pct(a, b):
        return f"{(a / b * 100):.1f}% ({a}/{b})" if b else "-"

    print("\n================ 평가 결과 ================")
    print(f"전체 질문           : {len(out)}")
    print(f"Top-1 정확도        : {pct(int(ans['정답여부'].sum()), len(ans))}  (답변 가능 질문 기준)")
    print(f"응답률              : {pct(len(answered), len(out))}")
    print(f"오답률              : {pct(int(answered['오답여부'].sum()), len(answered))}  (답변한 것 중 틀린 비율)")
    print(f"되묻기 비율         : {pct(len(clarified), len(out))}")
    print(f"되묻기 Top-3 적중   : {pct(int(clarified['되묻기_top3적중'].sum()), len(clarified))}")
    print(f"거절 정확도         : {pct(int(unans['거절성공'].sum()), len(unans))}  (답변불가 질문 기준)")
    lat = out["응답시간_ms"]
    print(f"응답시간 평균/P95   : {lat.mean():.0f}ms / {np.percentile(lat, 95):.0f}ms")

    print("\n[질문 유형별 Top-1 정확도]")
    types = sorted({t.strip() for v in ans["질문유형"] for t in str(v).split(",") if t.strip()})
    for t in types:
        sub = ans[ans["질문유형"].str.contains(t, regex=False)]
        print(f"  {t:<10}: {pct(int(sub['정답여부'].sum()), len(sub))}")
    print(f"\n상세 결과 저장: {args.out}")


if __name__ == "__main__":
    main()
