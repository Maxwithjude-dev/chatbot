"""
데이터 로딩 계층
- config.DB_MODE로 목업(SQLite) / 공단 Oracle을 전환합니다.
- 예시 질문 테이블은 항상 목업 SQLite에서 읽습니다 (운영 DB는 읽기만 한다는 원칙).
"""
import sqlite3
import pandas as pd
import config

T = config.TABLES
_oracle_initialized = False


def _read_sqlite(sql: str, path: str = config.SQLITE_PATH) -> pd.DataFrame:
    with sqlite3.connect(path) as conn:
        return pd.read_sql_query(sql, conn)


def _read_oracle(sql: str) -> pd.DataFrame:
    global _oracle_initialized
    import oracledb  # Oracle 모드에서만 필요

    if config.ORACLE["lib_dir"] and not _oracle_initialized:
        oracledb.init_oracle_client(lib_dir=config.ORACLE["lib_dir"])
        _oracle_initialized = True

    with oracledb.connect(
        user=config.ORACLE["user"], password=config.ORACLE["password"], dsn=config.ORACLE["dsn"]
    ) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def _read(sql: str) -> pd.DataFrame:
    return _read_oracle(sql) if config.DB_MODE == "oracle" else _read_sqlite(sql)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.fillna("")
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip()
    return df


def load_all() -> dict:
    data = {
        "keyword": _read(f"SELECT KEYWORD, KEYWORD_MENU, TERTIARY_MENU FROM {T['keyword']}"),
        "knowledge": _read(
            f"SELECT * FROM {T['knowledge']} "
            f"WHERE KEYWORD_MENU IN ('상세통계', '메뉴안내') AND IS_ANSWERABLE = '1'"
        ),
        "user_dict": _read(f"SELECT MORPHEME, MORPHEME_CODE FROM {T['user_dict']}"),
        "example": _read_sqlite(
            f"SELECT QUESTION, TERTIARY_MENU, KEYWORD_MENU, SOURCE FROM {T['example']} WHERE USE_YN = 'Y'"
        ),
    }
    data = {k: _clean(v) for k, v in data.items()}
    for k, v in data.items():
        print(f"[data_loader] {k}: {len(v)}건 ({config.DB_MODE if k != 'example' else 'sqlite'})")
    return data
