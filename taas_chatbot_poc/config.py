"""
TAAS 챗봇 PoC 설정
- 환경변수로 덮어쓸 수 있게 해 두었습니다.
- 임계값(THRESHOLD)은 모델마다 유사도 분포가 다르므로 반드시 평가셋으로 다시 맞춰야 합니다.
"""
import json
import os

# ---------------------------------------------------------------
# 데이터 소스
# ---------------------------------------------------------------
# "sqlite": 목업 DB 사용 / "oracle": 공단 Oracle에서 읽기 (읽기 전용)
DB_MODE = os.getenv("CHATBOT_DB_MODE", "sqlite")

# 실제 데이터 DB(import_data.py로 생성)가 있으면 그것을, 없으면 목업 DB를 씁니다.
# 예시 질문 테이블은 Oracle 모드에서도 항상 여기서 읽습니다(운영 DB 미변경 원칙).
SQLITE_PATH = os.getenv("CHATBOT_SQLITE_PATH", "taas.db" if os.path.exists("taas.db") else "mock_taas.db")

# 로그는 운영 로그 테이블과 섞이지 않도록 별도 SQLite에 기록합니다.
LOG_SQLITE_PATH = os.getenv("CHATBOT_LOG_PATH", "chatbot_log.db")

ORACLE = {
    "user": os.getenv("ORACLE_USER", ""),
    "password": os.getenv("ORACLE_PASSWORD", ""),
    "dsn": os.getenv("ORACLE_DSN", ""),          # 예: "host:1521/service"
    "lib_dir": os.getenv("ORACLE_LIB_DIR"),       # thick 모드가 필요할 때만
}

# 실제 테이블명은 공단 DB 수령 후 교체하세요. (원본 소스에서는 마스킹되어 있음)
TABLES = {
    "keyword": "TAAS_CHATBOT_KEYWORD",
    "knowledge": "TAAS_CHATBOT_KNOWLEDGE",
    "user_dict": "TAAS_CHATBOT_USER_DICT",
    "example": "TAAS_CHATBOT_EXAMPLE_QUESTION",   # 신규
    "log": "TAAS_CHATBOT_OPERT_EXC_HIST",
}

# ---------------------------------------------------------------
# 임베딩 모델
# ---------------------------------------------------------------
USE_EMBEDDING = os.getenv("CHATBOT_USE_EMBEDDING", "1") == "1"
# 로컬 경로 또는 허깅페이스 모델명 (망분리 환경이면 반드시 로컬 경로)
MODEL_PATH = os.getenv("CHATBOT_MODEL_PATH", "nlpai-lab/KURE-v1")
MODEL_VERSION = os.getenv("CHATBOT_MODEL_VERSION", os.path.basename(MODEL_PATH.rstrip("/\\")))
# "dense": 문장 하나를 벡터 하나로 (ko-sbert, KURE-v1, bge-m3, e5 등)
# "multivector": 토큰마다 벡터, MaxSim 점수 (KURE-v2 등 ColBERT 계열, sentence-transformers 6.0 이상 필요)
MODEL_TYPE = os.getenv("CHATBOT_MODEL_TYPE", "dense")
# multilingual-e5 계열은 질문/예시 질문 모두 앞에 "query: "를 붙여야 성능이 제대로 나옵니다.
QUERY_PREFIX = os.getenv("CHATBOT_QUERY_PREFIX", "")
EXAMPLE_PREFIX = os.getenv("CHATBOT_EXAMPLE_PREFIX", "")

# ---------------------------------------------------------------
# 해석 엔진 선택
# ---------------------------------------------------------------
# "v7"               : v7 해석 엔진만 (규칙 + 자체 TF-IDF 유사도, KURE 모델 미사용) - 기본값
# "poc"              : 기존 PoC (사전 → 오타 → KURE 임베딩)
# "v7_kure_replace"  : v7 규칙 + v7 TF-IDF 대신 KURE 임베딩
# "v7_kure_fallback" : v7 규칙 + v7 TF-IDF, 그래도 해석 불가일 때만 KURE 임베딩
# KURE 두 변형은 blind6에서 v7 단독 대비 +0.4%p로 효과가 없어 옵션으로만 둡니다 (docs/v7_kure_experiment.md)
ENGINE = os.getenv("CHATBOT_ENGINE", "v7")
if ENGINE == "v7":
    USE_EMBEDDING = False

# v7 엔진 폴더 (taas_nlu.py, thesaurus.txt, data/, SHA256.txt). 비교 패키지(../v7/)에서 그대로 복사한 동결본이며,
# 엔진 파일은 수정하지 않고 감싸서 씁니다. 기동 시 SHA256.txt와 대조합니다.
_HERE = os.path.dirname(os.path.abspath(__file__))
V7_DIR = os.getenv("CHATBOT_V7_DIR", os.path.join(_HERE, "engine", "v7"))
# v7에 넘길 지식·키워드: "loader"(data_loader로 읽은 DB/Oracle 데이터) / "v7_sources"(V7_SOURCES_DIR의 원본 사본, 비교용)
V7_DATA = os.getenv("CHATBOT_V7_DATA", "loader")
V7_SOURCES_DIR = os.getenv("CHATBOT_V7_SOURCES_DIR", os.path.join(
    _HERE, "..", "v7", "comparison_current_vs_claude_v7_vs_poc", "2_claude_v7_rules", "sources"))

# 예시 테이블 SOURCE가 이 접두어면 v7 예시(633 + 생성 2,707). v7+KURE 모드는 이것만, poc 모드는 이것을 뺀 나머지를 씁니다.
V7_EXAMPLE_PREFIX = "v7"
OOS_LABEL = "답변불가"   # '업무 밖'으로 표시된 생성 예시의 메뉴값. 임베딩 최상위가 이 부류면 fallback

# v7+KURE 모드의 KURE 임계값 (답변, 되묻기, 1·2등 차이). v7k_thresholds.json에 고정한 값을 씁니다.
# CHATBOT_V7K_SETTING으로 설정 이름(A 등)을 고르고, CHATBOT_V7K_THRESHOLDS="0.75,0.60,0.03"으로 현재 모드 값을 덮어쓸 수 있습니다.
_v7k = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "v7k_thresholds.json"), encoding="utf-8"))
V7K_SETTING = os.getenv("CHATBOT_V7K_SETTING", _v7k["setting"])
V7K_THRESHOLDS = {mode: tuple(v) for mode, v in _v7k[V7K_SETTING].items()}
if os.getenv("CHATBOT_V7K_THRESHOLDS") and ENGINE in V7K_THRESHOLDS:
    V7K_THRESHOLDS[ENGINE] = tuple(float(x) for x in os.environ["CHATBOT_V7K_THRESHOLDS"].split(","))

# ---------------------------------------------------------------
# 매칭 파라미터
# ---------------------------------------------------------------
# 사전 매칭에서 제외할 단어 (원본 소스의 제외 단어 + 너무 흔한 단어)
STOPWORDS = {"사고", "교통", "통계", "교통사고", "년", "현황", "건수", "알려줘"}

DICT_MIN_LEN = 2          # 이 글자 수 미만 키워드는 사전 매칭에서 제외
FUZZY_MIN_LEN = 3         # 오타 매칭은 3글자 이상 키워드만 (짧은 단어는 오매칭이 많음)
FUZZY_THRESHOLD = 0.85    # 자모 단위 편집거리 유사도 (0~1)

ANSWER_THRESHOLD = float(os.getenv("CHATBOT_ANSWER_THRESHOLD", "0.75"))   # 이상이면 바로 답변
CLARIFY_THRESHOLD = float(os.getenv("CHATBOT_CLARIFY_THRESHOLD", "0.60")) # 이상이면 되묻기
CLARIFY_MARGIN = 0.03     # 1등과 2등 점수 차가 이보다 작으면 답변 대신 되묻기
TOP_K = 3

FALLBACK_MESSAGE = (
    "현재 답변이 어려운 내용입니다. 조금씩 더 똑똑해지겠습니다! "
    "\n(문의) 033-749-5266, 5267, 5269, 5264"
)
CLARIFY_MESSAGE = "혹시 아래 중 찾으시는 내용이 있나요?"
