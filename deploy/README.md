# EC2 배포 (v7 엔진, SQLite)

서버 한 대에 챗봇을 올리고 systemd로 상시 실행합니다. RDS는 쓰지 않습니다 (데이터·로그 모두 서버 안 SQLite).

| 항목 | 값 |
|---|---|
| 서버 | EC2 `taas-server` (Amazon Linux 2023), 사용자 `ec2-user` |
| 설치 위치 | `/home/ec2-user/chatbot` (저장소), `/home/ec2-user/chatbot/.venv` (가상환경) |
| 서비스 | `taas-chatbot` (systemd), 포트 8000 |
| 엔진 | `CHATBOT_ENGINE=v7` (KURE·torch 설치 안 함) |
| 데이터 | `taas_chatbot_poc/data/`의 `DOCUMENT_SET.csv`, `KEYWORD_SET.csv` — 저장소에 없으므로 직접 올림 |

## 처음 배포
로컬 PC의 Git Bash, 저장소 루트(`chat_bot_kure/`)에서 실행합니다.
```bash
KEY=~/.ssh/taaskey.pem            # 팀원에게 받은 키
HOST=ec2-user@3.38.187.227        # taas-server 공인 IP

# 1) 공단 데이터 올리기 (저장소에는 없음)
ssh -i $KEY $HOST "mkdir -p ~/chatbot/taas_chatbot_poc/data"
scp -i $KEY taas_chatbot_poc/data/DOCUMENT_SET.csv taas_chatbot_poc/data/KEYWORD_SET.csv $HOST:~/chatbot/taas_chatbot_poc/data/

# 2) 설치 스크립트 올리고 실행 (패키지 → 저장소 → 가상환경 → 적재 → 서비스)
scp -i $KEY deploy/setup_ec2.sh $HOST:~/
ssh -i $KEY $HOST "bash ~/setup_ec2.sh"            # 마지막에 HTTP 200 이면 성공
```
`main`에 아직 합치지 않은 코드를 올릴 때는 `ssh -i $KEY $HOST "BRANCH=v7-kure-eval bash ~/setup_ec2.sh"`.

3) 웹 포트 열기 — **허용할 IP만** 추가합니다 (보안그룹 `launch-wizard-3`, `sg-04bcdc52523ad3a6d`).
```bash
MYIP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id sg-04bcdc52523ad3a6d --protocol tcp --port 8000 --cidr $MYIP/32
```
4) 브라우저에서 `http://3.38.187.227:8000/` (해석 경로를 보려면 `?debug=1`)

## 코드 갱신
`main`에 합친 뒤:
```bash
ssh -i $KEY $HOST "bash ~/chatbot/deploy/setup_ec2.sh"
```
저장소를 최신으로 받고, 패키지·데이터를 다시 적재한 뒤 서비스를 재시작합니다.
공단 데이터가 바뀌면 1)의 `scp`로 CSV를 다시 올리고 같은 명령을 실행합니다.

## 운영 명령 (서버에서)
| 할 일 | 명령 |
|---|---|
| 상태 | `sudo systemctl status taas-chatbot` |
| 실시간 로그 | `sudo journalctl -u taas-chatbot -f` |
| 재시작 | `sudo systemctl restart taas-chatbot` |
| 질문 로그 DB | `~/chatbot/taas_chatbot_poc/chatbot_log.db` (질문 원문 포함 — 반출·보관 주의) |

기동 로그에 `[v7] 동결 해시 일치`가 보여야 합니다. `해시가 동결본과 다름` 경고가 나오면 `engine/v7/` 파일이 바뀐 것입니다.

## 주의
- 보안그룹: SSH(22)가 현재 `0.0.0.0/0`으로 열려 있음 → 우리 IP로 좁히기를 권장.
- 서버 공인 IP는 인스턴스를 중지·시작하면 바뀝니다. 고정하려면 탄력적 IP(Elastic IP)를 붙입니다.
- HTTPS·도메인은 아직 없음. 외부 공개 전에는 nginx + 인증서(또는 ALB) 구성이 필요합니다.
