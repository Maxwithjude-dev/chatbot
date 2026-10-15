#!/usr/bin/env python3
"""회귀 테스트: 반드시 지켜야 할 사례 + 시험셋 정답률 하한
실행: python3 proto/test_regression.py   (실패 시 종료 코드 1)
"""
import os, sys, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from taas_nlu import Engine
from evaluate import judge, role_flip

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
e = Engine(os.path.join(ROOT, "sources"), examples_csv=os.path.join(ROOT, "data", "example_questions.csv"),
           aug_csv=os.path.join(ROOT, "data", "example_questions_aug_v2.csv"))

MUST = [  # (질문, 기대 라벨) — 역할 반전·띄어쓰기·복수·제한·업무밖 대표 사례
    ("노인 운전자", "1당노인"), ("노인운전자", "1당노인"), ("노인 보행자", "보행노인"), ("노인 사고", "노인"),
    ("자전거 피해자", "2당자전거"), ("자전거 운전자 사고", "1당자전거"), ("자전거 타다 차에 치인 사고", "2당자전거"),
    ("스쿨 존 사고", "어린이보호구역"), ("어린이 보행 사고", "보행어린이"), ("사상자 연령대", "사상자연령대"),
    ("음주랑 과속 사고", "음주운전+과속"), ("서울 음주운전 사고", "시군구+음주운전"),
    ("헬멧 안 쓴 오토바이 사고", "답변불가"), ("남녀 사고 비율", "답변불가"), ("오늘 사고 현황", "답변불가"),
    ("운전면허 갱신 어디서 해요", "답변불가"), ("점심 메뉴 추천", "답변불가"), ("음주운전 처벌 기준이 뭐예요", "답변불가"),
    ("기타 보고서", "기타 보고서"), ("이번 주 사고", "답변불가"), ("비교", "답변불가"),
    # 2026-10-14 독립 검수(B3) 지적 사례
    ("2023년 교통사고 통계", "주요 교통사고통계"), ("2023년도 월별로 사고 어떻게 되나요", "월"), ("횡단보도 사고", "보행"),
    ("횡단보도 아닌 데로 건너다 난 사고", "횡단보도외횡단중"), ("자전거를 친 차 사고", "2당자전거"), ("차가 자전거를 친 사고", "2당자전거"),
    ("자전거가 사람을 친 사고", "1당자전거"), ("최근 3년 사고", "추세"), ("사고 없는 지역", "시군구"), ("점심 뭐 먹을까", "답변불가"),
    ("저녁 메뉴", "답변불가"), ("점심시간 사고", "시간"), ("택시 호출", "답변불가"), ("택시 사고", "1당차량용도"),
    ("작년 대비 올해 사고 증감", "추세"), ("고령 운전자 면허 반납", "답변불가"), ("음주운전 말고 과속", "과속"),
    ("내가 넣은 문의 확인", "나의민원"), ("어린이 부상", "어린이"),
    # 2026-10-14 2차 검수 탐침
    ("아이디 찾기", "답변불가"), ("자전거한테 치인 사고", "1당자전거"), ("자전거 타다 차에 치인 사고", "2당자전거"),
    ("사고율 높은 지역", "시군구"), ("일본이랑 사고율 비교", "OECD 회원국 교통사고 비교"), ("사고율 뜻", "용어정리"),
    ("보행자 연령별 사고", "사상자연령대"), ("몇시까지 해?", "답변불가"), ("사고 위치 지도로 찍어서 볼 수 있어?", "사고분석"),
    ("2당 차죵 통계", "답변불가"), ("어린이 빼고 보행자 사고", "보행"), ("경로당 근처 노인 보호구역 사고", "노인보호구역"),
    ("자동차 사고", "주요 교통사고통계"), ("교통사고 건수 알려줘", "주요 교통사고통계"), ("내 사고 기록 조회", "답변불가"),
    ("사고 제일 적은 시", "시군구"), ("2022년과 2023년 비교", "추세"), ("사고 처리 절차", "답변불가"), ("경운기 사고", "1당차종"),
    ("경찰서별 사고", "경찰서"), ("어린이 사망자 수가 매년 줄고 있나요?", "어린이"), ("권한 신청 절차", "권한신청"),
]
ROUTE_MUST = [  # 확정 안내 대신 되묻기여야 하는 사례 (라벨은 답변불가, 경로 '되묻기')
    "경상 사고", "음주운전 아닌 사고", "좌회전 사고", "비", "노인 아닌 운전자", "데이터 다운로드",
]
fail = 0
for q, exp in MUST:
    got = e.analyze(q)["label"]
    if judge(exp, got) != "정답":
        print(f"FAIL  {q!r}: 기대 {exp} / 결과 {got}"); fail += 1

for q in ROUTE_MUST:
    r = e.analyze(q)
    if r["route"] != "되묻기":
        print(f"FAIL  {q!r}: 되묻기 기대 / 결과 {r['label']} ({r['route']})"); fail += 1

FLOORS = {"data/eval_dev.csv": 0.97, "data/blind/blind1_set.csv": 0.97, "data/blind/blind2_set.csv": 0.95,
          "data/blind/blind3_set.csv": 0.95, "data/blind/blind4_set.csv": 0.87, "data/blind/blind5_set.csv": 0.90, "data/blind/blind6_set.csv": 0.88}
for f, floor in FLOORS.items():
    rows = list(csv.DictReader(open(os.path.join(ROOT, f), encoding="utf-8-sig")))
    labs = [e.analyze(r["질문"])["label"] for r in rows]
    acc = sum(judge(r["정답메뉴"], l) == "정답" for r, l in zip(rows, labs)) / len(rows)
    flips = sum(role_flip(r["정답메뉴"], l) for r, l in zip(rows, labs))
    status = "OK " if acc >= floor and flips == 0 else "FAIL"
    if status == "FAIL": fail += 1
    print(f"{status} {f}: 정답률 {acc:.1%} (하한 {floor:.0%}), 역할반전 {flips}")
print("PASS" if not fail else f"{fail}건 실패")
sys.exit(1 if fail else 0)
