# procedure/app — 시술 현황 (Flutter · iOS)

계약: SPEC-004(`procedure/back` 계정 · 권한 · 통역 · 스냅샷 SSE). 아이폰 · 아이패드 한 앱 — 화면 짧은 변 < 600 이면 모바일 배치.

## 실행

```bash
# back: cd procedure && docker compose up --build   (:8700 · 0.0.0.0)
cd procedure/app
fvm flutter run -d <iOS 시뮬레이터> --dart-define=API_BASE=http://localhost:8700
fvm flutter run -d <기기>          --dart-define=API_BASE=http://<맥 IP>:8700
```

- 서버 주소는 로그인 화면 「서버 주소」 입력칸으로 바꾸고 기기에 저장된다(통역 = http→ws · https→wss + `/api/interpret`)
- 맥 IP · Apple 팀 ID · 번들 ID 는 레포에 쓰지 않는다

## 검증

```bash
fvm flutter analyze && fvm flutter test
fvm flutter build ios --no-codesign --dart-define=API_BASE=http://<맥 IP>:8700
# 화면 스크린샷(시뮬레이터): SHOT_DIR=<폴더> fvm flutter drive --driver=test_driver/integration_test.dart \
#   --target=integration_test/screens_test.dart -d <시뮬레이터> --dart-define=API_BASE=... --dart-define=SCENE=board|interpret --dart-define=SHOT=phone|tablet --dart-define=LOGIN_ID=<아이디> --dart-define=LOGIN_PW=<비밀번호>
```

## 서명 · TestFlight (사용자 맥)

번들 ID = App Store Connect 에 만든 값(Push Notifications 켬). 팀 ID · 번들 ID 는 레포에 쓰지 않는다(`Signing.xcconfig` 에만).

업로드 전 점검(mac-remote runbook-002 §1 을 이 앱에 맞춤):

| # | 항목 | 확인 |
|---|---|---|
| 1 | 1024 아이콘 알파 없음 | `sips -g hasAlpha ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-1024x1024@1x.png` → `no` |
| 2 | 로컬 네트워크 · 마이크 문구 | `ios/Runner/Info.plist` 의 `NSLocalNetworkUsageDescription` · `NSMicrophoneUsageDescription` |
| 3 | ATS | `NSAllowsLocalNetworking = true`(맥 IP http · ws) · `NSAllowsArbitraryLoads` 없음 |
| 4 | 수출 규정 | `Info.plist` `ITSAppUsesNonExemptEncryption = false`(Missing Compliance 안 뜸) |
| 5 | 서명 | `CODE_SIGN_STYLE = Automatic`(Debug/Release.xcconfig) · `DEVELOPMENT_TEAM` 은 `ios/Flutter/Signing.xcconfig` · Xcode Signing & Capabilities 에 Push Notifications 오류 없음 |
| 6 | 푸시 | `ios/Runner/Runner.entitlements` `aps-environment` — 내보내기(App Store Connect) 때 Xcode 가 production 으로 바꿈 · back 은 TestFlight 기기면 `APNS_ENV=production` |

절차:

1. `cp ios/Flutter/Signing.xcconfig.example ios/Flutter/Signing.xcconfig` → `DEVELOPMENT_TEAM` · `APP_BUNDLE_ID` 채움(gitignore · 커밋 금지)
2. 빌드 번호 +1 하고 ipa 만들기(같은 번호 재업로드는 거절):
   ```bash
   fvm flutter build ipa --release --dart-define=API_BASE=http://<맥 IP>:8700 --build-number=<이전 + 1>
   ```
   (서버 주소는 앱 로그인 화면 「서버 주소」로도 바꿀 수 있다 — 배포 뒤 `https://ccc.medisolveai.xyz`)
3. `build/ios/ipa/*.ipa` 를 Transporter 로 올리거나, `open build/ios/archive/Runner.xcarchive` → Organizer → Distribute App → App Store Connect → Upload(자동 서명)
4. App Store Connect → TestFlight → 처리 대기(5~30분) → **내부 테스터** 그룹에 빌드 배정(심사 없음)
5. 아이폰 · 아이패드 TestFlight 앱으로 설치 → 첫 실행: 로컬 네트워크 허용 → 서버 주소 확인 → 로그인 → 알림 허용 → (통역 처음 열 때) 마이크 허용

맥 쪽: 방화벽 8700 들어오기 허용 · 잠자기 막기(`caffeinate -dimsu`) · 공유기에서 맥 IP 고정 권장.

## 원장 호출 푸시 (SPEC-004 §5-1 · APNs 직접 · Firebase 0)

- 로그인 직후 알림 권한 요청 → 허용이면 기기 토큰 `POST /api/devices` · 로그아웃 때 `DELETE /api/devices/{token}` 먼저
- 알림을 누르면 payload `visitId` 룸 상세(꺼져 있던 앱 · 로그인 전 포함) · 앞에 있을 때도 배너 + 소리
- 알림 [수락](카테고리 `CALL` · 액션 `ACCEPT`) — 앱을 안 열고 백그라운드에서 `POST /api/calls/{callId}/accept`(`X-Accept-Source: push`) → 로컬 알림 「수락했어요 · <방>」/「수락 못 함 · <사유>」(누르면 룸 상세). 서버 주소 · 토큰은 `AppDelegate` 키체인(첫 잠금 해제 뒤 · 이 기기만)
- Push Notifications capability = `ios/Runner/Runner.entitlements`(`aps-environment`) · 팀 ID 는 `Signing.xcconfig` 에만

APNs 키 없이 시뮬레이터에서 가짜 알림:

```bash
xcrun simctl push <시뮬레이터> <번들 ID> tool/push_call.apns          # 누르면 visitId 룸 상세
xcrun simctl push <시뮬레이터> <번들 ID> tool/push_call_accept.apns   # 배너를 아래로 당기면 [수락]
# visitId · callId 는 실 판 값으로 바꿔 쓴다
```

## 앱 아이콘

- 원본 = `assets/icon/app_icon.svg`(32px 로고를 벡터로 다시 그림 — 바탕 `#2498BD` = ceramique primary · 흰 「C」 = Didot Bold 글리프 윤곽 · 위 5/32 · 높이 22/32 · 가로 가운데 15/32) · `assets/icon/app_icon_1024.png`(알파 없음)
- iOS AppIcon 전 크기 = 1024 PNG 를 줄여 `ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-*.png`(전부 RGB · 알파 없음). 알림 아이콘은 iOS 가 앱 아이콘을 쓴다
- 시뮬레이터에서 알림 아이콘이 옛것이면 SpringBoard 캐시 — `xcrun simctl spawn <시뮬레이터> launchctl stop com.apple.SpringBoard`
