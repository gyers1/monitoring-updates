# 웹사이트 모니터링 시스템

정부기관 웹사이트의 신규 게시물을 실시간 모니터링하여 대시보드로 확인하는 시스템

## 빠른 시작

```bash
# 가상환경 생성 및 활성화
python -m venv venv
venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 서버 실행
python main.py
```

브라우저에서 `http://localhost:8000` 접속

## 프로젝트 구조

```
├── config/           # 환경 설정
├── domain/           # 도메인 모델 및 인터페이스
├── application/      # 유스케이스 (비즈니스 로직)
├── infrastructure/   # 외부 시스템 연동 (DB, HTTP, Email)
├── presentation/     # API 및 UI
└── main.py           # 애플리케이션 진입점
```

## 기능

- 📊 일자별 뉴스 대시보드
- 🔔 키워드 기반 이메일 알림
- 🔄 30분 간격 자동 크롤링
- 📱 모바일 PWA 지원
