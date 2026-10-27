# 챗봇 동작 흐름 — 질문 입력부터 답변 표시까지

기준: 브랜치 `v7-kure-eval`, 기본 엔진 `CHATBOT_ENGINE=v7` (2026-10-27).
줄 번호는 이 시점 코드 기준이라 코드가 바뀌면 달라질 수 있습니다.

## 0. 한눈에 보기
```
[브라우저 chat.html]
  입력 → ask() → POST /chat {"query": "...", "conectrIp": "WEB_UI"}
                     │
[서버 app.py]        ▼
  chat_api() ── MATCHER.match(질문) ──► [v7_adapter.V7Matcher]
                                           │ engine.analyze(질문)   ──► [engine/v7/taas_nlu.py]
                                           │   정규화 → 연도 → 업무 밖 → 부정 → 'A랑 B' 분리
                                           │   → 절마다: 사전 분할 → 오타 → 활용형 → 역할 슬롯 → 정리
                                           │   → (못 찾으면) 일반어 처리 → TF-IDF 유사도
                                           │ ◄── {label, menus, route, reason, suggest, trace}
                                           │ decide(): answer / clarify / fallback 로 변환
             ◄──────────────────────────── MatchResult
  build_response() : 안내 문구, 바로가기 주소(build_link)
  write_log()      : chatbot_log.db 에 기록
  ── JSON 응답 ──►
[브라우저] addBot() : 답변 문구 + 바로가기 버튼 / 되묻기 버튼
```

## 1. 서버가 뜰 때 (1회)
| 순서 | 위치 | 하는 일 |
|---|---|---|
| 1 | [config.py](../taas_chatbot_poc/config.py) | 환경변수 읽기. 엔진 `v7`, DB `sqlite`(taas.db), v7 엔진 폴더 `engine/v7` |
| 2 | [app.py:25](../taas_chatbot_poc/app.py#L25) `load_all()` | [data_loader.py](../taas_chatbot_poc/data_loader.py)가 taas.db(또는 Oracle)에서 지식 102건·키워드 2,568건·예시 질문을 읽음 |
| 3 | [app.py:26](../taas_chatbot_poc/app.py#L26) | v7 모드는 `USE_EMBEDDING=False`라 **KURE 모델을 불러오지 않음** |
| 4 | [app.py:27](../taas_chatbot_poc/app.py#L27) `build_matcher()` | [matcher.py:192](../taas_chatbot_poc/matcher.py#L192)에서 모드를 보고 `V7Matcher` 생성 |
| 5 | [v7_adapter.py:71](../taas_chatbot_poc/v7_adapter.py#L71) `V7Matcher.__init__` | ① `engine/v7/SHA256.txt`로 동결본 해시 확인 ② 2번에서 읽은 지식·키워드를 임시 CSV로 써서 v7 엔진에 넘김 ③ v7 엔진이 사전(키워드+동의어 463+메뉴명)과 TF-IDF 색인(키워드·예시 3,340·메뉴 설명)을 만듦 |
| 6 | [app.py:30](../taas_chatbot_poc/app.py#L30) | 메뉴명 → 지식 DB 행 사전(`KNOWLEDGE`) 생성. 안내 문구·링크에 사용 |
| 7 | [app.py:45](../taas_chatbot_poc/app.py#L45) | 로그 DB(chatbot_log.db) 테이블 준비 |

기동 로그에 `[v7] 동결 해시 일치`, `[v7] 엔진 v7 로드 (… 제한 메뉴 18개)`가 나오면 정상입니다.

## 2. 브라우저: 질문 보내기
[static/chat.html](../taas_chatbot_poc/static/chat.html)
1. 입력창에서 Enter → `submit` 이벤트 ([chat.html:149](../taas_chatbot_poc/static/chat.html#L149))
2. `ask(text)` ([chat.html:126](../taas_chatbot_poc/static/chat.html#L126)): 내 말풍선 표시 후
   `POST /chat`, 본문 `{"query": 질문, "conectrIp": "WEB_UI"}` ([chat.html:134](../taas_chatbot_poc/static/chat.html#L134))

## 3. 서버: /chat 진입
[app.py:146](../taas_chatbot_poc/app.py#L146) `chat_api()`
1. 질문 시각 기록
2. `MATCHER.match(질문)` → 4장
3. `build_response(결과)` → 6장
4. `write_log(...)` → 7장 (실패해도 답변은 나감)
5. JSON 반환

## 4. 해석: v7 엔진
[v7_adapter.py:173](../taas_chatbot_poc/v7_adapter.py#L173) `match()`가 `engine.analyze(질문)`을 부릅니다. 엔진 파일은 수정하지 않는 동결본입니다.

### 4-1. 문장 전체 단계 — [taas_nlu.py:336](../taas_chatbot_poc/engine/v7/taas_nlu.py#L336) `analyze()`
| 순서 | 단계 | 내용 | 여기서 끝나는 경우 (route) |
|---|---|---|---|
| ① | 정규화 | 소문자, 기호 제거, 표현 통일(따릉이→자전거, 안전띠→안전벨트, '형태벌'→'형태별' 등) | 빈 문장 → `빈 질문` |
| ② | 연도 처리 (L341) | '2023년' 등은 지우고 해석. 올해 이후 연도는 '올해'(실시간 없음), 두 해는 '연도별'(추세)로 바꿈 | |
| ③ | 업무 밖 (L350) | 면허 갱신·과태료·날씨·점심 등 표현이 있고 통계 요청 표현이 없으면 거절 | `업무밖` |
| ④ | 부정 대상 (L353) | '노인 아닌', '어린이 빼고' → 그 대상을 지우고 계속 | 남는 게 없으면 `되묻기` |
| ⑤ | 병렬 분리 (L361) | 'A랑 B', 'A하고 B', 'A, B'를 절로 나눔. 앞 절의 대상(노인·자전거 등)이 없는 절은 이어받음. '비교·차이' 문장은 나누지 않음 | |
| ⑥ | 절마다 해석 | 4-2 | 절 2개 이상에서 메뉴가 나오면 합쳐서 `복수(병렬)` (최대 3개) |
| ⑦ | 확인 규칙 | 한 글자 질문, '경상·부상'만 있는 질문 등은 확정하지 않음 | `되묻기` |
| ⑧ | 메뉴를 찾았으면 | 그대로 반환 | `사전` 또는 `슬롯` |
| ⑨ | 일반어만 있는 질문 | '교통사고 통계', '사고' → 주요 교통사고통계 | `포괄` |
| ⑩ | TF-IDF 유사도 (L397) | 글자 조각(2~3자) 겹침으로 가장 비슷한 메뉴. 1등 ≥ 0.40, 1·2등 차이 ≥ 0.02면 답. 1등이 '업무 밖' 예시면 거절. 금지 조합(예: 좌회전→우회전보행사고)은 거부 | `유사도` / `업무밖(유사도)` / `되묻기` |

### 4-2. 절 단위 단계 — [taas_nlu.py:415](../taas_chatbot_poc/engine/v7/taas_nlu.py#L415) `analyze_clause()`
| 순서 | 단계 | 내용 |
|---|---|---|
| ⓐ | 사전 분할 (DP, L258) | 공백을 무시하고 등록 키워드·동의어·메뉴명으로 문장을 나눔. **어절 시작에서 시작해 어절 끝·조사 앞에서 끝나야 인정** ('사고가'의 '고가' 같은 오매칭 차단) |
| ⓑ | 오타 보정 (L304) | 사전에 안 걸린 어절을 자모 편집거리 1 이내로 보정 ('사꼬'→'사고', '연쟝'→'연장') |
| ⓒ | 활용형 규칙 (L451) | 정규식 44개: '죽었'→사망사고, '최근 3년'→추세, '치고 도망간'→뺑소니운전 등 |
| ⓓ | 역할 슬롯 (L473) | 노인·어린이·자전거·나이·성별 × 운전/피해/보행/보호구역 판단. 예: 노인+운전 → 1당노인, 자전거를 친 차 → 2당자전거 |
| ⓔ | 부정·예시 처리 | 'A 아닌' → A 제외, 'X 같은 Y' → Y가 주제 |
| ⓕ | 정리 (L578 `resolve`) | 약한 수식어(지역별·연도별 등) 제거, 상하위 메뉴 정리(보행노인이 있으면 노인·보행 제거), **제한 메뉴가 하나라도 있으면 '답변불가'**, 최대 3개 |

### 4-3. 엔진이 돌려주는 값
```
{"label": "음주운전+과속", "menus": ["음주운전", "과속"], "route": "복수(병렬)",
 "reason": "", "suggest": [], "trace": {...해석 근거...}}
```
제한 메뉴·업무 밖·되묻기는 모두 `menus = ["답변불가"]`로 나오므로 `route`와 `reason`으로 구분합니다.

## 5. v7 결과 → 서버 공통 형식(MatchResult)
[v7_adapter.py:134](../taas_chatbot_poc/v7_adapter.py#L134) `decide()`
| v7 결과 | MatchResult | 화면 |
|---|---|---|
| 실제 메뉴가 있음 | `answer` (stage = `v7:경로`) | 안내 문구 + 바로가기 |
| 제한 메뉴로 '답변불가' | `answer` — trace에서 원래 제한 메뉴(1당보호장구 등)를 되찾아 그 안내 문구를 씀. 못 찾으면 '별도문의' | "개방하지 않는 정보" 문구, 링크 없음 |
| `되묻기` | `clarify` — v7이 준 후보(suggest) 중 제한 메뉴를 뺀 최대 3개 | 후보 버튼 |
| `업무밖`·`미응답`·`빈 질문` | `fallback` | "답변이 어려운 내용입니다" |

## 6. 응답 만들기
[app.py:85](../taas_chatbot_poc/app.py#L85) `build_response()`
- `answer`: 메뉴마다 [build_document](../taas_chatbot_poc/app.py#L57)로 안내 문구를 만듦
  (상세통계는 "해당 통계는 {DOCUMENT} 통계[통계분석 > 상세통계]에서 확인하실 수 있습니다.", 메뉴안내는 DOCUMENT 그대로)
  + [build_link](../taas_chatbot_poc/app.py#L68)로 바로가기 주소
  - 상세통계 `7146|음주운전` → `…/sta/acs/exs/typical.do?menuId=WEB_KMP_OVT_UAS_PDS&patternId=7146&searchWord=음주운전`
  - 메뉴안내 `라벨|/경로` → `https://taas.koroad.or.kr/경로`, `IS_URL_PROVIDE=0`이면 빈 값
- `clarify`: "혹시 아래 중 찾으시는 내용이 있나요?" + `candidates`
- `fallback`: 답변 불가 안내 문구 (config.FALLBACK_MESSAGE)

응답 키: 기존 `document, keyword_menu, information, is_url_provide, inference` + 추가 `status, tertiary_menu, match_stage, candidates, url`.

## 7. 로그
[app.py:116](../taas_chatbot_poc/app.py#L116) `write_log()` → `chatbot_log.db`의 `TAAS_CHATBOT_OPERT_EXC_HIST`
- 질문 원문, 정규화 문장, 안내 메뉴, 점수, 첫 답변 문구, 질문·답변 시각, 접속 식별값(`WEB_UI`, `EVAL_TEST` 등), 해석 경로, 후보 목록
- 운영 로그 테이블과 섞이지 않도록 별도 SQLite에 기록 (운영 DB는 읽기만 함)

## 8. 화면 표시
[chat.html:92](../taas_chatbot_poc/static/chat.html#L92) `addBot()`
- 안내 문구마다 말풍선 + `url`이 있으면 "바로가기 ↗" 버튼 (새 탭)
- `clarify`면 후보 메뉴 버튼. 누르면 그 메뉴 이름으로 다시 `ask()` → 사전에서 바로 잡혀 답변
- 상태·경로·점수는 주소에 `?debug=1`을 붙였을 때만 표시

## 9. 실제 예시 (v7 모드 실행 결과)
| 질문 | 엔진 해석 (trace 요약) | route | 최종 |
|---|---|---|---|
| 음주랑 과속 사고 | 절 분리: '음주'→음주운전, '과속 사고'→과속 | 복수(병렬) | answer: 음주운전, 과속 (바로가기 2개) |
| 헬멧 안 쓴 오토바이 사고 | 사전: 헬멧(1당보호장구, 제한), 오토바이사고(1당차종) → 제한 메뉴 우선 | 사전 | answer: 1당보호장구 → "개방하지 않는 정보", 링크 없음 |
| 좌회전 사고 | 사전에 걸린 것 없음 → 유사도 1등 우회전보행사고(0.57)가 금지 조합이라 거부 | 되묻기 | clarify: 교차로형태, 1당노인 |
| 점심 메뉴 추천 | 업무 밖 표현 '점심 메뉴' | 업무밖 | fallback |

## 10. 다른 엔진 모드에서 달라지는 곳
| 모드 | 달라지는 곳 |
|---|---|
| `poc` | 4~5장 대신 [matcher.py:169](../taas_chatbot_poc/matcher.py#L169) `SentenceMatcher.match()`: 공백 제거 부분문자열 사전 → 자모 오타 → KURE 임베딩 (기동 시 KURE 로드) |
| `v7_kure_fallback` | 4-1 ⑩에서 '해석 불가' 되묻기면 KURE 임베딩으로 한 번 더 판단 ([v7_adapter.py:156](../taas_chatbot_poc/v7_adapter.py#L156)) |
| `v7_kure_replace` | v7 TF-IDF(⑩)를 끄고, 메뉴를 못 찾으면 KURE 임베딩으로 판단 |

## 11. 알아 둘 점
- **되묻기 응답의 `match_stage`** 는 후보를 낸 단계를 그대로 씀 ([app.py:107](../taas_chatbot_poc/app.py#L107)): v7은 `v7:되묻기`, poc·KURE는 `embedding`.
- **한 질문에 한 가지만 묻는다고 가정함.** 'A랑 B'처럼 두 가지를 묻는 질문도 처리하지만(최대 3개), 뒤 절이 앞 절의 대상을 이어받아 생기는 오답은 고치지 않음.
  예: "서울 노인 운전자 사고랑 음주 사고"는 두 번째 절이 '노인 음주 사고'로 해석되고, 메뉴가 4개라 3개(시군구·1당노인·노인)로 잘리면서 음주운전이 빠짐.
  수정안(역할을 나타내는 말이 있거나 그 절만으로 메뉴가 안 나올 때만 이어받기)은 시제품으로 확인했고(개발용+blind1~5 1,567문항 결과 변화 0건), 필요해지면 v8로 분리해 적용.
- **로그에 질문 원문이 그대로 저장됨.** 실제 운영에서는 개인정보가 섞일 수 있으니 보관 기간·마스킹 기준이 필요함.
