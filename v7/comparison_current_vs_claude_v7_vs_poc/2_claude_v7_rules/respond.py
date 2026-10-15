#!/usr/bin/env python3
"""해석 결과 → 사용자에게 보여줄 답변 문장 (제안 형식)
- 메뉴 1개: 기존 DOCUMENT 문구 + 링크
- 메뉴 여러 개: "요청하신 내용은 아래 N곳에서 보실 수 있습니다" + 목록
- 제공 제한: 사유 안내 + 같은 질문에서 볼 수 있는 대체 메뉴 제시
- 업무 밖: TAAS 범위 안내 + 대표 메뉴
- 되묻기(해석 불가): "혹시 이 중에 찾으시는 게 있나요?" + 후보 3개
- 유사도 경로: 확인형 문구 "~를 찾으시나요?"
사용: python3 proto/respond.py "질문" ["질문" ...]
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from taas_nlu import Engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://taas.koroad.or.kr"


def link(doc):
    info = doc.get("INFORMATION", "")
    if "|" in info:
        url = info.split("|", 1)[1]
        if url.startswith("/"): url = BASE + url
        if url.startswith("http"): return url
    return ""


def menu_line(e, m):
    d = e.docs[m]
    text = d["DOCUMENT"]
    if d["KEYWORD_MENU"] == "상세통계":
        text = f"{text} 통계 [통계분석 > 상세통계]"
    text = re.sub(r"\.n ", ". ", text).rstrip('"\\ ')
    u = link(d)
    return f"- {text}" + (f"  ({u})" if u else "")


def friendly(e, m):
    d = e.docs[m]["DOCUMENT"]
    if d.startswith("["): return d.split("]")[0].strip("[ ").split(">")[-1].strip()
    return re.sub(r"\.n .*", "", d).strip('" ')[:40]


def respond(e, q):
    r = e.analyze(q)
    menus, route, tr = r["menus"], r["route"], r["trace"]
    open_menus = [m for m in menus if m != "답변불가"]
    if route == "업무밖" or route == "업무밖(유사도)":
        return ("TAAS(교통사고분석시스템)는 교통사고 통계를 제공하는 곳이라 이 질문에는 답변드리기 어렵습니다. "
                "운전면허·과태료·보험 등은 해당 기관에 문의해 주세요.\n교통사고 통계는 [한눈에 보는 통계 > 주요 교통사고통계]에서 보실 수 있습니다.\n(TAAS 문의) 033-749-5266, 5267, 5269, 5264")
    if route == "빈 질문":
        return "궁금하신 교통사고 통계를 입력해 주세요. 예) '서울 음주운전 사고', '노인 보행자 사고'"
    if route == "되묻기":
        cands = [m for m in r["suggest"] if m in e.docs and m not in e.restricted][:3]
        if not cands:
            return "질문을 정확히 이해하지 못했습니다. 지역·시간·대상(어린이, 노인 등)을 넣어 다시 질문해 주세요."
        if r["reason"] == "부정 표현":
            return "제외 조건('~ 아닌', '~ 말고')은 메뉴로 바로 안내하기 어렵습니다. 아래 메뉴에서 조건을 골라 보실 수 있습니다.\n" + "\n".join(f"{i+1}. {friendly(e, m)}" for i, m in enumerate(cands))
        return "질문을 정확히 이해하지 못했습니다. 혹시 아래 중에 찾으시는 내용이 있나요?\n" + "\n".join(f"{i+1}. {friendly(e, m)}" for i, m in enumerate(cands))
    if route == "포괄":
        return ("전체 교통사고 현황은 아래에서 보실 수 있습니다.\n" + menu_line(e, "주요 교통사고통계") +
                "\n지역·시간·대상(어린이, 노인 등)을 함께 말씀해 주시면 더 정확한 통계를 안내해 드립니다.")
    lines = []
    restricted_part = "답변불가" in menus
    if restricted_part:
        alt = tr.get("restricted_dominant", [])
        # 제한 사유: 원래 걸린 제한 메뉴의 안내 문구 사용
        rmenu = None
        for p in tr.get("pieces", []):
            if p[0] == "KW" and e.lex.get(p[1], ("",))[0] in e.restricted: rmenu = e.lex[p[1]][0]; break
        for s in tr.get("slot", []):
            pass
        reason = e.docs[rmenu]["DOCUMENT"] if rmenu else "요청하신 세부 항목은 TAAS에서 제공하지 않는 정보입니다. (문의) 033-749-5266, 5267, 5269, 5264"
        lines.append(reason)
        alts = [m for m in (alt or open_menus) if m in e.docs and m not in e.restricted]
        if alts:
            lines.append("대신 아래 통계는 보실 수 있습니다.")
            lines += [menu_line(e, m) for m in alts]
        return "\n".join(lines)
    if len(open_menus) == 1:
        prefix = "혹시 이 메뉴를 찾으시나요? " if route == "유사도" else ""
        return prefix + menu_line(e, open_menus[0])[2:]
    return f"요청하신 내용은 아래 {len(open_menus)}곳에서 보실 수 있습니다.\n" + "\n".join(menu_line(e, m) for m in open_menus)


if __name__ == "__main__":
    e = Engine(os.path.join(ROOT, "sources"), examples_csv=os.path.join(ROOT, "data", "example_questions.csv"),
               aug_csv=os.path.join(ROOT, "data", "example_questions_aug_v2.csv"))
    qs = sys.argv[1:] or ["노인 운전자 사고", "자전거 타다 차에 치인 사고", "서울 음주운전 사고", "음주랑 과속 사고",
                          "헬멧 안 쓴 오토바이 사고", "운전면허 갱신 어디서 해요", "사고", "블라블라 뭐지"]
    for q in qs:
        print(f"Q. {q}\nA. {respond(e, q)}\n")
