import sys, csv, collections, time
sys.path.insert(0, "."); import rapidfuzz_stub
import pandas as pd
import matcher
sys.path.insert(0, "../2_claude_v7_rules/proto")
from evaluate import judge, role_flip
from taas_nlu import RESTRICTED_PATTERNS
ROOT = "../2_claude_v7_rules"
kw = pd.read_csv("../taas_chatbot_poc/data/KEYWORD_SET.csv", encoding="utf-8-sig").fillna("")
docs = list(csv.DictReader(open(f"{ROOT}/sources/DOCUMENT_SET.csv", encoding="utf-8-sig")))
restricted = {d["TERTIARY_MENU"] for d in docs if any(p in d["DOCUMENT"] for p in RESTRICTED_PATTERNS)}
ex = pd.DataFrame(columns=["QUESTION", "TERTIARY_MENU", "KEYWORD_MENU"])
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf): M = matcher.SentenceMatcher(kw, ex, None)
print("terms", len(M.terms), "warnings", buf.getvalue().count("[경고]"))

def label(q):
    r = M.match(q)
    if r.status != "answer": return "답변불가", r.status, ""
    menus = [c.menu for c in r.answers]
    if any(m in restricted for m in menus): return "답변불가", "answer(제한)", r.answers[0].stage
    return "+".join(menus[:3]), "answer", r.answers[0].stage

sets = [("개발용", f"{ROOT}/data/eval_dev.csv")] + [(f"블라인드{i}", f"{ROOT}/data/blind/blind{i}_set.csv") for i in range(1, 7)]
TYPES = ["정확 키워드", "띄어쓰기", "오타", "동의어", "구어체", "복수 의도", "범위 밖"]
out = []; summ = []
for name, f in sets:
    rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
    ok = wrong = refuse = flips = 0; by = collections.defaultdict(lambda: [0, 0]); ts = []
    for r in rows:
        a = time.perf_counter(); lab, st, stage = label(r["질문"]); ts.append((time.perf_counter() - a) * 1000)
        j = judge(r["정답메뉴"], lab); by[r["질문유형"]][1] += 1
        if j == "정답": ok += 1; by[r["질문유형"]][0] += 1
        elif lab == "답변불가": refuse += 1
        else: wrong += 1
        flips += role_flip(r["정답메뉴"], lab)
        out.append([name, r["ID"], r["질문"], r["질문유형"], r["정답메뉴"], lab, st, stage, j])
    n = len(rows); ts.sort()
    summ.append([name, n, f"{ok/n:.1%}", f"{wrong/n:.1%}", f"{refuse/n:.1%}", flips, round(sum(ts)/n, 1), round(ts[int(n*.95)], 1)] + [f"{by[t][0]/by[t][1]:.0%}" if by[t][1] else "" for t in TYPES])
    print(f"{name:6} n={n} 정답 {ok/n:.1%} 오안내 {wrong/n:.1%} 안내못함 {refuse/n:.1%} 역할반전 {flips} avg {sum(ts)/n:.1f}ms")
w = csv.writer(open("poc_rows.csv", "w", encoding="utf-8-sig", newline="")); w.writerow(["세트", "ID", "질문", "질문유형", "정답메뉴", "팀원PoC(규칙만)", "상태", "단계", "판정"]); w.writerows(out)
w = csv.writer(open("poc_summary.csv", "w", encoding="utf-8-sig", newline="")); w.writerow(["세트", "n", "정답률", "오안내", "안내못함", "역할반전", "avg_ms", "p95_ms"] + TYPES); w.writerows(summ)
