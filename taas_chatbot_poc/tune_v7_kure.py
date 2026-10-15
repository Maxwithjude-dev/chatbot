"""
v7+KURE 두 변형의 KURE 임계값을 eval_dev(개발용 407문항)로만 조정
- blind 세트는 읽지 않습니다. 설정을 고정한 뒤 blind6는 evaluate.py로 한 번만 채점하세요.
- v7 해석과 KURE 후보는 문항당 1회만 계산하고, 임계값 조합별 판정만 다시 돌립니다.
- 채점 기준은 evaluate.py와 같음 (안내 메뉴 집합 = 정답 집합, 제한 메뉴는 '답변불가')

실행: python tune_v7_kure.py [--eval data/eval/개발용.csv]
"""
import argparse
import contextlib
import io
import itertools

import numpy as np
import pandas as pd

import config
from data_loader import load_all
from evaluate import RESTRICTED_MENUS, UNANSWERABLE
from matcher import SentenceMatcher, load_model, normalize
from v7_adapter import KURE_MODES, V7Matcher

CLARIFY_FIXED = 0.60   # 되묻기와 fallback은 채점상 같은 '안내 안 함'이라 점수로는 조정 불가 → 고정


def is_correct(res, gold):
    golds = {g.strip() for g in gold.split("|") if g.strip()}
    if res.status != "answer":
        return golds == {UNANSWERABLE}
    menus = {UNANSWERABLE if c.menu in RESTRICTED_MENUS else c.menu for c in res.answers}
    return menus == golds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default="data/eval/개발용.csv")
    a = ap.parse_args()
    if "블라인드" in a.eval or "blind" in a.eval.lower():
        raise SystemExit("임계값 조정에는 blind 세트를 쓰지 않습니다.")
    rows = pd.read_csv(a.eval, encoding="utf-8-sig", dtype=str).fillna("")

    data = load_all()
    model = load_model()
    ex = data["example"]
    ex = ex[ex["SOURCE"].astype(str).str.startswith(config.V7_EXAMPLE_PREFIX)]
    with contextlib.redirect_stdout(io.StringIO()):
        kure = SentenceMatcher(data["keyword"].iloc[0:0], ex, model)
    print(f"KURE 예시 {len(ex)}건 임베딩 완료")

    v7_only = V7Matcher(data["knowledge"], data["keyword"], ex, None, "v7")
    base = np.mean([is_correct(v7_only.match(q), g) for q, g in zip(rows["질문"], rows["정답메뉴"])])
    print(f"\n[참고] eval_dev v7만: {base:.1%}  (v7은 이 세트로 규칙을 만들어 표본 내 수치)")

    emb_cache = {}
    answer_grid = np.round(np.arange(0.50, 0.901, 0.025), 3)
    margin_grid = [0.0, 0.01, 0.02, 0.03, 0.05]
    for mode in KURE_MODES:
        m = V7Matcher(data["knowledge"], data["keyword"], ex, model, mode, kure=kure)
        prepared = []
        for q, g in zip(rows["질문"], rows["정답메뉴"]):
            r = m.engine.analyze(q)
            emb = None
            if m.needs_kure(r):
                if q not in emb_cache:
                    emb_cache[q] = kure.embed_match(q)
                emb = emb_cache[q]
            prepared.append((r, normalize(q), emb, g))
        n_kure = sum(e is not None for _, _, e, _ in prepared)

        results = []
        for at, mg in itertools.product(answer_grid, margin_grid):
            th = (float(at), CLARIFY_FIXED, mg)
            acc = np.mean([is_correct(m.decide(r, nq, e, th), g) for r, nq, e, g in prepared])
            results.append((acc, at, mg))
        # 같은 점수면 더 보수적인(높은) 임계값을 고름
        best = max(results, key=lambda x: (round(x[0], 6), x[1], x[2]))
        print(f"\n== {mode}: KURE까지 간 문항 {n_kure}/{len(rows)}")
        top = sorted(results, key=lambda x: (-round(x[0], 6), -x[1], -x[2]))[:8]
        for acc, at, mg in top:
            print(f"   answer {at:.3f}  margin {mg:.2f}  → {acc:.1%}")
        print(f"   선택: answer {best[1]:.3f}, clarify {CLARIFY_FIXED:.2f}, margin {best[2]:.2f} → {best[0]:.1%}")
        default = np.mean([is_correct(m.decide(r, nq, e, (0.75, 0.60, 0.03)), g) for r, nq, e, g in prepared])
        print(f"   (참고: PoC 기본값 0.75/0.60/0.03 → {default:.1%})")


if __name__ == "__main__":
    main()
