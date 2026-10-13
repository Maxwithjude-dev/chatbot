"""
목업 DB(SQLite) 생성 스크립트
- 원본 소스에서 쓰는 컬럼 구조를 그대로 따르고, 예시 질문 테이블과 로그 보강 컬럼을 추가했습니다.
- 데이터는 모두 '더미'입니다. 공단 DB 수령 후 실제 데이터로 교체하세요.

실행: python create_mock_db.py
"""
import sqlite3
import config

T = config.TABLES

# (TERTIARY_MENU, KEYWORD_MENU, [동의어 키워드...])
KEYWORDS = [
    ("음주운전", "상세통계", ["음주운전", "음주", "만취운전", "음주사고"]),
    ("어린이", "상세통계", ["어린이", "어린이사고", "아동", "스쿨존", "어린이보호구역"]),
    ("고령운전자", "상세통계", ["고령운전자", "노인운전자", "고령자"]),
    ("보행자", "상세통계", ["보행자", "보행자사고", "무단횡단"]),
    ("이륜차", "상세통계", ["이륜차", "오토바이", "배달오토바이"]),
    ("무면허운전", "상세통계", ["무면허운전", "무면허"]),
    ("화물차", "상세통계", ["화물차", "트럭"]),
    ("사고다발지역", "메뉴안내", ["사고다발지역", "사고다발구역", "위험지역"]),
    ("교통안전지수", "메뉴안내", ["교통안전지수", "안전지수"]),
    ("자료실", "메뉴안내", ["자료실", "보고서", "간행물"]),
]

# (TERTIARY_MENU, KEYWORD_MENU, DOCUMENT, INFORMATION, IS_URL_PROVIDE, IS_ANSWERABLE)
KNOWLEDGE = [
    ("음주운전", "상세통계", "음주운전", "음주운전 사고 건수, 사상자 등", "1", "1"),
    ("어린이", "상세통계", "어린이", "어린이 교통사고 건수, 사상자 등", "1", "1"),
    ("고령운전자", "상세통계", "고령운전자", "65세 이상 운전자 사고 통계", "1", "1"),
    ("보행자", "상세통계", "보행자", "보행자 사고 통계", "1", "1"),
    ("이륜차", "상세통계", "이륜차", "이륜차 사고 통계", "1", "1"),
    ("무면허운전", "상세통계", "무면허운전", "무면허운전 사고 통계", "1", "1"),
    ("화물차", "상세통계", "화물차", "화물차 사고 통계", "1", "1"),
    ("사고다발지역", "메뉴안내", "사고다발지역 정보는 [사고분석 > 사고다발지역]에서 지역별로 확인하실 수 있습니다.", "사고다발지역", "1", "1"),
    ("교통안전지수", "메뉴안내", "교통안전지수는 [통계분석 > 교통안전지수]에서 지자체별로 확인하실 수 있습니다.", "교통안전지수", "1", "1"),
    ("자료실", "메뉴안내", "각종 보고서와 간행물은 [자료실]에서 내려받으실 수 있습니다.", "자료실", "1", "1"),
]

# (QUESTION, TERTIARY_MENU, KEYWORD_MENU, SOURCE)
EXAMPLES = [
    ("음주운전 사고 통계 알려줘", "음주운전", "상세통계", "수동"),
    ("술 마시고 운전해서 난 사고가 몇 건이야", "음주운전", "상세통계", "수동"),
    ("음주 교통사고 건수", "음주운전", "상세통계", "템플릿"),
    ("어린이 교통사고 통계 보고 싶어요", "어린이", "상세통계", "수동"),
    ("아이들이 다친 사고 얼마나 돼", "어린이", "상세통계", "수동"),
    ("스쿨존 사고 현황", "어린이", "상세통계", "템플릿"),
    ("노인 운전자 사고 통계", "고령운전자", "상세통계", "수동"),
    ("나이 많은 운전자가 낸 사고", "고령운전자", "상세통계", "수동"),
    ("보행자 교통사고 통계", "보행자", "상세통계", "수동"),
    ("길 건너다 차에 치인 사고", "보행자", "상세통계", "수동"),
    ("오토바이 사고 통계", "이륜차", "상세통계", "수동"),
    ("배달 라이더 사고 건수", "이륜차", "상세통계", "수동"),
    ("면허 없이 운전한 사고", "무면허운전", "상세통계", "수동"),
    ("트럭 사고 통계", "화물차", "상세통계", "수동"),
    ("대형 화물 차량 사고", "화물차", "상세통계", "수동"),
    ("사고가 자주 나는 곳 어디야", "사고다발지역", "메뉴안내", "수동"),
    ("우리 동네 위험한 교차로 알고 싶어", "사고다발지역", "메뉴안내", "수동"),
    ("지역별 교통안전 수준 비교", "교통안전지수", "메뉴안내", "수동"),
    ("우리 시 교통안전 점수", "교통안전지수", "메뉴안내", "수동"),
    ("교통사고 분석 보고서 다운로드", "자료실", "메뉴안내", "수동"),
    ("연간 통계 책자 받을 수 있어?", "자료실", "메뉴안내", "수동"),
]

USER_DICT = [("음주운전", "NNP"), ("고령운전자", "NNP"), ("사고다발지역", "NNP"), ("이륜차", "NNG")]


def main():
    conn = sqlite3.connect(config.SQLITE_PATH)
    cur = conn.cursor()
    for name in ("keyword", "knowledge", "user_dict", "example"):
        cur.execute(f"DROP TABLE IF EXISTS {T[name]}")

    cur.execute(f"""CREATE TABLE {T['keyword']} (
        KEYWORD TEXT, KEYWORD_MENU TEXT, TERTIARY_MENU TEXT)""")
    cur.execute(f"""CREATE TABLE {T['knowledge']} (
        TERTIARY_MENU TEXT, KEYWORD_MENU TEXT, DOCUMENT TEXT, INFORMATION TEXT,
        IS_URL_PROVIDE TEXT, IS_ANSWERABLE TEXT)""")
    cur.execute(f"""CREATE TABLE {T['user_dict']} (MORPHEME TEXT, MORPHEME_CODE TEXT)""")
    cur.execute(f"""CREATE TABLE {T['example']} (
        EXAMPLE_ID INTEGER PRIMARY KEY AUTOINCREMENT,
        QUESTION TEXT NOT NULL, TERTIARY_MENU TEXT NOT NULL, KEYWORD_MENU TEXT,
        SOURCE TEXT, USE_YN TEXT DEFAULT 'Y', REG_DT TEXT DEFAULT CURRENT_TIMESTAMP)""")

    cur.executemany(
        f"INSERT INTO {T['keyword']} VALUES (?, ?, ?)",
        [(kw, km, menu) for menu, km, kws in KEYWORDS for kw in kws],
    )
    cur.executemany(f"INSERT INTO {T['knowledge']} VALUES (?, ?, ?, ?, ?, ?)", KNOWLEDGE)
    cur.executemany(f"INSERT INTO {T['user_dict']} VALUES (?, ?)", USER_DICT)
    cur.executemany(
        f"INSERT INTO {T['example']} (QUESTION, TERTIARY_MENU, KEYWORD_MENU, SOURCE) VALUES (?, ?, ?, ?)",
        EXAMPLES,
    )
    conn.commit()
    conn.close()
    print(f"목업 DB 생성 완료: {config.SQLITE_PATH}")


if __name__ == "__main__":
    main()
