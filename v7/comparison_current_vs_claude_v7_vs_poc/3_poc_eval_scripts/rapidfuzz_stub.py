# rapidfuzz 미설치 환경용 대체: Levenshtein.normalized_similarity (유사도 0.85 미만은 정확값 불필요 → 상한 컷)
import sys, types
def _lev_cap(a, b, cap):
    if a == b: return 0
    if abs(len(a) - len(b)) > cap: return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]; best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)); cur.append(v)
            if v < best: best = v
        if best > cap: return cap + 1
        prev = cur
    return prev[-1]
class Levenshtein:
    @staticmethod
    def normalized_similarity(a, b):
        m = max(len(a), len(b))
        if m == 0: return 1.0
        cap = int(m * 0.16)
        d = _lev_cap(a, b, cap)
        return 0.0 if d > cap else 1 - d / m
m = types.ModuleType("rapidfuzz"); d = types.ModuleType("rapidfuzz.distance"); d.Levenshtein = Levenshtein
m.distance = d; sys.modules["rapidfuzz"] = m; sys.modules["rapidfuzz.distance"] = d
