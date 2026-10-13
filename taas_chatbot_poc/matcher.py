"""
문장 단위 매칭 파이프라인
  1) 정규화
  2) 사전 매칭   : 키워드/메뉴명을 질문 문자열에서 직접 찾음 (가장 긴 매칭 우선, 복수 의도 지원)
  3) 오타 매칭   : 자모 단위 편집거리 (사전 매칭이 없을 때만)
  4) 임베딩 매칭 : 질문 전체 vs 예시 질문 (앞 단계가 모두 실패했을 때)
결과 상태: answer(답변) / clarify(되묻기) / fallback(답변 불가)
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
from rapidfuzz.distance import Levenshtein

import config

# ---------------------------------------------------------------
# 텍스트 유틸
# ---------------------------------------------------------------
CHO = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
JUNG = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
JONG = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")


def to_jamo(text: str) -> str:
    """'음주' -> 'ㅇㅡㅁㅈㅜ' (오타를 글자가 아닌 자모 단위로 비교하기 위함)"""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(CHO[code // 588])
            out.append(JUNG[(code % 588) // 28])
            if code % 28:
                out.append(JONG[code % 28])
        else:
            out.append(ch)
    return "".join(out)


def normalize(text: str) -> str:
    text = str(text).lower()
    text = re.sub(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str) -> str:
    """띄어쓰기 차이를 없애기 위해 공백 제거"""
    return normalize(text).replace(" ", "")


# ---------------------------------------------------------------
# 결과 구조
# ---------------------------------------------------------------
@dataclass
class Candidate:
    menu: str            # TERTIARY_MENU
    keyword_menu: str    # 상세통계 / 메뉴안내
    score: float
    stage: str           # dict / fuzzy / embedding
    evidence: str        # 매칭 근거 (키워드 또는 예시 질문)


@dataclass
class MatchResult:
    status: str                                   # answer / clarify / fallback
    answers: List[Candidate] = field(default_factory=list)
    candidates: List[Candidate] = field(default_factory=list)  # 로그·되묻기용 상위 후보
    normalized_query: str = ""


# ---------------------------------------------------------------
# 매처
# ---------------------------------------------------------------
class SentenceMatcher:
    def __init__(self, keyword_df, example_df, model=None):
        self.model = model

        # 사전: 정규화된 키워드 -> (메뉴, 메뉴구분)
        self.terms = {}
        for row in keyword_df.itertuples(index=False):
            for raw in (row.KEYWORD, row.TERTIARY_MENU):
                term = compact(raw)
                if len(term) < config.DICT_MIN_LEN or term in config.STOPWORDS:
                    continue
                prev = self.terms.get(term)
                if prev and prev[0] != row.TERTIARY_MENU:
                    print(f"[경고] 키워드 '{term}'이 여러 메뉴에 등록됨: {prev[0]}, {row.TERTIARY_MENU} (먼저 등록된 것 사용)")
                    continue
                self.terms[term] = (row.TERTIARY_MENU, row.KEYWORD_MENU)
        self.term_jamo = {t: to_jamo(t) for t in self.terms if len(t) >= config.FUZZY_MIN_LEN}

        # 예시 질문 임베딩 (서버 기동 시 1회 계산)
        self.examples = list(example_df[["QUESTION", "TERTIARY_MENU", "KEYWORD_MENU"]].itertuples(index=False, name=None))
        self.example_emb = None
        if self.model is not None and self.examples:
            texts = [config.EXAMPLE_PREFIX + normalize(q) for q, _, _ in self.examples]
            if config.MODEL_TYPE == "multivector":
                # 예시 질문을 '문서' 쪽으로 인코딩 (토큰별 벡터 리스트)
                self.example_emb = self.model.encode_document(texts, show_progress_bar=False)
            else:
                self.example_emb = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            print(f"[matcher] 예시 질문 {len(self.examples)}건 임베딩 완료")

    # 2) 사전 매칭 -------------------------------------------------
    def dict_match(self, query: str) -> List[Candidate]:
        c = compact(query)
        hits = []
        for term, (menu, km) in self.terms.items():
            start = c.find(term)
            while start != -1:
                hits.append((start, start + len(term), term, menu, km))
                start = c.find(term, start + 1)

        # 긴 매칭 우선, 겹치는 짧은 매칭은 버림 ('고령운전자'가 잡히면 '운전자'는 무시)
        hits.sort(key=lambda h: -(h[1] - h[0]))
        taken = [False] * len(c)
        found = {}
        for s, e, term, menu, km in hits:
            if any(taken[s:e]):
                continue
            for i in range(s, e):
                taken[i] = True
            if menu not in found:
                found[menu] = (s, Candidate(menu, km, 1.0, "dict", term))
        # 질문에 등장한 순서대로 반환
        return [cand for _, cand in sorted(found.values(), key=lambda x: x[0])]

    # 3) 오타 매칭 -------------------------------------------------
    def fuzzy_match(self, query: str) -> List[Candidate]:
        c = compact(query)
        window_jamo = {}
        best = {}
        for term, tj in self.term_jamo.items():
            menu, km = self.terms[term]
            L = len(term)
            for w in (L - 1, L, L + 1):
                if w < 2 or w > len(c):
                    continue
                for i in range(len(c) - w + 1):
                    key = (i, w)
                    if key not in window_jamo:
                        window_jamo[key] = to_jamo(c[i:i + w])
                    sim = Levenshtein.normalized_similarity(tj, window_jamo[key])
                    if sim >= config.FUZZY_THRESHOLD and (menu not in best or sim > best[menu].score):
                        best[menu] = Candidate(menu, km, float(sim), "fuzzy", f"{c[i:i + w]}→{term}")
        return sorted(best.values(), key=lambda x: -x.score)

    # 4) 임베딩 매칭 -----------------------------------------------
    def embed_match(self, query: str) -> List[Candidate]:
        if self.example_emb is None:
            return []
        text = config.QUERY_PREFIX + normalize(query)
        if config.MODEL_TYPE == "multivector":
            q = self.model.encode_query([text], show_progress_bar=False)
            # length_normalize=True: MaxSim을 질문 토큰 수로 나눠 0~1 근처 점수로 (임계값 설정이 쉬워짐)
            sims = self.model.similarity(q, self.example_emb, length_normalize=True)[0]
            sims = sims.float().cpu().numpy()
        else:
            q = self.model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
            sims = self.example_emb @ q
        best = {}
        for (question, menu, km), s in zip(self.examples, sims):
            if menu not in best or s > best[menu].score:
                best[menu] = Candidate(menu, km, float(s), "embedding", question)
        return sorted(best.values(), key=lambda x: -x.score)[: config.TOP_K]

    # 전체 파이프라인 -----------------------------------------------
    def match(self, query: str) -> MatchResult:
        nq = normalize(query)

        cands = self.dict_match(query)
        if not cands:
            # 참고: 정확한 키워드와 오타 키워드가 섞인 질문은 현재 정확한 쪽만 잡힘 (PoC 단순화)
            cands = self.fuzzy_match(query)
        if cands:
            return MatchResult("answer", answers=cands, candidates=cands, normalized_query=nq)

        emb = self.embed_match(query)
        if not emb:
            return MatchResult("fallback", normalized_query=nq)

        top = emb[0]
        gap = top.score - emb[1].score if len(emb) > 1 else 1.0
        if top.score >= config.ANSWER_THRESHOLD and gap >= config.CLARIFY_MARGIN:
            return MatchResult("answer", answers=[top], candidates=emb, normalized_query=nq)
        if top.score >= config.CLARIFY_THRESHOLD:
            return MatchResult("clarify", candidates=emb, normalized_query=nq)
        return MatchResult("fallback", candidates=emb, normalized_query=nq)


def load_model():
    print(f"[matcher] 모델 로드: {config.MODEL_PATH} ({config.MODEL_TYPE})")
    if config.MODEL_TYPE == "multivector":
        from sentence_transformers import MultiVectorEncoder  # sentence-transformers >= 6.0
        return MultiVectorEncoder(config.MODEL_PATH, device="cpu")
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config.MODEL_PATH, device="cpu")
