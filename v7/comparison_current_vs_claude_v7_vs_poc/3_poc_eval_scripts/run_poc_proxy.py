"""팀원 PoC 3단계(임베딩)를 이 환경에서 구할 수 없는 KURE-v1 대신 문자 n-gram TF-IDF kNN으로 대체한 '추정' 실행.
   1·2단계(사전·오타)는 PoC 코드 그대로. 3단계만 대체하므로 '규칙만' 결과와의 차이 = 유사도 단계의 상한 추정."""
import sys, csv, collections, io, contextlib
sys.path.insert(0, "."); import rapidfuzz_stub
import pandas as pd, matcher, config
sys.path.insert(0, "../2_claude_v7_rules/proto")
from evaluate import judge, role_flip
from taas_nlu import RESTRICTED_PATTERNS, norm
from sklearn.feature_extraction.text import TfidfVectorizer
ROOT = "../2_claude_v7_rules"
kw = pd.read_csv("../taas_chatbot_poc/data/KEYWORD_SET.csv", encoding="utf-8-sig").fillna("")
docs = list(csv.DictReader(open(f"{ROOT}/sources/DOCUMENT_SET.csv", encoding="utf-8-sig")))
restricted = {d["TERTIARY_MENU"] for d in docs if any(p in d["DOCUMENT"] for p in RESTRICTED_PATTERNS)}
with contextlib.redirect_stdout(io.StringIO()): M = matcher.SentenceMatcher(kw, pd.DataFrame(columns=["QUESTION", "TERTIARY_MENU", "KEYWORD_MENU"]), None)
# 예시 질문: 633 + 생성 2,707 (PoC 설계의 TAAS_CHATBOT_EXAMPLE_QUESTION 역할)
ex = []
for f in (f"{ROOT}/data/example_questions.csv", f"{ROOT}/data/example_questions_aug_v2.csv"):
    for r in csv.DictReader(open(f, encoding="utf-8-sig")):
        if r["메뉴"] != "답변불가": ex.append((norm(r["질문"]), r["메뉴"]))
vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), sublinear_tf=True); X = vec.fit_transform([q for q, _ in ex])
def embed(q, k=3):
    s = (X @ vec.transform([norm(q)]).T).toarray().ravel(); best = {}
    for i in s.argsort()[::-1][:80]:
        m = ex[i][1]
        if m not in best: best[m] = float(s[i])
        if len(best) >= k: break
    return sorted(best.items(), key=lambda x: -x[1])
ANS, CLAR, MARGIN = 0.40, 0.30, 0.03   # TF-IDF 분포에 맞춘 임계 (KURE 0.75/0.60에 해당)
def label(q):
    r = M.match(q)
    if r.status == "answer":
        menus = [c.menu for c in r.answers]
        if any(m in restricted for m in menus): return "답변불가", "answer(제한)"
        return "+".join(menus[:3]), r.answers[0].stage
    e = embed(q)
    if not e: return "답변불가", "fallback"
    top, sc = e[0]; gap = sc - (e[1][1] if len(e) > 1 else 0)
    if sc >= ANS and gap >= MARGIN: return ("답변불가" if top in restricted else top), "embedding(proxy)"
    if sc >= CLAR: return "답변불가", "clarify"
    return "답변불가", "fallback"
sets = [("개발용", f"{ROOT}/data/eval_dev.csv")] + [(f"블라인드{i}", f"{ROOT}/data/blind/blind{i}_set.csv") for i in range(1, 7)]
out = []; summ = []
for name, f in sets:
    rows = list(csv.DictReader(open(f, encoding="utf-8-sig"))); ok = wrong = refuse = 0
    for r in rows:
        lab, st = label(r["질문"]); j = judge(r["정답메뉴"], lab)
        if j == "정답": ok += 1
        elif lab == "답변불가": refuse += 1
        else: wrong += 1
        out.append([name, r["ID"], r["질문"], r["정답메뉴"], lab, st, j])
    n = len(rows); summ.append([name, n, f"{ok/n:.1%}", f"{wrong/n:.1%}", f"{refuse/n:.1%}"])
    print(f"{name:6} 정답 {ok/n:.1%} 오안내 {wrong/n:.1%} 안내못함 {refuse/n:.1%}")
w = csv.writer(open("poc_proxy_rows.csv", "w", encoding="utf-8-sig", newline="")); w.writerow(["세트", "ID", "질문", "정답메뉴", "PoC+유사도프록시", "단계", "판정"]); w.writerows(out)
w = csv.writer(open("poc_proxy_summary.csv", "w", encoding="utf-8-sig", newline="")); w.writerow(["세트", "n", "정답률", "오안내", "안내못함"]); w.writerows(summ)
