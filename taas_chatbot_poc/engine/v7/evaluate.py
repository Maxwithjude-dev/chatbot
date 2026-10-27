#!/usr/bin/env python3
"""프로토타입 채점. 사용: python3 proto/evaluate.py <eval_csv> [--baseline observation_log.csv] [--out 결과.csv] [--ablation]
채점 기준(엄격): 예측 메뉴 집합 == 정답 메뉴 집합. 복수 의도는 부분 일치를 따로 집계.
역할 반전: 1당↔2당, 운전자↔사상자 계열로 뒤바뀐 경우.
"""
import csv, os, sys, collections, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from taas_nlu import Engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TYPES = ["정확 키워드", "띄어쓰기", "동의어", "오타", "구어체", "복수 의도", "범위 밖"]
ROLE_PAIRS = [("1당노인", "노인"), ("1당노인", "보행노인"), ("2당자전거", "1당자전거"), ("1당연령대", "사상자연령대"),
              ("보행노인", "노인"), ("보행어린이", "어린이")]


def judge(exp, got):
    e, g = set(exp.split("+")), set(got.split("+"))
    if e == g: return "정답"
    if len(e) > 1 and e & g: return "부분정답"
    return "오답"


def role_flip(exp, got):
    e, g = set(exp.split("+")), set(got.split("+"))
    for a, b in ROLE_PAIRS:
        if (a in e and b in g and a not in g) or (b in e and a in g and b not in g):
            if a in ("1당노인", "2당자전거", "1당연령대") or b in ("1당노인", "2당자전거", "1당연령대"):
                return True
    return False


def run(engine, rows):
    res = []
    for r in rows:
        o = engine.analyze(r["질문"])
        res.append((r, o, judge(r["정답메뉴"], o["label"])))
    return res


def summary(res, label=""):
    n = len(res); ok = sum(j == "정답" for _, _, j in res)
    by = collections.defaultdict(lambda: [0, 0])
    for r, o, j in res:
        by[r["질문유형"]][1] += 1; by[r["질문유형"]][0] += j == "정답"
    flips = sum(role_flip(r["정답메뉴"], o["label"]) for r, o, _ in res)
    fp_oos = sum(1 for r, o, j in res if r["정답메뉴"] == "답변불가" and "답변불가" not in o["label"])
    fn_oos = sum(1 for r, o, j in res if r["정답메뉴"] != "답변불가" and o["label"] == "답변불가")
    d = {"label": label, "n": n, "acc": ok / n, "flips": flips, "oos_missed": fp_oos, "false_refusal": fn_oos}
    for t in TYPES:
        a, b = by[t]
        d[t] = (a / b) if b else None
    return d


def fmt(d):
    s = f"{d['label']:<28} 전체 {d['acc']:.1%}  역할반전 {d['flips']}  범위밖놓침 {d['oos_missed']}  잘못된거절 {d['false_refusal']} | "
    return s + "  ".join(f"{t} {d[t]:.0%}" for t in TYPES if d[t] is not None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_csv"); ap.add_argument("--baseline"); ap.add_argument("--out"); ap.add_argument("--ablation", action="store_true")
    ap.add_argument("--sem", type=float, default=0.40); ap.add_argument("--extra-examples"); ap.add_argument("--aug"); ap.add_argument("--margin", type=float, default=0.02)
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.eval_csv, encoding="utf-8-sig")))
    src = os.path.join(ROOT, "sources"); exq = os.path.join(ROOT, "data", "example_questions.csv")
    extra = []
    if a.extra_examples:
        extra = [(r["질문"], r["정답메뉴"]) for r in csv.DictReader(open(a.extra_examples, encoding="utf-8-sig")) if r["정답메뉴"] != "답변불가"]
    if a.baseline:
        base = {r["평가ID"]: r for r in csv.DictReader(open(a.baseline, encoding="utf-8-sig"))}
        bres = [(r, {"label": base[r["ID"]]["챗봇응답메뉴"].replace("/", "+")}, base[r["ID"]]["판정"].replace("부분정답(복수 의도 중 1개)", "부분정답")) for r in rows if r["ID"] in base]
        print(fmt(summary(bres, "현행 챗봇(실측)")))
    full = Engine(src, examples_csv=exq, extra_examples=extra, sem_threshold=a.sem, aug_csv=a.aug, sem_margin=a.margin)
    res = run(full, rows)
    print(fmt(summary(res, "개선안(전체)")))
    if a.ablation:
        for name, kw in [("─ 동의어 사전 제외", dict(use_thesaurus=False)), ("─ 슬롯 규칙 제외", dict(use_slots=False)),
                         ("─ 오타 보정 제외", dict(use_fuzzy=False)), ("─ 유사도 대체 제외", dict(use_semantic=False)),
                         ("─ 업무밖 판정 제외", dict(use_oos=False)), ("─ 복수 의도 제외", dict(multi=False)),
                         ("분할(DP)+사전만", dict(use_thesaurus=False, use_slots=False, use_fuzzy=False, use_semantic=False, use_oos=False))]:
            e = Engine(src, examples_csv=exq, extra_examples=extra, sem_threshold=a.sem, **kw)
            print(fmt(summary(run(e, rows), name)))
    if a.out:
        with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ID", "질문", "질문유형", "정답메뉴", "개선안응답", "판정", "경로", "역할반전", "현행응답", "현행판정", "근거"])
            for r, o, j in res:
                b = base.get(r["ID"]) if a.baseline else None
                tr = o["trace"]
                why = "; ".join(x for x in [
                    "분할:" + ",".join(p for k, p in tr.get("pieces", []) if k == "KW") if tr.get("pieces") else "",
                    "슬롯:" + ",".join(tr["slot"]) if tr.get("slot") else "",
                    "오타:" + ",".join(f"{a_}→{b_}" for a_, b_ in tr["fuzzy"]) if tr.get("fuzzy") else "",
                    "업무밖:" + tr["oos"] if tr.get("oos") else "",
                    "유사도:" + ",".join(f"{m}({s:.2f})" for m, s in tr["semantic"][:2]) if tr.get("semantic") else ""] if x)
                w.writerow([r["ID"], r["질문"], r["질문유형"], r["정답메뉴"], o["label"], j, o["route"],
                            "Y" if role_flip(r["정답메뉴"], o["label"]) else "", b["챗봇응답메뉴"] if b else "", b["판정"] if b else "", why])
