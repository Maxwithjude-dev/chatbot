#!/usr/bin/env python3
"""TAAS 챗봇 문장 해석 프로토타입 v2 (표준 라이브러리 + scikit-learn, 외부 전송 없음)

처리 순서
 0. 정규화              : 소문자·기호 제거·공백 정리
 1. 업무 밖 판정         : 절차·법률·잡담 표현이 있고 통계 요청 표현이 없으면 '답변불가(업무 아님)'
 2. 병렬 구문 분리       : 'A랑 B', 'A하고 B', 'A, B' → 절별로 해석 후 합침. 앞 절의 대상(자전거·노인 등)을
                          생략한 절은 이어받음. 비교 구문('A랑 B 비교')은 나누지 않음
 3. 사전 분할(DP)        : 공백을 무시하고 등록 키워드 + 동의어 사전으로 분할.
                          키워드는 어절 시작(또는 앞 키워드 바로 뒤)에서 시작, 어절 끝·조사·꼬리말 앞에서 끝나야 인정.
                          여러 어절에 걸친 키워드는 어절 시작에서만 시작 (예: '사망자 정의'→'자정' 차단)
 4. 오타 보정            : 덮이지 않은 어절을 자모 편집거리 1로 보정. 2음절은 첫 음절이 같고 일상어가 아닐 때만
 5. 어간 규칙            : 활용형 표현(죽었, 뒤집어진, 얼어서, 면허 취소된, 달마다 …) → 메뉴
 6. 역할·조건 슬롯        : 노인/어린이/자전거/나이/성별 × 운전·피해·보행·보호구역
 7. 정리                 : 약한 수식어 제거, 상하위 메뉴 정리, 제한 속성이 붙으면 '답변불가'
 8. 의미 유사도 대체      : 그래도 없으면 문자 n-gram 유사도. 임계값 미만이면 되묻기(후보 제시)
"""
import datetime, csv, os, re, unicodedata, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RESTRICTED_PATTERNS = ("개방하고 있지 않은", "보유하고 있지 않습니다", "개인정보보호 사유", "실시간 정보는 보유")

# ---------------------------------------------------------------- 자모
CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = ["ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ", "ㅙ", "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ"]
JONG = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")


def to_jamo(s):
    out = []
    for ch in s:
        c = ord(ch) - 0xAC00
        if 0 <= c < 11172:
            out.append(CHO[c // 588]); out.append(JUNG[(c % 588) // 28])
            if c % 28: out.append(JONG[c % 28])
        else:
            out.append(ch)
    return out


def lev(a, b, cap=2):
    if abs(len(a) - len(b)) > cap: return cap + 1
    prev2 = None; prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b); best = cur[0]
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
            best = min(best, cur[j])
        if best > cap: return cap + 1
        prev2, prev = prev, cur
    return prev[-1]


# ---------------------------------------------------------------- 어휘
PARTICLES = sorted(("은 는 이 가 을 를 에 에서 에서의 의 로 으로 와 과 랑 이랑 하고 도 만 별 별로 별의 에는 에도 에선 중 때 들 등 "
                    "인 이나 나 까지 부터 보다 처럼 에서는 에서도 으로는 로는 엔 분들 분 님 님들 내 내의 별로는 이고 이며 들의 들이 들은 쯤 정도 마다 하다 하는 한 하던 해서 할 했던 하다가 했는데 하면 했을 중인 하고서 한테").split(),
                   key=len, reverse=True)
FILLERS = {"사고", "교통사고", "통계", "현황", "건수", "자료", "정보", "관련", "데이터", "사고통계", "교통", "발생", "발생건수",
           "통계자료", "수치", "숫자", "비율", "순위", "비중", "추정", "메뉴", "기능", "서비스", "사이트", "페이지"}
GENERIC = {"자동차", "차", "차량", "전국", "전체", "총", "알려줘", "보여줘", "알려주세요", "보여주세요", "우리나라", "한국", "국내", "몇", "얼마나", "건수", "발생"}
ONECHAR_BLOCK_PREV = {"이번", "지난", "다음", "저번", "매", "한", "몇", "일"}
FUZZY_STOP = set(("경찰 경찰서 예전 차이 보다 정도 경우 우리 어디 얼마 무슨 정말 요즘 최근 이번 지난 다음 그냥 혹시 좀 많이 같이 이거 그거 저거 "
                  "여기 거기 어떤 언제 누가 무엇 뭐가 가요 해요 내요 돼요 봐요 와요 줘요 나요 알려 보여 보고 있어 없어 싶어 하는 하고 "
                  "해서 하면 했던 되는 된 중 분들 사람 안내 설명 방법 기능 서비스 메뉴 사이트 페이지 이후 이전 지표 설치 기간 이상 "
                  "이하 미만 초과 기준 관련 대한 위한 통한 따른 기능은 지역 우리시 전국 작년 올해 내년 매년 이용 사용 흐름 경향 상황 내용 결과 원인 분포 구분 전반 단위 등급 비교 차이 나눠 따로 같이 자료 상태 사상자 사망자 피해자 운전자 피해차 상대차 내차 우리차").split())
VERB_END = ("요", "다", "까", "지", "죠", "네", "고", "서", "면", "니", "자", "게", "데", "는", "은", "던", "된", "한")
SLOT_VOCAB = ["노인", "고령", "어르신", "어린이", "아동", "자전거", "보행자", "보행", "운전자", "피해자", "연령대", "나이대",
              "사상자", "사망자", "보호구역", "스쿨존", "실버존"]
# 지역명 축약에서 제외: 일반 낱말과 겹치거나 폐지된 옛 지명
REGION_STEM_BLOCK = set("연기 음성 장수 공주 진도 장성 원성 중원 영일 제원 명주 승주 금릉 영풍 선산 옥구 천원 춘성 진양 여천 대천 송탄 동해 고성 보은 화성 성주 상주 영동 청원".split())
# 다른 주제가 있으면 버리는 약한 수식어 (표현 기준)
WEAK = {"기준", "매년", "해마다", "연도", "연도별", "지도", "지도로", "지도에서", "gis", "관할", "동네", "지역별", "리포트", "추이",
        "증감", "늘고", "줄고", "보고서", "사망률", "치사율", "사고률", "사고율", "시군구", "시군구별", "시도", "시도별", "우리시",
        "우리구", "인구", "사고현황", "요청", "신청", "추계", "겨울철", "여름철", "봄철", "가을철", "계절", "휴가철", "연휴", "taas", "타스", "책자", "통계보고서", "기타"}

PROC_RE = re.compile("|".join([
    "갱신", "재발급", "발급", "예약", "납부", "납입", "과태료", "범칙금", "벌점", "벌금", "처벌", "형량", "합의금", "합의",
    "보험료", "보험 ?접수", "보험 ?처리", "보험금", "보험 ?(싸게|가입|드는)", "면허 ?시험", "시험 ?일정", "시험장", "(^| )학원", "운전 ?연수", "연습", "교육 ?신청",
    "신고", "고장", "노선", "날씨 ?어때", "막히", "막혀", "정체", "통행료", "주차", "대리운전", "자동차세", "세금", "번호판",
    "검사 ?예약", "정기검사", "추천", "맛집", "안녕", "^하이", "고마", "감사합니다", "감사해요", "반가", "누구야", "너는 ?누구",
    "심심", "증명서", "(면허|자격|서류|준비물)\\S{0,3} ?필요", "어떻게 ?해야", "비밀번호", "로그인", "회원 ?가입", "이의 ?신청", "정비소", "개정 ?내용", "법 ?개정", "열차", "ktx", "지하철", "항공", "해야 ?하나요", "해야 ?돼", "제한 ?속도\\S{0,2} ?몇", "속도 ?제한\\S{0,2} ?몇",
    "몇 ?키로", "범인", "잡혔", "소송", "변호사", "판례", "과실 ?비율", "견인", "렌트 ?예약", "얼마예요", "얼마에요", "얼마인가요",
    "몇 ?시까지", "운영 ?시간", "영업 ?시간", "안 ?열려", "접속이? ?안", "먹통", "사고 ?처리 ?(절차|방법)", "아이디", "뭐 ?먹", "먹을까", "먹지", "(점심|저녁|아침) ?메뉴", "식당", "배고", "택시 ?(호출|잡|부르|불러|요금)", "카카오 ?t", "반납",
    "부동산", "아파트", "집값", "실업", "강수량", "강우량", "미세먼지", "주가", "환율", "코로나",
    "전화 ?번호", "연락처", "카메라 ?위치", "단속 ?(카메라 ?)?위치", "(경찰서|지구대|시험장|공단) ?(위치|주소|가는 ?길)", "(내일|모레|주말|오늘) ?날씨", "날씨 ?(알려|어때|어떄)",
]))
STAT_RE = re.compile("통계|건수|현황|몇 ?건|얼마나 ?(났|발생|일어|많|돼|되)|추이|비율|순위|많이 ?나|많아|많나|자료|데이터|수치|발생|사고 ?수|몇 ?명|증가|감소")
NONTAAS_STAT_RE = re.compile("부동산|아파트|집값|매매가|실업|강수량|강우량|미세먼지|주가|환율|인구 ?이동|출생|사망 ?원인|코로나|열차|ktx|항공|지하철")
COORD_RE = re.compile(r"(?:(?<=\S)(?:이랑|랑|하고|와|과)(?= )|\s(?:및|그리고|또는|이나)\s|,|/)")
COMPARE_RE = re.compile(r"비교|차이|대비|보다 |중 (누가|어디|어느)|구분|나눠|나누어")
STRONG_TERM_RE = re.compile(r"뜻|정의|의미|용어|무슨 ?말|계산 ?방법|산출 ?방법|어떻게 ?계산")
OLD_REPORT_RE = re.compile(r"옛날|예전|과거|지난 ?(연도|해)|구버전|오래된|예전에|나오던")
YEAR_RE = re.compile(r"(?<!\d)((19|20)\d{2} ?(년도|년)?( ?대)?|\d{2} ?년도)(?!\d)")
NEG_ENT_RE = re.compile(r"(노인|고령자?|어르신|어린이|아동|아이들?|초등학생|자전거|보행자|오토바이|이륜차|택시|버스|화물차|트럭)(은|는|이|가)? ?(아닌|아니고|말고|빼고|제외하고|제외한|제외)")
NEG_RE = re.compile(r"^(아닌|아니고|아니라|말고|빼고|제외|외에|외의|없이)")
ORPHAN_RE = re.compile(r"경상(?!남|북|도|권)|부상(?!자 ?연령)|중상")
SEM_VETO = [(re.compile(r"좌회전"), "우회전보행사고"), (re.compile(r"횡단보도(?! ?(외|밖|아닌|아니|없))"), "횡단보도외횡단중"),
            (re.compile(r"\d"), "1당연령대"), (re.compile(r"\d"), "도로연장"), (re.compile(r"다운|내려 ?받"), "분석리포트"), (re.compile(r"사이트|홈페이지|접속"), "어린이 TAAS"), (re.compile(r"없는|적은|안전한"), "무면허운전")]
ENTITY_RE = re.compile(r"자전거|노인|고령|어르신|어린이|아동|초등학생|보행자|오토바이|이륜차|화물차|택시|버스|킥보드")

# 어간·활용 규칙 (정규식 → 메뉴)
STEM_RULES = [
    (r"죽었|죽은|죽는|죽거나|숨지|숨진|숨졌|사망했|목숨", "사망사고"),
    (r"뒤집|전복|넘어졌|넘어진|굴렀", "사고유형"),
    (r"면허 ?(취소|정지)|면허 ?없", "무면허운전"),
    (r"일몰|해 ?(진|지고|떨어진) ?(뒤|후|다음)|어두워|어두운 ?(밤|시간)", "주야"),
    (r"달마다|매달|월마다|한 ?달 ?단위|월 ?단위", "월"),
    (r"하루하루|매일|날마다|일 ?단위|하루 ?단위|날짜별", "일"),
    (r"얼어서|얼어붙|얼었|빙판|미끄러", "노면상태"),
    (r"(잘|자주|많이) ?(나는|일어나는|발생하는) ?(지점|곳|데|구간|장소|교차로|도로)", "다발지분석"),
    (r"(사고|위험).{0,4}(잦은|많은) ?(곳|지점|구간)", "다발지분석"),
    (r"(설치|개선|생기|바뀌|도입).{0,8}(전|후|나서|뒤|전후).{0,12}(비교|줄었|늘었|효과|변화)", "전후사고비교분석"),
    (r"(설치|개선|도입) ?(전후|효과)", "전후사고비교분석"),
    (r"도로.{0,6}(km|킬로|길이|거리|연장)", "도로연장"),
    (r"(운전 ?면허|면허).{0,6}(가진|소지|보유|있는) ?(사람|인구|자|수)", "운전면허소지자수"),
    (r"(사고 ?당시|당시) ?(행동|상태|뭐)", "보행사상자사고시상태"),
    (r"(어린이|초등|애들|아이|키즈|학생).{0,24}(사이트|버전|홈페이지|전용|용 |taas)", "어린이 TAAS"),
    (r"보호구역(별|별로)?.{0,16}(지도|조회|찾아|검색|골라)", "보호구역사고조회"),
    (r"젖은|젖었|물기|축축", "노면상태"),
    (r"달아난|달아나|튀었|튄 ?사고|도망친|도망간|치고 ?(가|간|달|튀)", "뺑소니운전"),
    (r"(운전|면허).{0,4}(한 ?지|딴 ?지|딴지|따고).{0,10}(얼마 ?안|안 ?된|안된|\d+ ?년|몇 ?년|금방)", "1당면허경과년수"),
    (r"(면허).{0,6}(딴|취득한|가진|소지|보유|있는).{0,4}(사람|인구|자 |수)", "운전면허소지자수"),
    (r"차끼리|차 ?대 ?차|차와 ?차|차량 ?간", "사고유형"),
    (r"세 ?갈래|네 ?갈래|갈래 ?길|삼거리|오거리", "교차로형태"),
    (r"도로 ?(등급|유형|종류|구분)", "도로종류"),
    (r"(데이터|자료|원자료|원본).{0,10}(받|요청|신청|구하|얻)", "자료요청"),
    (r"(데이터|시설물|정보|자료).{0,10}(같이|함께|겹쳐|결합|연계|합쳐).{0,10}(분석|보는|보기|놓고)", "융합분석"),
    (r"(주제|테마).{0,6}(깊게|깊이|심층|파고)|깊게 ?(파고|분석)", "주제별 심층분석"),
    (r"(그 ?외|그 ?밖|나머지|기타).{0,10}보고서", "기타 보고서"),
    (r"(우리 ?(시|군|구|지역)|지자체).{0,16}(전반|종합|한 ?번에|한눈에|전체)", "지자체 종합통계"),
    (r"인구 ?(추정|전망)|추정 ?인구|장래 ?인구", "추계인구"),
    (r"(몇 ?시|시간 ?대|어느 ?시간)", "시간"),
    (r"들이받|뒤에서 ?(박|받|부딪)|후미 ?추돌", "사고유형"),
    (r"(회원|가입|승인).{0,12}(승인|요청|조회 ?(가 )?안|안 ?(돼|되)|권한)", "권한신청"),
    (r"(스쿨 ?존|보호 ?구역|실버 ?존).{0,8}(지도|조회|찾아|위치별)", "보호구역사고조회"),
    (r"(이 ?(사이트|시스템|홈페이지)|여기|taas).{0,8}(뭐|무엇|어떤|소개|하는 ?곳)", "TAAS 소개"),
    (r"(시청|군청|구청|도청|지자체).{0,10}(종합|전반)", "지자체 종합통계"),
    (r"(애들|아이|어린이|학생).{0,16}(교육용|교육 ?자료|보여 ?줄)", "어린이 TAAS"),
    (r"(최근|지난) ?\d+ ?년|\d+ ?년 ?(간|동안)|(작년|전년|지난 ?해).{0,8}(대비|비교|보다)|올해.{0,8}(작년|전년)", "추세"),
    (r"(내가|제가|내|나의|저의|제) ?(넣은|한|신청한|보낸|접수한|남긴|올린|등록한) ?(문의|민원|질문|요청|신청)", "나의민원"),
    (r"(사고|사고율|사망률|치사율).{0,4}(없는|적은|많은|높은|낮은|안전한|위험한) ?(지역|동네|도시|시도|시군구|시|군|구)( |$)", "시군구"),
    (r"횡단보도 ?(외|밖|아닌|아니|없는)", "횡단보도외횡단중"),
    (r"(연도별|연간|해마다|매년|년간).{0,10}(변화|추이|흐름|증감|늘|줄)", "추세"),
    (r"(일본|미국|독일|영국|프랑스|외국|해외|선진국|다른 ?나라).{0,12}(비교|대비|보다|랑|와|과)|(비교|대비).{0,8}(일본|미국|독일|영국|외국|해외|선진국|다른 ?나라)", "OECD 회원국 교통사고 비교"),
    (r"(내|제|나의|저의) ?(교통)?사고 ?(기록|이력|내역|조회|확인)", "개인정보"),
    (r"(위험|사고).{0,10}예측|예측.{0,6}(위험|사고)|인공 ?지능|(^| )ai", "AI위험지역예측분석"),
]
STEM_RULES = [(re.compile(p), m) for p, m in STEM_RULES]


ALIASES = [(r"따릉이|타슈|어울링|누비자|공공 ?자전거|전기 ?자전거", "자전거"), (r"나이 ?드신|나이 ?많은|연세 ?(많|드)|노령층", "노인"),
           (r"안전띠", "안전벨트"), (r"(형태|유형|연도|요일|시간대|종류|지역|연령대|차종|선형|상태|용도|성별|경찰서|시군구|시도|월|일)벌", r"\1별"),
           (r"(노인|어르신|할머니|할아버지|어린이|아이|학생|운전자|보행자)분들", r"\1"), (r"스피드", "속도"), (r"초딩|초등학생", "초등학생"), (r"오른쪽으로 ?(꺾|돌|회전)|우측으로 ?(꺾|돌)", "우회전"),
           (r"왼쪽으로 ?(꺾|돌)|좌측으로 ?(꺾|돌)", "좌회전"), (r"탓스|타스|tass|taas", "taas"), (r"오픈 ?데이터", "오픈api")]
ALIASES = [(re.compile(p), r) for p, r in ALIASES]


def norm(q):
    q = unicodedata.normalize("NFC", q).lower()
    for rx, rep in ALIASES:
        q = rx.sub(rep, q)
    q = re.sub(r"[^0-9a-z가-힣&,/\s]", " ", q)
    q = re.sub(r"\s*([,/])\s*", r" \1 ", q)
    return re.sub(r"\s+", " ", q).strip()


def ns(s):
    return re.sub(r"\s+", "", s)


def lexkey(s):
    """사전 키: 질문 정규화와 같은 문자만 남기고 공백 제거"""
    return ns(re.sub(r"[^0-9a-z가-힣&]", "", unicodedata.normalize("NFC", s).lower()))


class Engine:
    VERSION = "v7"

    def __init__(self, src_dir, thesaurus_path=None, examples_csv=None, extra_examples=None,
                 use_thesaurus=True, use_slots=True, use_fuzzy=True, use_semantic=True, use_oos=True,
                 multi=True, sem_threshold=0.40, use_stems=True, use_coord=True, aug_csv=None, sem_margin=0.02):
        self.flags = dict(thesaurus=use_thesaurus, slots=use_slots, fuzzy=use_fuzzy, semantic=use_semantic, oos=use_oos,
                          multi=multi, stems=use_stems, coord=use_coord)
        self.sem_threshold = sem_threshold
        self.sem_margin = sem_margin
        self.aug_csv = aug_csv
        docs = list(csv.DictReader(open(os.path.join(src_dir, "DOCUMENT_SET.csv"), encoding="utf-8-sig")))
        self.docs = {d["TERTIARY_MENU"]: d for d in docs}
        self.restricted = {m for m, d in self.docs.items() if any(p in d["DOCUMENT"] for p in RESTRICTED_PATTERNS)}
        self.lex = {}
        for k in csv.DictReader(open(os.path.join(src_dir, "KEYWORD_SET.csv"), encoding="utf-8-sig")):
            if k["TERTIARY_MENU"] in self.docs:
                self.lex[lexkey(k["KEYWORD"])] = (k["TERTIARY_MENU"], "keyword")
        for m in self.docs:  # 메뉴 이름 자체 (키워드가 0개인 메뉴 대비)
            key = lexkey(m.replace("(구)", ""))
            if key and key not in self.lex: self.lex[key] = (m, "menu-name")
        self.thesaurus = []
        if use_thesaurus:
            for line in open(thesaurus_path or os.path.join(HERE, "thesaurus.txt"), encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#"): continue
                phrase, menu = [x.strip() for x in line.split("|")]
                assert menu in self.docs, menu
                key = lexkey(phrase)
                self.thesaurus.append((phrase, menu, key in self.lex))
                if key not in self.lex:
                    self.lex[key] = (menu, "thesaurus")
        for k, (m, src) in list(self.lex.items()):  # 지역명 '시/군/구' 생략형 (전주시→전주)
            if m == "시군구" and src == "keyword" and len(k) >= 3 and k[-1] in "시군구":
                stem = k[:-1]
                if len(stem) >= 2 and stem not in self.lex and stem not in FUZZY_STOP and stem not in REGION_STEM_BLOCK:
                    self.lex[stem] = (m, "region-stem")
        self.maxlen = max(len(k) for k in self.lex)
        self.fuzzy_targets = [(k, to_jamo(k)) for k in list(self.lex) + list(FILLERS) + SLOT_VOCAB if len(k) >= 2]
        self._sem = None
        if use_semantic:
            self._build_semantic(examples_csv, extra_examples or [])

    # ------------------------------------------------------------ 의미 유사도
    def _build_semantic(self, examples_csv, extra):
        from sklearn.feature_extraction.text import TfidfVectorizer
        texts, labels = [], []
        for k, (m, _) in self.lex.items():
            texts.append(k); labels.append(m)
        if examples_csv and os.path.exists(examples_csv):
            for r in csv.DictReader(open(examples_csv, encoding="utf-8-sig")):
                if r["메뉴"] in self.docs:
                    texts.append(norm(r["질문"])); labels.append(r["메뉴"])
        for q, m in extra:
            for mm in m.split("+"):
                if mm in self.docs:
                    texts.append(norm(q)); labels.append(mm)
        if self.aug_csv and os.path.exists(self.aug_csv):  # 생성 예시 (업무 밖 예시는 '__업무밖__' 부류)
            for r in csv.DictReader(open(self.aug_csv, encoding="utf-8-sig")):
                m = r["메뉴"]
                if m in self.docs: texts.append(norm(r["질문"])); labels.append(m)
                elif m == "답변불가": texts.append(norm(r["질문"])); labels.append("__업무밖__")
        for m, d in self.docs.items():
            texts.append(norm(d["DOCUMENT"] + " " + d["SUBMENU"] + " " + m)); labels.append(m)
        self._vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), sublinear_tf=True)
        self._X = self._vec.fit_transform(texts)
        self._labels = labels
        self._sem = True

    def semantic(self, q, k=4):
        v = self._vec.transform([q])
        sims = (self._X @ v.T).toarray().ravel()
        best = {}
        for i in sims.argsort()[::-1][:60]:
            m = self._labels[i]
            if m not in best: best[m] = float(sims[i])
            if len(best) >= k: break
        return sorted(best.items(), key=lambda x: -x[1])

    # ------------------------------------------------------------ 분할 (DP)
    def segment(self, tokens):
        S = "".join(tokens); n = len(S)
        tok_of = []; starts = set(); ends = set(); p = 0
        for ti, t in enumerate(tokens):
            starts.add(p); tok_of += [ti] * len(t); p += len(t); ends.add(p)
        INF = (10 ** 9, 0)
        # 상태 0: 어절 시작(또는 어절 끝) / 1: 키워드·꼬리말 직후 같은 어절 안 / 2: 모르는 글자 뒤
        best = [[INF] * 3 for _ in range(n + 1)]; back = [[None] * 3 for _ in range(n + 1)]
        best[0][0] = (0, 0)

        def relax(q, st, cost, prev):
            if cost < best[q][st]: best[q][st] = cost; back[q][st] = prev

        for i in range(n):
            at_start = i in starts
            for st in range(3):
                c = best[i][st]
                if c == INF: continue
                st_eff = 0 if at_start else st
                if st_eff != 1:
                    relax(i + 1, 0 if (i + 1) in ends else 2, (c[0] + 1, c[1]), (i, st, "UNK", S[i]))
                if st_eff in (0, 1):
                    for L in range(1, min(self.maxlen, n - i) + 1):
                        piece = S[i:i + L]; j = i + L
                        kind = "KW" if piece in self.lex else "FILL" if piece in FILLERS else None
                        if not kind: continue
                        if tok_of[j - 1] != tok_of[i] and not at_start: continue  # 어절을 넘는 키워드는 어절 시작에서만
                        if L == 1:
                            if not at_start: continue
                            ti = tok_of[i]; rest = tokens[ti][1:]
                            if rest and rest not in PARTICLES: continue
                            if ti > 0 and tokens[ti - 1] in ONECHAR_BLOCK_PREV: continue
                        relax(j, 0 if j in ends else 1, (c[0], c[1] + 1), (i, st, kind, piece))
                if st_eff == 1:  # 조사: 키워드·꼬리말 뒤, 어절 끝까지
                    for part in PARTICLES:
                        j = i + len(part)
                        if S.startswith(part, i) and j in ends and tok_of[j - 1] == tok_of[i]:
                            relax(j, 0, c, (i, st, "PART", part))
        if best[n][0] == INF: return [], S
        pieces = []; q, st = n, 0
        while q > 0:
            i, pst, kind, piece = back[q][st]; pieces.append((i, kind, piece)); q, st = i, pst
        pieces.reverse()
        return pieces, S

    # ------------------------------------------------------------ 오타 보정
    def fuzzy(self, token):
        """어절 전체와 조사를 뗀 형태를 모두 시도해 더 가까운 쪽을 고름"""
        forms = [token]
        for part in PARTICLES:
            if token.endswith(part) and len(token) - len(part) >= 2:
                forms.append(token[: -len(part)]); break
        if len(forms) > 1 and token[-1] in "은는이가을를에의로도만와과랑":
            forms = forms[1:]
        best = None
        for t in forms:
            k = self._fuzzy1(t)
            if k: return k
        return best

    def _fuzzy1(self, t):
        if len(t) < 2 or t in FUZZY_STOP or t in self.lex or re.fullmatch(r"\d+\S{0,2}", t): return None
        if len(t) == 2 and t.endswith(VERB_END): return None
        jt = to_jamo(t)
        cands = []
        for k, jk in self.fuzzy_targets:
            if abs(len(k) - len(t)) > 1: continue
            d = lev(jt, jk, 1)
            if d <= 1: cands.append((d, -len(k), k))
        if not cands: return None
        cands.sort(); k = cands[0][2]
        uniq = {c[2] for c in cands if c[0] == cands[0][0]}
        if len(t) >= 3 and len(k) >= 3: return k
        if len(t) == 2 and len(uniq) == 1 and len(k) >= 2 and t[0] == k[0] and self.lex.get(k, ("",))[0] not in ("시군구", "경찰서"):
            return k
        return None

    # ------------------------------------------------------------ 메인
    def analyze(self, question):
        q = norm(question)
        trace = {"norm": q}
        if not q:
            return self._out(["답변불가"], "빈 질문", trace)
        if YEAR_RE.search(q):  # 연도는 메뉴를 가르지 않음 (모든 통계가 연도 선택 가능) → 지우고 해석
            ys = [m.group(0) for m in YEAR_RE.finditer(q)]
            trace["year"] = ys
            nums = [int(re.match(r"\d+", y).group(0)) for y in ys]
            nums = [n if n >= 100 else (2000 + n if n < 50 else 1900 + n) for n in nums]
            if any(n >= datetime.date.today().year for n in nums): rep = " 올해 "      # 집계 전 연도 → 실시간 제한 안내
            elif len(ys) >= 2: rep = " 연도별 "                                          # 두 해 비교 → 추세
            else: rep = " "
            q = re.sub(r"\s+", " ", YEAR_RE.sub(rep, q, count=1)); q = re.sub(r"\s+", " ", YEAR_RE.sub(" ", q)).strip() or "사고"
        if self.flags["oos"] and ((PROC_RE.search(q) and not STAT_RE.search(q) and not re.search(r"권한", q)) or NONTAAS_STAT_RE.search(q)):
            trace["oos"] = (PROC_RE.search(q) or NONTAAS_STAT_RE.search(q)).group(0)
            return self._out(["답변불가"], "업무밖", trace, reason="TAAS 업무 아님")
        mneg = NEG_ENT_RE.search(q)
        if mneg:
            trace["negated_entity"] = mneg.group(1)
            q2 = re.sub(r"\s+", " ", NEG_ENT_RE.sub(" ", q)).strip()
            if q2: q = q2
            else: return self._out(["답변불가"], "되묻기", trace, reason="부정 표현", suggest=["주요 교통사고통계", "사고유형", "1당법규위반"])
        clauses = [q]
        if self.flags["coord"] and self.flags["multi"] and not COMPARE_RE.search(q):
            parts = [p.strip() for p in COORD_RE.split(q) if p and p.strip() and p.strip() not in (",", "/")]
            if len(parts) >= 2:
                ents = [set(ENTITY_RE.findall(p)) for p in parts]
                allents = set().union(*ents)
                parts = [(" ".join(sorted(allents)) + " " + p) if (not e and allents) else p for p, e in zip(parts, ents)]
                clauses = parts
        outs = [self.analyze_clause(cq) for cq in clauses]
        if len(clauses) > 1:
            trace["clauses"] = [(c, m) for c, (m, _) in zip(clauses, outs)]
            if sum(1 for m, _ in outs if m) >= 2:
                merged = []
                for m, _ in outs:
                    for x in m:
                        if x not in merged: merged.append(x)
                for _, sub in outs:
                    for k, v in sub.items():
                        trace.setdefault(k, []).extend(v if isinstance(v, list) else [v])
                return self._out(merged[:3], "복수(병렬)", trace)
            menus, sub = self.analyze_clause(q)
        else:
            menus, sub = outs[0]
        trace.update(sub)
        if trace.get("negated_entity") and menus == ["답변불가"]:
            return self._out(["답변불가"], "되묻기", trace, reason="부정 표현", suggest=["1당연령대", "주요 교통사고통계", "사고유형"])
        if menus and len(q.split()) == 1 and len(ns(q)) == 1:  # 한 글자 질문은 확정하지 않고 확인
            return self._out(["답변불가"], "되묻기", trace, reason="한 글자 질문", suggest=menus)
        if not menus and trace.get("negated"):
            return self._out(["답변불가"], "되묻기", trace, reason="부정 표현", suggest=["주요 교통사고통계", "사고유형", "1당법규위반"])
        if not menus and ORPHAN_RE.search(q):
            return self._out(["답변불가"], "되묻기", trace, reason="부상 정도 메뉴 없음", suggest=["주요 교통사고통계", "사망사고", "사상자연령대"])
        if menus:
            return self._out(menus if self.flags["multi"] else menus[:1], "슬롯" if sub.get("slot") else "사전", trace)
        # 일반어만 있는 질문 ('교통사고 통계', '사고') → 주요 통계로 안내하고 세부 메뉴를 되물음
        toks = q.split()
        if toks and all(any(t == f or (t.startswith(f) and t[len(f):] in PARTICLES) for f in FILLERS | GENERIC) for t in toks):
            return self._out(["주요 교통사고통계"], "포괄", trace, suggest=["주요 교통사고통계", "시군구", "추세"])
        if self._sem:
            cand = self.semantic(q)
            trace["semantic"] = cand
            margin = cand[0][1] - (cand[1][1] if len(cand) > 1 else 0)
            if cand and cand[0][0] == "__업무밖__" and cand[0][1] >= self.sem_threshold:
                return self._out(["답변불가"], "업무밖(유사도)", trace, reason="TAAS 업무 아님", suggest=[c[0] for c in cand[1:]])
            cand = [c for c in cand if c[0] != "__업무밖__"] or cand
            margin = cand[0][1] - (cand[1][1] if len(cand) > 1 else 0)
            short = len(ns(q)) <= 2 and len(q.split()) == 1  # 한 단어 2글자 이하는 자동 안내하지 않음
            if cand and not short and cand[0][1] >= self.sem_threshold and margin >= self.sem_margin:
                top = cand[0][0]
                if any(rx.search(q) and top == vm for rx, vm in SEM_VETO):
                    trace["veto"] = top
                    return self._out(["답변불가"], "되묻기", trace, reason="유사도 거부", suggest=[c[0] for c in cand if c[0] != top])
                return self._out(["답변불가" if top in self.restricted else top], "유사도", trace, suggest=[c[0] for c in cand])
            return self._out(["답변불가"], "되묻기", trace, reason="해석 불가", suggest=[c[0] for c in cand])
        return self._out(["답변불가"], "미응답", trace, reason="해석 불가")

    def analyze_clause(self, q):
        trace = {}
        tokens = q.split()
        if not tokens: return [], trace
        pieces, S = self.segment(tokens)
        facets = []
        covered = [False] * len(S)
        for i, kind, piece in pieces:
            if kind == "KW":
                m, src = self.lex[piece]; facets.append((m, i, len(piece), src, piece))
            if kind in ("KW", "FILL", "PART"):
                for x in range(i, i + len(piece)): covered[x] = True
        trace["pieces"] = [(k, p) for _, k, p in pieces if k != "UNK"]
        if self.flags["fuzzy"]:
            pos = 0; spans = []
            for t in tokens: spans.append((pos, t)); pos += len(t)
            done = set()
            for ti, (p0, t) in enumerate(spans):
                if all(covered[p0:p0 + len(t)]) or ti in done: continue
                k = None
                if ti + 1 < len(spans) and len(t) >= 2 and len(spans[ti + 1][1]) >= 2 and not all(covered[spans[ti + 1][0]:spans[ti + 1][0] + len(spans[ti + 1][1])]):
                    k2 = self.fuzzy(t + spans[ti + 1][1])
                    if k2 and k2 in self.lex: k = k2; done.add(ti + 1)
                if not k:
                    k = self.fuzzy(t)
                    if not k:
                        for cut in range(len(t) - 1, 1, -1):
                            if t[:cut] in self.lex and self.fuzzy(t[cut:]) in FILLERS:
                                k = t[:cut]; break
                if k and k in self.lex:
                    m, src = self.lex[k]; facets.append((m, p0, len(k), "fuzzy", k))
                    trace.setdefault("fuzzy", []).append((t, k))
                    if k in SLOT_VOCAB: q = q.replace(t, k)
                elif k and k in SLOT_VOCAB:
                    q = q.replace(t, k); trace.setdefault("fuzzy", []).append((t, k))
        if self.flags["stems"]:
            for rx, m in STEM_RULES:
                mt = rx.search(q)
                if mt and m not in [f[0] for f in facets if f[4] not in WEAK]:
                    st0 = len(ns(q[:mt.start()]))
                    piece = "추이" if rx.pattern.startswith("(연도별") else m  # '매년 늘고' 류는 약한 수식어 (다른 주제가 있으면 버림)
                    facets.append((m, st0, max(2, len(ns(mt.group(0)))), "stem-pos", piece)); trace.setdefault("stem", []).append(m)
        if self.flags["slots"]:
            facets = self.slots(q, facets, trace)
        neg = [f for f in facets if f[3] != "slot" and NEG_RE.match(S[f[1] + f[2]:])]
        if neg:  # 'A 아닌/말고/빼고' → A 제외
            trace["negated"] = [f[0] for f in neg]
            facets = [f for f in facets if f not in neg and f[0] not in trace["negated"]]
        m_like = re.search(r" 같은 ", q)
        if m_like:  # 'X 같은 Y' → X는 예시, Y가 주제
            cut = len(ns(q[:m_like.start()]))
            after_kw = [f for f in facets if f[1] >= cut and f[3] != "slot"]
            if after_kw:
                facets = [f for f in facets if f[1] >= cut]; trace["예시수식어"] = q[:m_like.start()]
        menus = self.resolve(q, facets, trace)
        return menus, trace

    # ------------------------------------------------------------ 슬롯
    def slots(self, q, facets, trace):
        has = lambda pat: re.search(pat, q) is not None
        OLD = has(r"노인|고령|어르신|노령|노년|할머니|할아버지|시니어|65 ?세 ?이상")
        CHILD = has(r"어린이|아동|아이(?!디|폰|패드|템|콘|돌|스|러브|큐|티|피)|애들|초등|유아|미취학|꼬마|13 ?세 ?미만|12 ?세 ?이하")
        BIKE = has(r"자전거")
        PED = has(r"보행|걷|걸어|건너|횡단|행인")
        ZONE_C = has(r"스쿨 ?존|스쿨 ?죤|어린이 ?보호 ?구역|학교 ?앞|통학로")
        ZONE_O = has(r"실버 ?존|실버 ?죤|(노인|고령자?|어르신) ?보호 ?구역|경로당")
        DRIVER = has(r"운전|가해|낸 사고|사고 ?낸|사고 ?내|몰다|몰던")
        VICTIM = has(r"피해|당한|당하|당해|치인|치여|치이|받힌|받히|받혀|다친|다쳐|부상|사상자|사망자|죽은|숨진")
        AGE = has(r"나이|연령|몇 ?살|\d+ ?대\b|\d+ ?살|\d+ ?세|청소년|젊은|\d0대")
        new = list(facets)

        def drop(*ms):
            nonlocal new
            new = [f for f in new if f[0] not in ms]

        def add(m, tag):
            nonlocal new
            if m not in [f[0] for f in new]: new.append((m, 0, 10, "slot", m))
            trace.setdefault("slot", []).append(tag)

        if OLD:
            if ZONE_O: drop("노인", "1당노인", "보행노인"); add("노인보호구역", "노인+보호구역")
            elif PED and not DRIVER: drop("노인", "보행", "1당노인"); add("보행노인", "노인+보행")
            elif DRIVER and not VICTIM: drop("노인", "별도문의"); add("1당노인", "노인+운전자")
        if CHILD:
            if ZONE_C: drop("어린이", "보행어린이"); add("어린이보호구역", "어린이+보호구역")
            elif PED: drop("어린이", "보행"); add("보행어린이", "어린이+보행")
        BIKE_HIT = has(r"자전거(를|을)? ?(친|쳤|치고|들이받|박은|박았)|(차|차량|자동차|트럭|버스|택시|오토바이)(가|이)? ?자전거(를|을)")
        if BIKE:
            if has(r"자전거(한테|에게|에) ?(치인|치여|치이|받힌|받혀|부딪힌|부딪혀|다친)"):
                drop("2당자전거"); add("1당자전거", "자전거+가해(수동문)")
            elif BIKE_HIT and not has(r"자전거(가|이) |사람 ?(을 )?친|보행자"):
                drop("1당자전거"); add("2당자전거", "자전거+피해(능동문)")
            elif VICTIM and not has(r"가해"): drop("1당자전거"); add("2당자전거", "자전거+피해")
            elif has(r"가해|사고 ?낸|낸 사고|사람 ?(을 )?친"): drop("2당자전거"); add("1당자전거", "자전거+가해")
        if not new or all(f[0] == "별도문의" for f in new):
            if OLD and not AGE: add("노인", "노인(기본:사상자)")
            elif CHILD: add("어린이", "어린이(기본:사상자)")
        if AGE and not OLD and not CHILD:
            if has(r"피해.{0,6}운전자|당한 ?쪽 ?운전자|상대 ?운전자"): drop("1당연령대", "사상자연령대", "별도문의"); add("2당연령대", "나이+피해운전자")
            elif VICTIM or (PED and not DRIVER): drop("1당연령대", "별도문의", "보행"); add("사상자연령대", "나이+사상자")
            elif DRIVER or "1당연령대" in [f[0] for f in new]: drop("별도문의"); add("1당연령대", "나이+운전자")
        if has(r"성별|남녀|남자|여자|남성|여성"):
            target = "사상자성별" if has(r"사상자|사망자|다친|부상") else ("2당성별" if VICTIM else "1당성별")
            drop("1당성별", "2당성별", "사상자성별", "별도문의"); add(target, "성별")
        if has(r"피해 ?(차|차량)|상대 ?(차|차량)|당한 ?차"):
            if "1당차량용도" in [f[0] for f in new] or has(r"용도|사업용|영업용|자가용"): drop("1당차종", "1당차량용도"); add("2당차량용도", "피해차량+용도")
            elif "1당차종" in [f[0] for f in new] or has(r"차종|종류"): drop("1당차종"); add("2당차종", "피해차량+차종")
        if re.search(r"(^| )[가-힣]{1,3}\d?가?동( |$)", q) and not re.search(r"(자|이|행|활|운|노|공|변|작|진|발|출|자동|이동)동( |$)", q) and not [f for f in new if f[0] not in ("시군구",)]:
            drop("시군구"); add("법정동", "동 단위 지명")
        if VICTIM and has(r"차종|차량 ?종류|무슨 ?차|차 ?종류"):
            drop("1당차종", "1당차량용도"); add("2당차종", "차종+피해")
        if VICTIM and has(r"용도"):
            drop("1당차종", "1당차량용도"); add("2당차량용도", "용도+피해")
        if has(r"피해.{0,6}(면허 ?경과|운전 ?경력|경력)"):
            drop("1당면허경과년수"); add("2당면허경과년수", "경력+피해")
        if has(r"피해.{0,6}면허 ?종"):
            drop("1당면허종류"); add("2당면허종류", "면허종류+피해")
        if has(r"(사상자|사망자|다친|탑승자|숨진|죽은).{0,8}(벨트|헬멧|안전모|보호장구)"):
            drop("1당보호장구", "사망사고"); add("사상자보호장구", "보호장구+사상자")
        elif VICTIM and has(r"피해.{0,8}(벨트|헬멧|안전모|보호장구)"):
            drop("1당보호장구"); add("2당보호장구", "보호장구+피해")
        if has(r"지도|gis") and not has(r"좌표|위경도|gps") and "개인정보" in [f[0] for f in new]:
            drop("개인정보"); add("사고분석", "위치+지도")
        if has(r"(^| )밤") and has(r"(^| )낮"): drop("시간"); add("주야", "밤+낮")
        portal = has(r"(지역|지자체) ?(교통 ?안전 ?(정보)? ?)?포털")
        if has(r"안전") and has(r"지도") and not portal: drop("사고분석"); add("교통안전지도", "안전+지도")
        if portal:
            tab = "GIS분석" if has(r"gis|지도") else "분석리포트" if has(r"리포트") else "AI위험지역예측분석" if has(r"ai|예측") else "교통사고종합분석"
            drop("교통사고종합분석", "사고분석", "분석리포트", "AI위험지역예측분석", "교통안전지도", "개인정보", "시군구", "지자체 종합통계"); add(tab, "지역포털 탭")
        if has(r"우회전") and (PED or has(r"사람|행인")): drop("보행", "우회전보행사고"); add("우회전보행사고", "우회전+보행")
        if OLD_REPORT_RE.search(q) and has(r"보고서|책자|간행물|통계|자료"):
            for cue, menu in ((r"지역별", "(구)지역별 교통사고통계"), (r"요약", "(구)교통사고통계 요약"),
                              (r"자료집|분석 ?자료", "(구)교통사고 분석 자료집"), (r"비용", "(구)도로교통사고비용의 추계")):
                if has(cue): drop("시군구", "교통사고 통계 분석", "추세", "사고분석"); add(menu, "옛 보고서"); break
        if "주요 교통사고통계" in [f[0] for f in new] and not OLD_REPORT_RE.search(q): drop("(구)교통사고통계 요약")
        if has(r"어린이 ?taas|어린이 ?타스"): drop("어린이", "TAAS 소개"); add("어린이 TAAS", "어린이 TAAS")
        if "어린이 TAAS" in [f[0] for f in new]: drop("어린이", "TAAS 소개")
        pol = [f for f in new if f[0] == "경찰서"]
        if pol:
            new = [f for f in new if not (f[0] == "시군구" and any(f[1] + f[2] == p[1] for p in pol))]
        if len({f[0] for f in new}) > 1:
            new = [f for f in new if not (f[0] == "별도문의" and f[4] == "운전자")]
        return new

    # ------------------------------------------------------------ 정리
    HIER = {"보행노인": ["노인", "보행", "사망사고"], "보행어린이": ["어린이", "보행", "사망사고"], "1당노인": ["노인", "사망사고"],
            "어린이보호구역": ["어린이"], "노인보호구역": ["노인"], "2당자전거": ["1당자전거"], "사상자연령대": ["1당연령대"],
            "횡단보도외횡단중": ["사고유형", "보행"], "우회전보행사고": ["보행", "사망사고"], "교통안전지도": ["사고분석"],
            "자동차등록대수": ["1당차종"], "운전면허소지자수": ["별도문의", "등록인구", "무면허운전"], "추세": ["등록인구", "실시간"], "나의민원": ["별도문의", "권한신청", "자료요청"],
            "교통사고통계(경찰청)": ["경찰서", "교통사고 통계 분석"], "OECD 회원국 교통사고 비교": ["사고분석", "교통사고 통계 분석"],
            "주야": ["시간"], "분석리포트": ["교통사고 통계 분석"], "(구)교통사고 분석 자료집": ["교통사고 통계 분석", "사고분석"],
            "(구)지역별 교통사고통계": ["시군구", "교통사고 통계 분석"], "기타 보고서": ["교통사고 통계 분석"],
            "(구)도로교통사고비용의 추계": ["교통사고 통계 분석", "추계인구"], "(구)교통사고통계 요약": ["교통사고 통계 분석"],
            "교통안전지수": ["교통사고 통계 분석", "지자체 종합통계"], "교차로형태": ["도로형태"], "보행사상자사고시상태": ["보행"],
            "등록인구": ["시군구"], "추계인구": ["시군구", "등록인구"], "세대수": ["시군구"], "도로연장": ["시군구"],
            "사고반경분석": ["용어정리"], "GIS분석": ["사고분석"], "AI위험지역예측분석": ["시군구", "다발지분석", "교통사고정보 개방체계"],
            "교통사고통계(경찰청)": ["경찰서", "교통사고 통계 분석"], "추계인구": ["시군구", "등록인구"], "자료요청": ["권한신청"],
            "교통사고정보 개방체계": ["자료요청"], "지자체 종합통계": ["추세", "시군구"], "(구)교통사고 분석 자료집": ["교통사고 통계 분석", "사고분석", "자료요청"],
            "교통사고종합분석": ["지자체 종합통계"],
            "어린이": ["사망사고"], "노인": ["사망사고"], "보행": ["사망사고"], "대형사고": ["사망사고"]}
    ABSORB = {"다발지분석", "보호구역사고조회", "사고반경분석", "전후사고비교분석", "빅데이터분석"}

    def resolve(self, q, facets, trace):
        if not facets: return []
        if len({f[0] for f in facets}) > 1:
            strong = [f for f in facets if f[4] not in WEAK]
            if strong: facets = strong
        agg = collections.OrderedDict()
        for m, s, L, src, *_ in sorted(facets, key=lambda f: f[1]):
            if m not in agg: agg[m] = (s, L, src)
            else: agg[m] = (agg[m][0], max(agg[m][1], L), agg[m][2])
        ms = list(agg)
        if "용어정리" in ms and STRONG_TERM_RE.search(q):
            trace["meta"] = "용어정리 우선"
            return ["용어정리"]
        if "용어정리" in ms and len(ms) > 1: ms = [m for m in ms if m != "용어정리"]
        if "사고반경분석" in ms and ({"노인보호구역", "어린이보호구역"} & set(ms)) and not re.search(r"반경|\d+ ?(m|미터|km|킬로)", q):
            ms = [m for m in ms if m != "사고반경분석"]
        if "전후사고비교분석" in ms:
            ms = [m for m in ms if m == "전후사고비교분석" or m in self.restricted or m in self.ABSORB]
        for parent, kids in self.HIER.items():
            if parent in ms: ms = [m for m in ms if m not in kids]
        absorbers = [m for m in ms if m in self.ABSORB]
        if absorbers:
            def near(m):
                s0 = agg[m][0]
                return any(agg[a][0] - 6 <= s0 <= agg[a][0] + agg[a][1] for a in absorbers) or agg[m][2] in ("slot", "stem")
            ms = [m for m in ms if m in self.ABSORB or m in self.restricted or not near(m)]
        if any(m in self.restricted for m in ms):
            if len(ms) > 1: trace["restricted_dominant"] = [m for m in ms if m not in self.restricted]
            return ["답변불가"]
        if len(ms) > 3:
            keep = set(sorted(ms, key=lambda m: -agg[m][1])[:3]); ms = [m for m in ms if m in keep]
        return ms

    def _out(self, menus, route, trace, reason="", suggest=None):
        label = "+".join(menus) if menus else "답변불가"
        return {"label": label, "menus": menus, "route": route, "reason": reason, "suggest": suggest or [], "trace": trace}


if __name__ == "__main__":
    import sys
    e = Engine(os.path.join(HERE, "..", "sources"), examples_csv=os.path.join(HERE, "..", "data", "example_questions.csv"))
    for q in sys.argv[1:] or ["노인 운전자", "자전거 가해 사고랑 피해 사고 둘 다", "사망자 정의 30일 기준", "보행로인"]:
        r = e.analyze(q)
        print(q, "→", r["label"], "|", r["route"], {k: v for k, v in r["trace"].items() if k not in ("norm",)})
