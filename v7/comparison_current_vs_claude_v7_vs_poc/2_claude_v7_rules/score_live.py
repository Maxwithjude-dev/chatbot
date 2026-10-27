#!/usr/bin/env python3
"""현행 챗봇 실측 응답(TSV: ID<TAB>응답분류)을 평가셋과 대조해 채점. evaluate.py와 같은 기준.
사용: python3 proto/score_live.py <eval_csv> <raw_tsv> [--out 결과.csv]
"""
import csv, os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate import judge, summary, fmt, role_flip

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
docs = list(csv.DictReader(open(os.path.join(ROOT, "sources", "DOCUMENT_SET.csv"), encoding="utf-8-sig")))
info2m = {}
for d in docs:
    info2m.setdefault(d["INFORMATION"], set()).add(d["TERTIARY_MENU"])


def interpret(raw):
    if raw in ("FALLBACK", "NODOC", "PRIVACY", "REALTIME", "ERR") or raw.startswith(("RESTRICTED", "NOTHELD")):
        return "답변불가"
    if raw.startswith("DOC:"):
        hit = {d["TERTIARY_MENU"] for d in docs if d["DOCUMENT"].startswith(raw[4:].strip())}
        return "+".join(sorted(hit)) if hit else "?" + raw
    if raw in info2m:
        return "+".join(sorted(info2m[raw]))
    head = raw.split("|")[0]
    hit = {d["TERTIARY_MENU"] for d in docs if d["INFORMATION"].split("|")[0] == head}
    return "+".join(sorted(hit)) if hit else "?" + raw


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("eval_csv"); ap.add_argument("raw_tsv"); ap.add_argument("--out")
    a = ap.parse_args()
    rows = {r["ID"]: r for r in csv.DictReader(open(a.eval_csv, encoding="utf-8-sig"))}
    res, unk = [], []
    for line in open(a.raw_tsv, encoding="utf-8"):
        if not line.strip(): continue
        i, raw = line.rstrip("\n").split("\t", 1)
        got = interpret(raw)
        if got.startswith("?"): unk.append((i, raw))
        # 같은 안내 문구를 공유하는 메뉴(지역 포털 4개 등)는 정답 메뉴가 그 안에 있으면 정답 처리
        exp = rows[i]["정답메뉴"]
        if "+" in got and "+" not in exp and exp in got.split("+") and raw in info2m:
            got = exp
        res.append((rows[i], {"label": got}, judge(exp, got)))
    print(fmt(summary(res, "현행 챗봇(실측)")))
    if unk: print("매핑 실패:", unk)
    if a.out:
        with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["ID", "질문", "질문유형", "정답메뉴", "현행응답", "판정"])
            for r, o, j in res: w.writerow([r["ID"], r["질문"], r["질문유형"], r["정답메뉴"], o["label"], j])
