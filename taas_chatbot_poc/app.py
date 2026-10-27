"""
개선 챗봇 서버 (기존 /chat 응답 형식과 호환)
- 기존 키: document, keyword_menu, information, is_url_provide, inference
- 추가 키: status, tertiary_menu, match_stage, candidates  (화면에서 되묻기 버튼을 그릴 때 사용)

실행: uvicorn app:app --host 0.0.0.0 --port 8000
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import config
from data_loader import load_all
from matcher import build_matcher, load_model

# ---------------------------------------------------------------
# 기동 시 1회 준비
# ---------------------------------------------------------------
DATA = load_all()
MODEL = load_model() if config.USE_EMBEDDING else None
MATCHER = build_matcher(DATA, MODEL)

# 메뉴 -> 지식 DB 행 (원본과 동일하게 첫 번째 행 사용)
KNOWLEDGE = {}
for row in DATA["knowledge"].to_dict("records"):
    KNOWLEDGE.setdefault(row["TERTIARY_MENU"], row)

LOG_TABLE = config.TABLES["log"]


def init_log_db():
    with sqlite3.connect(config.LOG_SQLITE_PATH) as conn:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
            QUESTION TEXT, CORRECT_QUESTION TEXT, MORPHPMES TEXT, KEYWORD TEXT,
            SIMILARITY_VALUE TEXT, ANSWER TEXT, QUESTION_DT TEXT, ANSWER_DT TEXT, CONECTR_IP TEXT,
            MATCH_STAGE TEXT, MATCHED_EXAMPLE TEXT, CANDIDATES TEXT, MODEL_VERSION TEXT)""")


init_log_db()
app = FastAPI()


class Param(BaseModel):
    query: str
    conectrIp: str = ""


# ---------------------------------------------------------------
# 응답 생성
# ---------------------------------------------------------------
def build_document(menu: str):
    row = KNOWLEDGE.get(menu)
    if row is None:
        return "참고 문서 없음", "참고 문서 없음", "참고 문서 없음", "0"
    if row["KEYWORD_MENU"] == "상세통계":
        doc = f"해당 통계는 {row['DOCUMENT']} 통계[통계분석 > 상세통계]에서 확인하실 수 있습니다."
    else:
        doc = row["DOCUMENT"]
    return doc, row["KEYWORD_MENU"], row["INFORMATION"], row["IS_URL_PROVIDE"]


def build_link(menu: str) -> str:
    """INFORMATION으로 바로가기 주소 생성. 링크 제공 안 하는 메뉴(IS_URL_PROVIDE=0)·형식이 다른 값은 빈 문자열
    - 상세통계: '패턴ID|검색어' → 상세통계 화면 주소
    - 메뉴안내: '버튼이름|경로' → 경로 (상대경로는 TAAS 주소를 붙임)"""
    row = KNOWLEDGE.get(menu)
    if row is None or row["IS_URL_PROVIDE"] != "1" or "|" not in row["INFORMATION"]:
        return ""
    head, tail = (x.strip() for x in row["INFORMATION"].split("|", 1))
    if row["KEYWORD_MENU"] == "상세통계":
        if not head.isdigit():
            return ""
        return config.DETAIL_STAT_URL.format(pattern_id=head, search_word=quote(tail))
    if tail.startswith("/"):
        return config.TAAS_BASE_URL + tail
    return tail if tail.startswith("http") else ""


def build_response(result) -> dict:
    resp = {
        "document": [], "keyword_menu": [], "information": [], "is_url_provide": [],
        "url": [],   # 추가 키: document와 같은 순서의 바로가기 주소 (없으면 빈 문자열)
        "inference": False,
        "status": result.status,
        "tertiary_menu": [],
        "match_stage": "",
        "candidates": [{"menu": c.menu, "score": round(c.score, 4), "stage": c.stage}
                       for c in result.candidates],
    }

    if result.status == "answer":
        resp["match_stage"] = result.answers[0].stage
        for c in result.answers:
            doc, km, info, url = build_document(c.menu)
            resp["document"].append(doc)
            resp["keyword_menu"].append(km)
            resp["information"].append(info)
            resp["is_url_provide"].append(url)
            resp["url"].append(build_link(c.menu))
            resp["tertiary_menu"].append(c.menu)
    elif result.status == "clarify":
        resp["match_stage"] = "embedding"
        resp["document"].append(config.CLARIFY_MESSAGE)
    else:
        resp["document"].append(config.FALLBACK_MESSAGE)
    return resp


def write_log(param, result, resp, question_dt, answer_dt):
    picked = result.answers if result.answers else result.candidates
    matched_example = next((c.evidence for c in result.candidates if c.stage == "embedding"), "")
    with sqlite3.connect(config.LOG_SQLITE_PATH) as conn:
        conn.execute(
            f"INSERT INTO {LOG_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                param.query,
                result.normalized_query,
                "",  # 형태소 분석을 쓰지 않으므로 비움 (호환용 컬럼)
                ",".join(c.menu for c in picked),
                ",".join(f"{c.score:.4f}" for c in picked),
                resp["document"][0] if resp["document"] else "",
                question_dt.isoformat(),
                answer_dt.isoformat(),
                param.conectrIp,
                resp["match_stage"] or result.status,
                matched_example,
                json.dumps(resp["candidates"], ensure_ascii=False),
                config.MODEL_VERSION if MODEL is not None else "none",
            ),
        )


@app.get("/")
def chat_page():
    """테스트용 채팅 화면"""
    return FileResponse(Path(__file__).parent / "static" / "chat.html")


@app.post("/chat")
def chat_api(param: Param):
    question_dt = datetime.now()
    result = MATCHER.match(param.query)
    resp = build_response(result)
    answer_dt = datetime.now()
    try:
        write_log(param, result, resp, question_dt, answer_dt)
    except Exception as e:  # 로그 실패가 답변을 막지 않도록
        print(f"[log] 기록 실패: {e}")
    return JSONResponse(content=resp, headers={"Content-Type": "application/json; charset=utf-8"})
