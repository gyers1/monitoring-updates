# NEW docs final

이 폴더는 `C:\CODE\2. 보도자료 모니터링(260127 완성본)\NEW` 기준의 현재 운영 문서입니다.

현재 검증된 상태:
- `NEW\release\start_tray.bat` 실행 기준 정상
- `NEW\source\setup_source_env.bat` 정상
- `NEW\source\tray_start.bat`가 실제 source launcher(`venv_webview\Scripts\pythonw.exe`)를 가리키는 것 확인
- 새 배포 빌드 `v202603111526` 생성 완료
- 배포 ZIP, SHA256, manifest, release notes 생성 완료
- 새 빌드 exe의 isolated launch 테스트 성공
- GitHub 업로드와 앱 내 업데이트는 아직 실제 end-to-end 검증 전

문서 구성:
- `01_운영_기준.md`: 기준 폴더와 현재 공식 흐름
- `02_소스_실행_가이드.md`: source 실행 및 개발 환경 기준
- `03_배포_업데이트_현황.md`: build/publish/update 현재 상태
- `04_기존_문서_판정표.md`: 기존 docs 파일 판정 기록
- `05_유지보수_체크리스트.md`: 유지보수 우선순위와 점검표
- `06_배포_스크립트_가이드.md`: 새 build/publish 스크립트 사용법
- `PATCH_NOTES.md`: 회차별 변경 이력