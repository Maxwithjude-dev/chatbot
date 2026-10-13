# TAAS 챗봇 문장 단위 매칭 PoC

Oracle 없이 로컬에서 바로 돌려볼 수 있는 개선 챗봇 뼈대입니다. 모든 데이터는 더미입니다.

## 파일 구성
| 파일 | 역할 |
|---|---|
| config.py | DB 모드, 테이블명, 모델 경로, 임계값 설정 |
| create_mock_db.py | 목업 SQLite DB 생성 (키워드·지식 DB·사용자 사전·예시 질문) |
| data_loader.py | 데이터 로딩 계층 (sqlite / oracle 전환) |
| matcher.py | 매칭 파이프라인 (정규화 → 사전 → 자모 오타 → 임베딩) |
| app.py | FastAPI 서버, 기존 /chat 응답 형식과 호환 |
| evaluate.py | 평가 스크립트 (현행·개선 챗봇 공통) |
| eval_sample.csv | 평가셋 예시 |

## 실행 순서
```bash
pip install -r requirements.txt
python create_mock_db.py

# 1) 임베딩 없이 (규칙 매칭만) - 모델 다운로드 없이 바로 확인 가능
CHATBOT_USE_EMBEDDING=0 uvicorn app:app --port 8000

# 2) 임베딩 포함
CHATBOT_MODEL_PATH=/models/KURE-v1 uvicorn app:app --port 8000

# 평가 (다른 터미널)
python evaluate.py --url http://localhost:8000/chat --eval eval_sample.csv --out result_new.csv
```
Windows에서는 `set CHATBOT_USE_EMBEDDING=0` 처럼 환경변수를 먼저 지정한 뒤 실행하세요.

## 모델 비교 실험
모델 경로만 바꿔 서버를 띄우고 같은 평가셋으로 evaluate.py를 돌리면 됩니다.
- multilingual-e5 계열은 `CHATBOT_QUERY_PREFIX="query: "`, `CHATBOT_EXAMPLE_PREFIX="query: "` 지정
- 모델마다 유사도 분포가 달라서 `CHATBOT_ANSWER_THRESHOLD`, `CHATBOT_CLARIFY_THRESHOLD`를 평가셋으로 다시 맞춰야 공정한 비교가 됩니다.

## KURE-v2 (멀티벡터 모델) 사용
KURE-v2는 ColBERT 계열이라 `SentenceTransformer`가 아니라 `MultiVectorEncoder`로 불러옵니다.
sentence-transformers 6.x는 Python 3.10 이상, transformers 5.x가 필요하므로 현행 챗봇과 별도 가상환경을 권장합니다.
```bash
pip install -U "sentence-transformers>=6.0"
CHATBOT_MODEL_TYPE=multivector CHATBOT_MODEL_PATH=/models/KURE-v2 uvicorn app:app --port 8000
```
점수는 MeanMaxSim(0~1 근처)이라 dense 모델과 분포가 다릅니다. 임계값을 평가셋으로 따로 맞추세요.

## 현행 챗봇 평가
현행 서버 주소로 evaluate.py를 그대로 실행하면 됩니다. 현행 응답에는 메뉴명이 없어서
답변 문구를 지식 DB의 DOCUMENT와 대조해 메뉴를 역추적합니다 (같은 지식 DB를 써야 함).
요청 시 `--ip EVAL_TEST` 식별값이 로그에 남으니 운영 로그 분석 때 제외하세요.

## 평가셋 형식
`질문, 정답메뉴, 질문유형` 컬럼. 답변하면 안 되는 질문은 정답메뉴에 `답변불가`,
복수 의도 질문은 `음주운전|이륜차`처럼 `|`로 구분합니다. 질문유형은 쉼표로 여러 개 가능합니다.

## 공단 DB 수령 후 할 일
1. config.py의 TABLES를 실제 테이블명으로 교체
2. `CHATBOT_DB_MODE=oracle` 과 ORACLE_USER / ORACLE_PASSWORD / ORACLE_DSN 지정 (운영 DB는 읽기만 함)
3. 예시 질문은 목업 SQLite의 TAAS_CHATBOT_EXAMPLE_QUESTION에 계속 적재
4. 로그는 별도 SQLite(chatbot_log.db)에 기록됨

## 알려진 단순화 (PoC 범위)
- 사전 매칭이 하나라도 되면 오타·임베딩 단계는 건너뜀
- 정확한 키워드와 오타 키워드가 섞인 질문은 정확한 쪽만 잡힘
- 되묻기(status=clarify) 시 candidates를 버튼으로 보여주려면 화면 쪽 수정 필요
