# TAAS 챗봇 문장 단위 매칭 PoC

TAAS 챗봇 개선 서버입니다. 기존 `/chat` 응답 형식을 유지한 채 해석 엔진만 바꿔 끼울 수 있습니다.
**기본 엔진은 v7**(규칙·사전·슬롯 + TF-IDF 유사도)이며 KURE 모델 없이 동작합니다.

## 엔진 모드 (`CHATBOT_ENGINE`)
| 모드 | 동작 | KURE 모델 |
|---|---|---|
| `v7` (기본) | v7 해석 엔진만 | 불필요 |
| `poc` | 기존 PoC: 사전 → 자모 오타 → KURE 임베딩 | 필요 |
| `v7_kure_replace` | v7 규칙 + TF-IDF 대신 KURE | 필요 |
| `v7_kure_fallback` | v7 규칙 + TF-IDF, 해석 불가일 때만 KURE | 필요 |

KURE 두 변형은 blind6에서 v7 단독 대비 +0.4%p로 효과가 없어 옵션으로만 둡니다. 자세한 내용은 `../docs/v7_kure_experiment.md`.

## 폴더 구성
| 경로 | 역할 |
|---|---|
| app.py | FastAPI 서버, `/chat`(기존 응답 형식 호환), 채팅 화면(`/`), 로그 |
| config.py | 엔진 모드, DB 모드, 테이블명, 모델 경로, 임계값 |
| data_loader.py | 데이터 로딩 계층 (sqlite / oracle 전환) |
| matcher.py | poc 엔진(`SentenceMatcher`) + 모드별 매처 생성(`build_matcher`) |
| v7_adapter.py | v7 엔진 래퍼: 결과를 `/chat` 형식으로 변환, 기동 시 동결 해시 확인 |
| engine/v7/ | **v7 엔진 동결본** (taas_nlu.py, thesaurus.txt, data/ 예시 질문, SHA256.txt). 수정 금지 |
| v7k_thresholds.json | KURE 변형용 임계값 (blind6 채점 전에 고정한 설정 A) |
| static/chat.html | 채팅 화면 |
| import_data.py | `data/`의 공단 CSV·시험 엑셀 → `taas.db` + `data/eval/` 평가셋 |
| evaluate.py | 서버에 평가셋을 보내 채점 (현행·개선 챗봇 공통) |
| tune_v7_kure.py | KURE 변형 임계값 조정 (blind 세트는 거부) |
| create_mock_db.py | 목업 SQLite DB (poc 모드 시연용, v7 모드는 실제 데이터 필요) |
| data/ | 공단 원본 CSV, 시험 엑셀, eval/ 평가셋 — **git 제외**, 따로 받아서 둠 |

`engine/v7/`는 저장소 루트의 `v7/` 비교 패키지에서 그대로 복사한 파일입니다. `v7/`의 나머지(보고서·비교 스크립트)는 참고 자료이며 서버가 쓰지 않습니다.

## 실행 순서
```bash
pip install -r requirements.txt
python import_data.py                # data/ 원본 → taas.db (최초 1회, 데이터 바뀌면 다시)

# 기본 (v7 엔진, 모델 다운로드 없음)
uvicorn app:app --port 8000

# 다른 엔진으로 실행
CHATBOT_ENGINE=poc uvicorn app:app --port 8000

# 평가 (다른 터미널)
python evaluate.py --url http://127.0.0.1:8000/chat --eval data/eval/블라인드6.csv --out result_v7.csv
```
Windows PowerShell에서는 `$env:CHATBOT_ENGINE="poc"` 처럼 환경변수를 먼저 지정한 뒤 실행하세요.
실제 데이터 없이 poc 엔진만 시연하려면 `python create_mock_db.py` 후 `CHATBOT_ENGINE=poc`로 실행합니다.

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

## 알려진 단순화 (poc 엔진)
- 사전 매칭이 하나라도 되면 오타·임베딩 단계는 건너뜀
- 정확한 키워드와 오타 키워드가 섞인 질문은 정확한 쪽만 잡힘
- 띄어쓰기를 지우고 부분 문자열로 찾기 때문에 짧은 키워드가 단어 경계를 넘어 잡힘 (예: '사고가' → '고가')
