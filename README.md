# TAAS 챗봇 개선

TAAS(교통사고분석시스템) 챗봇이 사용자 질문을 알맞은 통계 메뉴로 안내하도록 해석 엔진을 개선하는 프로젝트입니다.
기존 챗봇의 `/chat` 응답 형식은 그대로 두고, 해석 엔진만 바꿔 끼울 수 있는 FastAPI 서버를 제공합니다.

- **기본 엔진: v7** — 키워드·동의어 사전, 오타 보정, 가해/피해 등 역할 규칙, 문자 n-gram TF-IDF 유사도.
  학습된 AI 모델 없이 동작합니다 (torch·GPU 불필요).
- **옵션: KURE-v1 문장 임베딩** — 기존 PoC 방식과, v7에 KURE를 붙인 두 변형을 설정으로 고를 수 있습니다.

## 결과 요약
같은 시험 질문(블라인드), 같은 채점 기준(안내 메뉴 집합이 정답과 같아야 정답)으로 비교했습니다.

| 엔진 | 블라인드1~6 (1,420문항) | 블라인드6 (260문항) |
|---|---:|---:|
| 현행 TAAS 챗봇 | 41.6% | 40.4% |
| 기존 PoC (사전 + 오타 + KURE) | 66.3% | 64.2% |
| **v7 (기본)** | 88.1%¹ | **88.8%** |
| v7 + KURE (두 변형) | — | 89.2% |

¹ 세트별로 당시 버전으로 잰 값. 블라인드6만 최종 v7을 고정한 뒤 처음 본 시험입니다.

- KURE를 붙여도 v7 대비 +0.4%p(1문항)라 기본 엔진은 v7로 정했습니다 → [docs/v7_kure_experiment.md](docs/v7_kure_experiment.md)
- 시험 질문과 정답표는 AI(Claude)가 작성했고 정답표는 담당자 검수 전입니다. 실제 이용자 질문으로 다시 확인할 예정입니다.

## 저장소 구성
| 경로 | 내용 |
|---|---|
| [taas_chatbot_poc/](taas_chatbot_poc/) | **실행하는 서버.** 실행 방법·엔진 모드·파일 설명은 [taas_chatbot_poc/README.md](taas_chatbot_poc/README.md) |
| [taas_chatbot_poc/engine/v7/](taas_chatbot_poc/engine/v7/) | v7 해석 엔진 동결본 (규칙 `taas_nlu.py`, 동의어 사전 `thesaurus.txt`, 예시 질문). 수정하지 않음 |
| [docs/](docs/) | [동작 흐름](docs/chatbot_request_flow.md), [v7 + KURE 실험 기록](docs/v7_kure_experiment.md) |
| [v7/](v7/) | v7을 만든 팀의 비교 패키지 (보고서·비교 스크립트, 참고용). 서버는 쓰지 않음 |

## 빠른 시작
```bash
cd taas_chatbot_poc
pip install -r requirements.txt
python import_data.py          # data/의 공단 데이터 → taas.db (최초 1회)
uvicorn app:app --port 8000    # 기본 v7 엔진
```
브라우저에서 http://127.0.0.1:8000/ 을 열면 채팅 화면이 나옵니다 (`?debug=1`을 붙이면 해석 경로·점수 표시).

**데이터는 저장소에 포함되어 있지 않습니다.** 공단 지식·키워드 데이터(`DOCUMENT_SET.csv`, `KEYWORD_SET.csv`)와
시험 질문 엑셀을 따로 받아 `taas_chatbot_poc/data/`에 두어야 합니다.
데이터 없이 기존 PoC 엔진만 시연하려면 `python create_mock_db.py` 후 `CHATBOT_ENGINE=poc uvicorn app:app`.

## 원칙
- 운영 챗봇과 공단 DB는 변경하지 않습니다 (Oracle은 읽기 전용, 로그는 별도 SQLite).
- v7 엔진 파일은 동결본이며 서버 기동 시 `SHA256.txt`로 확인합니다. 규칙을 고칠 때는 새 버전(v8)으로 분리합니다.
- 공단 원본 데이터와 평가셋은 공개 저장소에 올리지 않습니다.
