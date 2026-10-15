"""
v7 해석 엔진(taas_nlu.py) 래퍼
- v7 엔진 파일은 수정하지 않고 config.V7_DIR에서 그대로 불러옵니다. 기동 시 SHA256.txt와 대조합니다.
- 지식·키워드는 data_loader가 읽은 데이터를 임시 CSV로 써서 넘깁니다 (DB/Oracle 전환 그대로 유지).
- v7 결과를 PoC의 MatchResult(answer / clarify / fallback)로 바꿔 app.py·/chat 응답·로그를 그대로 씁니다.

모드
  v7               : v7 엔진만 (규칙 + v7 자체 TF-IDF 유사도)
  v7_kure_replace  : v7 규칙(TF-IDF 끔) → 메뉴를 못 찾으면 KURE 임베딩
  v7_kure_fallback : v7 규칙 + TF-IDF → 그래도 '해석 불가' 되묻기면 KURE 임베딩
"""
import hashlib
import os
import sys
import tempfile

import config
from matcher import Candidate, MatchResult, SentenceMatcher, normalize

KURE_MODES = ("v7_kure_replace", "v7_kure_fallback")
OOS_ROUTES = ("업무밖", "업무밖(유사도)", "빈 질문")
RESTRICTED_DEFAULT = "별도문의"   # 어떤 제한 메뉴인지 추적할 수 없을 때 쓰는 대표 제한 메뉴


def _import_engine():
    if config.V7_DIR not in sys.path:
        sys.path.insert(0, config.V7_DIR)
    import taas_nlu
    return taas_nlu


def verify_frozen():
    """SHA256.txt에 적힌 동결 해시와 실제 파일 비교. 다르면 경고만 남김"""
    sha_file = os.path.join(config.V7_DIR, "SHA256.txt")
    if not os.path.exists(sha_file):
        print("[v7] SHA256.txt 없음 - 동결 여부 확인 불가")
        return False
    ok = True
    for line in open(sha_file, encoding="utf-8"):
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            continue
        digest, name = parts
        path = next((p for p in (os.path.join(config.V7_DIR, name), os.path.join(config.V7_DIR, "data", name))
                     if os.path.exists(p)), None)
        if path is None:
            print(f"[v7] 경고: {name} 파일 없음"); ok = False
            continue
        if hashlib.sha256(open(path, "rb").read()).hexdigest() != digest:
            print(f"[v7] 경고: {name} 해시가 동결본과 다름 (보고서 수치와 결과가 달라질 수 있음)"); ok = False
    if ok:
        print("[v7] 동결 해시 일치")
    return ok


def _sources_dir(knowledge_df, keyword_df):
    if config.V7_DATA == "v7_sources":
        return os.path.join(config.V7_DIR, "sources")
    need = {"DOCUMENT", "TERTIARY_MENU", "SUBMENU", "KEYWORD_MENU", "INFORMATION"}
    missing = need - set(knowledge_df.columns)
    if missing:
        raise ValueError(f"v7 모드는 실제 지식 데이터가 필요합니다 (없는 컬럼: {sorted(missing)}). "
                         "import_data.py로 taas.db를 만들거나 Oracle 모드를 쓰세요.")
    tmp = tempfile.mkdtemp(prefix="v7src_")
    knowledge_df.to_csv(os.path.join(tmp, "DOCUMENT_SET.csv"), index=False, encoding="utf-8-sig")
    keyword_df.to_csv(os.path.join(tmp, "KEYWORD_SET.csv"), index=False, encoding="utf-8-sig")
    return tmp


class V7Matcher:
    def __init__(self, knowledge_df, keyword_df, example_df, model, mode, kure=None):
        if mode not in ("v7",) + KURE_MODES:
            raise ValueError(f"알 수 없는 엔진 모드: {mode}")
        self.mode = mode
        taas_nlu = _import_engine()
        verify_frozen()
        data = os.path.join(config.V7_DIR, "data")
        self.engine = taas_nlu.Engine(
            _sources_dir(knowledge_df, keyword_df),
            examples_csv=os.path.join(data, "example_questions.csv"),
            aug_csv=os.path.join(data, "example_questions_aug_v2.csv"),
            use_semantic=(mode != "v7_kure_replace"),
        )
        self.keyword_menu = {m: d["KEYWORD_MENU"] for m, d in self.engine.docs.items()}
        print(f"[v7] 엔진 {taas_nlu.Engine.VERSION} 로드 (모드 {mode}, 데이터 {config.V7_DATA}, 제한 메뉴 {len(self.engine.restricted)}개)")

        self.kure = kure
        if mode in KURE_MODES and self.kure is None:
            if model is None:
                raise ValueError(f"{mode} 모드는 KURE 모델이 필요합니다 (CHATBOT_USE_EMBEDDING=1)")
            # 기존 PoC의 임베딩 단계를 그대로 재사용 (사전은 비워 둠)
            self.kure = SentenceMatcher(keyword_df.iloc[0:0], example_df, model)
        mt = config.V7K_THRESHOLDS.get(mode, (None, None, None))
        self.thresholds = mt

    # ------------------------------------------------------------ 변환 유틸
    def _cand(self, menu, stage, score=1.0, evidence=""):
        return Candidate(menu, self.keyword_menu.get(menu, ""), score, stage, evidence)

    def _restricted_menu(self, r):
        """v7이 '답변불가'로 합친 제한 메뉴를 trace에서 되찾음 (안내 문구용). 못 찾으면 대표 제한 메뉴"""
        tr = r["trace"]
        keys = [p for k, p in tr.get("pieces", []) if k == "KW"] + [k for _, k in tr.get("fuzzy", [])]
        for k in keys:
            m = self.engine.lex.get(k, ("",))[0]
            if m in self.engine.restricted:
                return m
        for m, _ in tr.get("semantic", []):
            if m in self.engine.restricted:
                return m
        return RESTRICTED_DEFAULT

    def _evidence(self, r):
        tr = r["trace"]
        bits = [",".join(p for k, p in tr.get("pieces", []) if k == "KW"), ",".join(tr.get("slot", [])),
                ",".join(f"{a}->{b}" for a, b in tr.get("fuzzy", []))]
        return " | ".join(b for b in bits if b)

    def _clarify_from_suggest(self, r, nq):
        cands = [self._cand(m, "v7:되묻기", 0.0) for m in r["suggest"]
                 if m in self.engine.docs and m not in self.engine.restricted][: config.TOP_K]
        if cands:
            return MatchResult("clarify", candidates=cands, normalized_query=nq)
        return MatchResult("fallback", normalized_query=nq)

    # ------------------------------------------------------------ 판정
    def needs_kure(self, r):
        if self.mode == "v7_kure_replace":
            return r["route"] == "미응답"
        if self.mode == "v7_kure_fallback":
            return r["route"] == "되묻기" and r["reason"] == "해석 불가"
        return False

    def decide(self, r, nq, emb=None, thresholds=None):
        """v7 결과(+필요 시 KURE 후보) → MatchResult. 임계값 튜닝 때도 같은 함수를 씀"""
        route, menus = r["route"], r["menus"]
        if self.needs_kure(r) and emb is not None:
            return self._decide_kure(r, nq, emb, thresholds or self.thresholds)

        if menus and menus != ["답변불가"]:
            out = []
            for m in menus:
                menu = self._restricted_menu(r) if m == "답변불가" else m
                if menu not in [c.menu for c in out]:
                    out.append(self._cand(menu, f"v7:{route}", 1.0, self._evidence(r)))
            return MatchResult("answer", answers=out, candidates=out, normalized_query=nq)

        if route in OOS_ROUTES or route == "미응답":
            return MatchResult("fallback", normalized_query=nq)
        if route == "되묻기":
            return self._clarify_from_suggest(r, nq)
        # 사전·슬롯·유사도 등으로 제한 메뉴에 걸린 경우 → 제한 안내 문구로 답변
        c = self._cand(self._restricted_menu(r), f"v7:{route}", 1.0, self._evidence(r))
        return MatchResult("answer", answers=[c], candidates=[c], normalized_query=nq)

    def _decide_kure(self, r, nq, emb, thresholds):
        answer_t, clarify_t, margin_t = thresholds
        if not emb:
            return self._clarify_from_suggest(r, nq) if self.mode == "v7_kure_fallback" else MatchResult("fallback", normalized_query=nq)
        top = emb[0]
        shown = [c for c in emb if c.menu != config.OOS_LABEL]
        if top.menu == config.OOS_LABEL:   # 업무 밖 예시와 가장 가까움
            return MatchResult("fallback", candidates=shown, normalized_query=nq)
        gap = top.score - emb[1].score if len(emb) > 1 else 1.0
        if top.score >= answer_t and gap >= margin_t:
            return MatchResult("answer", answers=[top], candidates=emb, normalized_query=nq)
        if self.mode == "v7_kure_fallback":   # KURE도 확신이 없으면 v7 되묻기 그대로
            return self._clarify_from_suggest(r, nq)
        if top.score >= clarify_t:
            return MatchResult("clarify", candidates=shown, normalized_query=nq)
        return MatchResult("fallback", candidates=shown, normalized_query=nq)

    def match(self, query: str) -> MatchResult:
        nq = normalize(query)
        r = self.engine.analyze(query)
        emb = self.kure.embed_match(query) if (self.kure is not None and self.needs_kure(r)) else None
        return self.decide(r, nq, emb)
