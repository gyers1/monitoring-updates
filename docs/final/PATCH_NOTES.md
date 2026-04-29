# Patch Notes

기록 규칙:
- 날짜는 `YYYY-MM-DD` 형식으로 기록
- 가능하면 버전 태그를 함께 기록
- 작업 내용, 검증 내용, 남은 제약을 분리해서 적는다

---

## 2026-04-29 / 유지보수 패치
### 작업 내용
- 대시보드 기사 정렬이 실제 원문 사이트 순서와 다르게 뒤집히는 문제를 수정
- `source_order` 필드를 추가해 크롤링 당시 원문 목록 순서를 DB/API/화면까지 보존
- 기존 DB는 앱 시작 시 `site_id + date_key + id ASC` 기준으로 `source_order`를 자동 보정하도록 마이그레이션 추가
- 대시보드 정렬 기준을 `최신 날짜순 -> 사이트 순서 -> 원문 순번`으로 변경하고, 보지 않은 기사는 순서 변경이 아니라 표시/필터 기준으로만 유지
- 환경부 보도·설명자료 기본 주소를 `https://www.mcee.go.kr/home/web/index.do?menuId=10598`로 변경
- 사이트 설정 동기화가 사용자 수정 URL을 기본 URL로 중복 복원하지 않도록 `이름 + 카테고리` 기준 보완 로직으로 수정
- 환경부 보도·설명자료의 예전 주소와 새 주소가 중복 존재하는 경우 예전 주소 항목을 비활성화하도록 보정

### 검증 내용
- `py_compile` 통과: `entities.py`, `models.py`, `repository.py`, `crawl_service.py`, `routes.py`, `main.py`
- `dashboard.html` inline script `node --check` 통과
- `source\tray_start.bat --check-only` 통과
- 환경부 새 URL 수집 테스트 성공, 최신 보도자료 10건 확인
- 대한민국 관보와 국회일정의 저장 순서가 크롤러 원문 순서와 일치하는지 확인
- 환경부 old/new URL 중복 상태 임시 DB 테스트 통과
- `git diff --check` 통과

### 현재 제약
- 기존 DB의 `source_order`는 과거 수집 시점의 실제 DOM 순서를 별도로 저장하지 않았기 때문에 `id ASC` 기반으로 보정
- 향후 재수집되는 기사는 크롤러가 반환한 원문 순서가 그대로 `source_order`에 저장됨

## 2026-03-20 / v2026-03-20-10-40
### 작업 내용
- 오버뷰와 카테고리 상세 목록의 기사 정렬을 `보지 않은 기사 우선 -> 최신 수집 순`으로 통일해, 빨간 안읽음 기사가 접힌 영역 아래로 밀리지 않도록 조정
- 앱 시작 후 GitHub의 최신 승인 릴리스를 확인하고, 새 승인 버전이 있을 때만 `지금 업데이트 / 나중에` 팝업을 띄우는 흐름 추가
- 승인 팝업에서 바로 기존 업데이트 실행을 연결해 설정 화면으로 다시 이동하지 않아도 업데이트가 가능하도록 정리
- `publish_release.ps1`를 `test`/`approved` 채널 방식으로 개편해, 테스트 업로드는 prerelease로 올리고 승인 시 같은 태그를 최신 정식 릴리스로 승격할 수 있도록 변경
- 승인 릴리스에 `NOTICE:` 문구를 넣으면 사용자 팝업 본문에 같은 문구를 노출할 수 있도록 배포 흐름 정리
- 선택자 도우미의 날짜 선택 로직을 공통 조상 기반 방식에서 `열 인식 + 위치 인식 + 날짜 텍스트 검증` 방식으로 보강해, HUG/LHRI/MCEE 같은 목록에서 날짜 샘플에 번호·첨부·조회가 섞이는 문제를 줄이도록 수정
- pywebview 주입형 도우미와 iframe 도우미 모두 같은 날짜 인식 규칙을 쓰도록 정리하고, helper가 `:nth-child(...)` 선택자를 만들면 저장 시 raw 선택자 유지 체크가 자동으로 켜지도록 연계

### 검증 내용
- `routes.py` `py_compile` 통과
- `dashboard.html` 인라인 스크립트 `node --check` 통과
- `source\\tray_start.bat --check-only` 통과
- 브라우저 평가로 `compareArticlesForDisplay()`가 `안읽음 우선 -> 최신순`으로 정렬되는 것 확인
- 브라우저 평가로 승인 업데이트 팝업이 버전/문구/릴리스 링크를 정상 표시하는 것 확인
- 빌드 산출물 `start_tray.bat --check-only` 통과
- 배포 ZIP 내부 raw `.py`는 `pyarmor_runtime` 1개만 남는 것 확인
- `selector_helper_inject.js` `node --check` 통과
- helper 적용 시 `keep_raw_selectors` 자동 체크 연동 확인

### 현재 제약
- 이번 버전부터 승인 릴리스 팝업이 동작하므로, 이미 배포된 이전 버전 사용자는 이번 버전까지는 기존 설정 화면 업데이트 방식으로 올려야 함
- 테스트 릴리스는 `latest` 대상에서 제외되므로 앱 내 수동 업데이트도 승인 릴리스 기준으로만 동작

## 2026-03-11 / v202603111526
### 작업 내용
- `NEW\source`, `NEW\release`, `NEW\build`, `NEW\docs\final` 기준 구조 정리
- `setup_source_env.bat` 복구 및 source 실행 환경 정상화
- `setup_build_env.bat`, `build_release.bat`, `build_release.ps1` 추가
- `publish_release.bat`, `publish_release.ps1` 추가
- `deploy_assets\start_tray.bat`를 공식 배포 런처 템플릿으로 분리
- `MonitoringDashboard.spec`를 새 build 구조에 맞게 정리
- staging -> PyArmor -> PyInstaller -> artifacts 흐름으로 새 build pipeline 구성
- `v202603111526` 암호화 배포 빌드 생성 완료

### 검증 내용
- `NEW\release\start_tray.bat` 실행 정상 확인
- `NEW\source\setup_source_env.bat` 정상 완료 확인
- `NEW\source\tray_start.bat --check-only`가 source launcher를 가리키는 것 확인
- `NEW\build\artifacts\v202603111526\MonitoringDashboard.zip` 생성 확인
- ZIP 안에 `.env`, `start_tray.bat`, `version.json`, `MonitoringDashboard.exe`, `_internal\config\settings.py` 포함 확인
- SHA256 확인: `3b1da2acd4f019d59459b84ea3296937da439b9f2ac608c8e586e708ac2e7367`
- 새 빌드 exe isolated launch 테스트 성공

### 현재 제약
- 현재 PyArmor는 trial이라 전체 폴더 암호화는 실패
- 그래서 현재 표준은 `main.py`, `webview_app.py`, `application/crawl_service.py` 부분 암호화
- GitHub Release 업로드는 아직 미실행
- 프로그램 내 업데이트 버튼의 end-to-end 검증은 아직 미실행

- 추가 반영: `routes.py` 정상본 복구 및 `interval_minutes` API 재반영
- 추가 반영: `dashboard.html` 정상본 복구, 로컬 날짜 기준 통일, `보지 않은 기사` 필터/기준선 재설정 추가
- 추가 반영: 카테고리별 간격 일괄 적용 UI, 1분 tick 카테고리 순차 수집, Windows 요약 알림 적용
- 추가 검증: `routes.py`, `main.py`, `application\crawl_service.py`, `infrastructure\notifiers\windows_notifier.py` `py_compile` 통과
- 추가 검증: `dashboard.html` inline script `node --check` 통과
- 추가 제약: 카테고리별 간격 UI는 현재 해당 카테고리 소속 사이트 전체의 `interval_minutes`를 일괄 갱신하는 방식
- 추가 반영: Windows 알림을 2분 30초 누적 버퍼 뒤 1회 요약 토스트로 보내도록 변경하고, 토스트 클릭 시 `notification-open` 인텐트를 통해 앱 메인 화면을 `오늘 + 전체 카테고리 + 보지 않은 기사` 상태로 전환하도록 연결
- 추가 반영: 설정 화면에 카테고리/사이트별 `최근 수집`, `다음 예정`, `최근 오류` 운영성 메타를 추가하고 `/api/logs`의 `site_id`를 함께 사용하도록 정리
- 추가 반영: 날짜 기준선이 빈 목록으로 먼저 만들어진 경우, 첫 비어있지 않은 결과를 자동으로 기준선으로 승격시켜 기존 기사 전체가 `보지 않은 기사`로 잘못 표시되지 않도록 보정
- 추가 반영: 설정 화면의 카테고리별 간격 입력 UI를 `알림/자동 갱신` 카드로 이동하고, 빠른 간격 버튼 + 직접 입력 방식으로 단순화

---

## 템플릿
### YYYY-MM-DD / vTAG
### 작업 내용
- 

### 검증 내용
- 

### 현재 제약
- 

## 2026-03-13 / v2026-03-13-08-49
### 작업 내용
- `WindowsNotifier`를 60초 요약 버퍼 기준으로 조정하고, AppUserModelID/시작 메뉴 바로가기 준비와 실패 로그를 추가해 윈도우 토스트 전제 조건을 보강
- `notify-test` API가 실제 실패를 500 응답으로 돌려주도록 바꿔 설정 화면의 알림 테스트 결과를 정확히 표시
- 설정 > `알림/자동 갱신` 카드 설명을 모니터링 기준 문구로 교체하고, 상단 우측에 `전체 수집 간격` 드롭다운 + 직접 입력 + `일괄 적용` UI 추가
- 카테고리별 빠른 간격 버튼을 `10/20/30/40/50/60분`으로 확장
- 기본 사이트 간격을 20분으로 통일하고, 기존 DB가 전부 30분인 레거시 상태일 때만 1회성으로 20분으로 내려주는 마이그레이션 추가

### 검증 내용
- 예정

### 현재 제약
- 실제 윈도우 토스트 표시는 OS 알림 설정 상태에 영향을 받으므로, 코드 검증 외에 배포 앱에서 1회 수동 확인이 필요
## 2026-03-16
### 작업 내용
- `MonitoringDashboard.spec`에서 프로젝트 폴더 전체를 data로 싣던 구성을 제거하고, 템플릿/정적 파일/`sites.json`만 명시적으로 포함하도록 정리했다.
- 의존 패키지 수집을 `collect_all`에서 `collect_data_files + collect_dynamic_libs + collect_submodules + copy_metadata` 조합으로 바꿔 raw `.py` 포함을 줄였다.
- `build_release.ps1`에 배포 산출물 내부 raw `.py` 누출 검사 단계를 추가했다.
- 업데이트 복사 검증 기준 파일을 `_internal\\presentation\\api\\routes.py`에서 `version.json`으로 바꿨다.
- 루트 `.gitignore`를 추가하고, `source/.gitignore`를 보강해 빌드/실행 산출물과 로컬 상태 파일이 새 Git 저장소에 섞이지 않도록 정리했다.
- `build_release.ps1`이 빌드 때마다 `settings.py`, `dashboard.html`을 수정하지 않도록 바꿔 Git 작업 트리 오염을 줄였다.
- 업데이트 재시작 시 `start_tray.bat` 대신 GUI exe를 직접 다시 띄우도록 바꿔 검은 콘솔 창 깜빡임을 줄였다.
- 대시보드 업데이트 버튼에 전체 화면 진행 오버레이를 추가해, 다운로드/적용/재시작 상태가 더 명확하게 보이도록 정리했다.
- `webview_app.py`가 정적 JS 리소스를 `resource_dir` 기준으로 읽도록 바꿔 배치 런처 의존도를 줄였다.
- 버전 문자열 파서를 `v202603161021` 구형 형식과 `v2026-03-16-10-21` 신형 형식 모두 읽도록 보강했다.
- 대시보드 좌측 버전 표시는 하드코딩 fallback 대신 서버가 현재 런타임 버전을 HTML에 직접 주입하도록 바꿨다.
- 업데이트 적용기는 `apply_update.bat` 대신 숨김 `apply_update.ps1`을 사용하도록 교체해 종료 후 반복적으로 뜨던 검은 콘솔 창을 줄이는 방향으로 정리했다.
- 버전 해석 로직을 `config/versioning.py` 공용 모듈로 분리해 패키징 실행본에서 `main -> presentation.api.routes` 직접 import로 인한 시작 오류가 나지 않도록 정리했다.
- 운영 기본값을 `debug=False`, `sql_echo=False`로 정리해 사용자용 `tray.log`에 SQL 상세 로그가 계속 쌓이지 않도록 수정했다.
- `tray.log`는 회전 로그(기본 5MB, 백업 2개)로 바꾸고, 이미 과도하게 커진 단일 로그 파일은 시작 시 새로 만들도록 정리했다.
- `crawl_logs`는 기본 30일 보관 후 시작 시 자동 정리하고, 삭제가 발생하면 SQLite `VACUUM`으로 DB 파일도 함께 정리하도록 추가했다.
- 업데이트 적용기는 이제 설치 폴더를 그대로 덮지 않고, `.env`/DB/사용자 설정만 보존한 뒤 나머지 파일을 깨끗하게 교체하도록 변경했다.
- 패키징 spec에 로컬 패키지(`application`, `config`, `domain`, `infrastructure`, `presentation`) 서브모듈 수집을 명시적으로 추가해, 난독화 후 빌드에서도 `ModuleNotFoundError: infrastructure`가 나지 않도록 보정했다.
