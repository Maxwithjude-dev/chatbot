"""
공단 실제 데이터 -> SQLite(taas.db) + 평가셋 CSV 변환

입력 (data/ 폴더)
  - DOCUMENT_SET.csv, KEYWORD_SET.csv              : 공단 DB 내보내기
  - 03_테스트질문_챗봇응답_비교_*.xlsx              : 시험 질문 1,827개 (정답 메뉴는 담당자 검수 전)

출력
  - taas.db            : 지식/키워드 + 예시 질문(개발용 세트에서만 추출)
  - data/eval/*.csv    : 세트별 평가셋 (블라인드1~6, 개발용)

개발용 세트는 임베딩 예시 질문으로 쓰고, 블라인드 세트는 채점에만 씁니다.
같은 질문을 예시와 채점에 함께 쓰면 점수가 부풀려지기 때문입니다.

실행: python import_data.py
"""
import glob
import os
import sqlite3

import pandas as pd

import config

T = config.TABLES
DATA_DIR = "data"
DB_PATH = "taas.db"
UNANSWERABLE = "답변불가"


def read_csv(name):
    return pd.read_csv(os.path.join(DATA_DIR, name), dtype=str).fillna("")


def load_v7_examples(menus):
    """v7 예시 질문(633) + AI 생성 예시(2,707) → 예시 테이블 행. v7+KURE 모드에서만 씀 (SOURCE가 'v7'로 시작)
    생성 예시 중 메뉴가 '답변불가'인 것은 버리지 않고 OOS_LABEL 부류로 넣음 (임베딩 최상위가 이 부류면 fallback)"""
    data = os.path.join(config.V7_DIR, "data")
    rows, dropped = [], 0
    for fname, tag in (("example_questions.csv", "v7예시"), ("example_questions_aug_v2.csv", "v7생성")):
        path = os.path.join(data, fname)
        if not os.path.exists(path):
            print(f"[v7 예시] {path} 없음 - 건너뜀")
            continue
        for _, r in pd.read_csv(path, dtype=str).fillna("").iterrows():
            m = r["메뉴"].strip()
            if m in menus:
                rows.append((r["질문"], m, menus[m], f"{tag}:{r['출처']}"))
            elif m == UNANSWERABLE and tag == "v7생성":
                rows.append((r["질문"], config.OOS_LABEL, "업무밖", f"{tag}:업무밖"))
            else:
                dropped += 1
    n_oos = sum(1 for r in rows if r[1] == config.OOS_LABEL)
    print(f"[v7 예시] {len(rows)}건 적재 (업무밖 부류 {n_oos}건), 제외 {dropped}건")
    return rows


def main():
    doc = read_csv("DOCUMENT_SET.csv")
    kw = read_csv("KEYWORD_SET.csv")
    xlsx = sorted(glob.glob(os.path.join(DATA_DIR, "03_테스트질문_*.xlsx")))[-1]
    qs = pd.read_excel(xlsx, sheet_name="전체_질문별_비교", dtype=str).fillna("")
    qs["정답메뉴"] = qs["정답 메뉴(검수 전)"].str.replace("+", "|", regex=False)

    # 예시 질문: 개발용 중 정답이 메뉴 하나이고 지식 DB에 있는 것만
    menus = dict(zip(doc["TERTIARY_MENU"], doc["KEYWORD_MENU"]))
    dev = qs[(qs["세트"] == "개발용") & ~qs["정답메뉴"].str.contains("|", regex=False)]
    dev = dev[dev["정답메뉴"].isin(menus.keys())]
    examples = [(r["질문"], r["정답메뉴"], menus[r["정답메뉴"]], f"개발용:{r['ID']}") for _, r in dev.iterrows()]
    examples += load_v7_examples(menus)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        doc.to_sql(T["knowledge"], conn, index=False)
        kw.to_sql(T["keyword"], conn, index=False)
        conn.execute(f"CREATE TABLE {T['user_dict']} (MORPHEME TEXT, MORPHEME_CODE TEXT)")
        conn.execute(f"""CREATE TABLE {T['example']} (
            EXAMPLE_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            QUESTION TEXT NOT NULL, TERTIARY_MENU TEXT NOT NULL, KEYWORD_MENU TEXT,
            SOURCE TEXT, USE_YN TEXT DEFAULT 'Y', REG_DT TEXT DEFAULT CURRENT_TIMESTAMP)""")
        conn.executemany(
            f"INSERT INTO {T['example']} (QUESTION, TERTIARY_MENU, KEYWORD_MENU, SOURCE) VALUES (?, ?, ?, ?)",
            examples,
        )
    print(f"{DB_PATH} 생성: 지식 {len(doc)}건, 키워드 {len(kw)}건, 예시 질문 {len(examples)}건 (개발용 {len(qs[qs['세트'] == '개발용'])}건 중)")

    # 세트별 평가셋 (현행·v7 판정도 같이 넣어 두면 나중에 나란히 비교 가능)
    out_dir = os.path.join(DATA_DIR, "eval")
    os.makedirs(out_dir, exist_ok=True)
    cols = {"ID": "ID", "질문": "질문", "정답메뉴": "정답메뉴", "질문유형": "질문유형",
            "앞선 질문과 중복": "중복", "현행 판정": "현행판정", "블라인드 판정": "v7블라인드판정"}
    for name, sub in qs.groupby("세트"):
        sub[list(cols)].rename(columns=cols).to_csv(
            os.path.join(out_dir, f"{name}.csv"), index=False, encoding="utf-8-sig")
    blind = qs[qs["세트"].str.startswith("블라인드")]
    blind[["세트"] + list(cols)].rename(columns=cols).to_csv(
        os.path.join(out_dir, "블라인드_전체.csv"), index=False, encoding="utf-8-sig")
    print(f"평가셋 저장: {out_dir}/ (블라인드 전체 {len(blind)}건)")


if __name__ == "__main__":
    main()
