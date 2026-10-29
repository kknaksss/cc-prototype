import AVFoundation
import Flutter
import UIKit
import UserNotifications

// 원장 호출 푸시(SPEC-004 §5-1) — APNs 직접(Firebase 0). Dart 와는 채널 "procedure/push" 하나로:
//   Dart → 앱: ready(눌러서 연 알림이 있으면 그 payload 를 돌려줌) · requestPermission · status · register · deviceName · deviceModel · appVersion
//             · installId(설치 단위 id · 키체인 — E2E batch 1 #1) · takeLink(앱을 연 ccc:// 링크 · #5)
//             · setAuth({base, token}) · clearAuth — 알림 [수락] 을 앱 없이 보내려고 키체인에 둔다
//   앱 → Dart: onToken(16진 기기 토큰) · onTokenError · onTap({kind?, visitId?, callId?, reservationId?, requestId?}) · onLink(ccc:// 링크)
// 알림에서 바로 수락(카테고리 CALL · 액션 ACCEPT「수락」 — 앱을 안 열고 · 잠금 해제 요구 없음 · 워치에서도)
//   → 백그라운드에서 POST /api/calls/{callId}/accept(doctorId 없음 = 의사 자기 자신) → 로컬 알림으로 결과
@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var channel: FlutterMethodChannel?
  private var dartReady = false
  private var pendingTap: [String: Any]?
  private var pendingLink: String? // Dart 준비 전에 온 ccc:// 링크(꺼진 상태에서 QR 로 열림)
  private lazy var links = LinkHandler { [weak self] url in self?.openLink(url) }
  private let scanner = TextScanner() // QR · 여권 사진 · 글자 인식(채널 procedure/scan)
  private let video = VideoConverter() // 채팅 동영상 바꾸기(채널 procedure/video · SPEC-007 §9.2)

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // 꺼진 상태에서 알림을 눌러 열어도 didReceive 가 오도록 시작 때 대리자를 정한다
    UNUserNotificationCenter.current().delegate = self
    let accept = UNNotificationAction(identifier: "ACCEPT", title: "수락", options: [])
    UNUserNotificationCenter.current().setNotificationCategories([
      UNNotificationCategory(identifier: "CALL", actions: [accept], intentIdentifiers: [], options: [])
    ])
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    guard let registrar = engineBridge.pluginRegistry.registrar(forPlugin: "ProcedurePush") else { return }
    let ch = FlutterMethodChannel(name: "procedure/push", binaryMessenger: registrar.messenger())
    ch.setMethodCallHandler { [weak self] call, result in self?.handle(call, result) }
    channel = ch
    if let r = engineBridge.pluginRegistry.registrar(forPlugin: "ProcedureScan") { scanner.attach(r.messenger()) }
    if let r = engineBridge.pluginRegistry.registrar(forPlugin: "ProcedureVideo") { video.attach(r.messenger()) }
    // ccc:// 딥링크(웹 QR 을 iOS 기본 카메라로 찍음 — §5-3 · E2E batch 1 #5) — 장면 생명주기로 받는다
    if let r = engineBridge.pluginRegistry.registrar(forPlugin: "ProcedureLink") { r.addSceneDelegate(links) }
  }

  // 링크 → Dart(준비 전이면 takeLink 때). ccc://display?t= 만 — 나머지는 Dart 가 거른다
  func openLink(_ url: URL) {
    guard url.scheme?.lowercased() == "ccc" else { return }
    if dartReady, let ch = channel {
      ch.invokeMethod("onLink", arguments: url.absoluteString)
    } else {
      pendingLink = url.absoluteString
    }
  }

  // 장면 없이 열린 경우(옛 경로) — 같은 곳으로
  override func application(_ app: UIApplication, open url: URL, options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
    if url.scheme?.lowercased() == "ccc" {
      openLink(url)
      return true
    }
    return super.application(app, open: url, options: options)
  }

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    switch call.method {
    case "ready":
      dartReady = true
      result(pendingTap)
      pendingTap = nil
    case "requestPermission":
      // alert · sound(배지 없음 — §5-1.1)
      UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, _ in
        DispatchQueue.main.async {
          if granted { UIApplication.shared.registerForRemoteNotifications() }
          result(granted)
        }
      }
    case "status":
      UNUserNotificationCenter.current().getNotificationSettings { s in
        let v: String
        switch s.authorizationStatus {
        case .authorized, .provisional, .ephemeral: v = "authorized"
        case .denied: v = "denied"
        default: v = "notDetermined"
        }
        DispatchQueue.main.async { result(v) }
      }
    case "takeLink":
      result(pendingLink)
      pendingLink = nil
    case "installId":
      // 설치 단위 id(E2E batch 1 #1) — 처음 한 번 identifierForVendor 를 키체인에 두고 그 뒤로는 키체인 값.
      // 토큰이 바뀌어도(sandbox ↔ production · 재설치) 같은 값이라 back 이 옛 기기 행을 바꿔 끼운다
      result(InstallId.value())
    case "setAuth":
      let a = call.arguments as? [String: Any]
      if let base = a?["base"] as? String, let token = a?["token"] as? String {
        AuthKeychain.save(base: base, token: token)
      }
      result(nil)
    case "clearAuth":
      AuthKeychain.clear()
      result(nil)
    case "deviceName":
      // 기기 이름(설정 「이 기기」 처음 값 · SPEC-004 §5-1.1 D7-27)
      result(UIDevice.current.name)
    case "deviceModel":
      // 기종 코드(utsname.machine · 예 iPhone16,1) — 기본 기기 이름 = 기종 이름(E2E batch 2 #3 · entitlement 없이).
      // 시뮬레이터는 machine 이 arm64 라 SIMULATOR_MODEL_IDENTIFIER
      var u = utsname()
      uname(&u)
      let machine = withUnsafeBytes(of: &u.machine) { raw in
        String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
      }
      result(ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] ?? machine)
    case "appVersion":
      // 설정 「앱 정보」 — 버전 · 빌드(§6.14)
      let b = Bundle.main.infoDictionary
      result(["version": b?["CFBundleShortVersionString"] as? String ?? "", "build": b?["CFBundleVersion"] as? String ?? ""])
    case "register":
      // 이미 허용된 상태에서 앱 시작 · 서버 주소 바뀜 — 토큰을 다시 받는다(멱등)
      UIApplication.shared.registerForRemoteNotifications()
      result(nil)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  override func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
    let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
    channel?.invokeMethod("onToken", arguments: hex)
  }

  override func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
    channel?.invokeMethod("onTokenError", arguments: error.localizedDescription)
  }

  // 앱이 앞에 있을 때도 배너 + 소리(§5-1.3)
  // 띄우기(kind = display)는 앞에서 받으면 배너 대신 바로 Dart 로 — 앱이 pending 을 읽어 QR · 스캔 화면을 연다
  // (전에는 배너만 떠서, SSE 가 그 순간 안 붙어 있으면 눌러야만 열렸다 — 「띄우기 실기기 안 열림」)
  // 채팅(kind = chat)은 앞에서 받으면 iOS 배너 · 소리 없이 Dart 로 — 앱 안 배너만(SPEC-007 §8 · D9-39).
  // Dart 준비 전(막 켠 직후)이면 지금처럼 배너 + 소리(띄우기와 같은 꼴)
  override func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    willPresent notification: UNNotification,
    withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
  ) {
    let info = notification.request.content.userInfo
    if (info["kind"] as? String) == "display" {
      var tap: [String: Any] = [:]
      for key in ["kind", "requestId"] {
        if let v = info[key] { tap[key] = v }
      }
      if dartReady, let ch = channel {
        ch.invokeMethod("onForeground", arguments: tap)
        return completionHandler([])
      }
    }
    if (info["kind"] as? String) == "chat" {
      var tap: [String: Any] = [:]
      for key in ["kind", "roomId", "messageId"] {
        if let v = info[key] { tap[key] = v }
      }
      // 앱 안 배너 글자 = 푸시 제목 · 본문(1:1 = 보낸 사람 · 그룹 = 「보낸 사람 · 방 이름」)
      tap["title"] = notification.request.content.title
      tap["body"] = notification.request.content.body
      if dartReady, let ch = channel {
        ch.invokeMethod("onForeground", arguments: tap)
        return completionHandler([])
      }
    }
    if #available(iOS 14.0, *) {
      completionHandler([.banner, .list, .sound])
    } else {
      completionHandler([.alert, .sound])
    }
  }

  // 알림을 누름 → payload(kind · visitId · callId · reservationId · requestId · 채팅 roomId · messageId)를 Dart 로(아직 준비 전이면 ready 때 넘김)
  override func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    didReceive response: UNNotificationResponse,
    withCompletionHandler completionHandler: @escaping () -> Void
  ) {
    let info = response.notification.request.content.userInfo
    if response.actionIdentifier == "ACCEPT" {
      acceptFromNotification(info, alertBody: response.notification.request.content.body, done: completionHandler)
      return
    }
    var tap: [String: Any] = [:]
    for key in ["kind", "visitId", "callId", "reservationId", "requestId", "roomId", "messageId"] {
      if let v = info[key] { tap[key] = v }
    }
    if dartReady, let ch = channel {
      ch.invokeMethod("onTap", arguments: tap)
    } else {
      pendingTap = tap
    }
    completionHandler()
  }

  // 알림 [수락] — 앱 화면 없이 수락 요청 → 결과를 로컬 알림으로(실패 알림을 누르면 그 방 룸 상세)
  private func acceptFromNotification(_ info: [AnyHashable: Any], alertBody: String, done: @escaping () -> Void) {
    let room = alertBody.components(separatedBy: " · ").first ?? ""
    let visitId = info["visitId"]
    guard let callId = (info["callId"] as? NSNumber)?.intValue ?? Int("\(info["callId"] ?? "")"),
          let auth = AuthKeychain.load(),
          let url = URL(string: "\(auth.base)/api/calls/\(callId)/accept") else {
      notifyResult(title: "수락 못 함 · 앱에서 다시 로그인해 주세요", visitId: visitId, done: done)
      return
    }
    var task = UIBackgroundTaskIdentifier.invalid
    task = UIApplication.shared.beginBackgroundTask { UIApplication.shared.endBackgroundTask(task) }
    var req = URLRequest(url: url, timeoutInterval: 20)
    req.httpMethod = "POST"
    req.setValue("Bearer \(auth.token)", forHTTPHeaderField: "Authorization")
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.setValue("push", forHTTPHeaderField: "X-Accept-Source") // back 기록용(알림 [수락])
    req.httpBody = "{}".data(using: .utf8) // doctorId 없음 = 의사 자기 자신(§3.4)
    URLSession.shared.dataTask(with: req) { data, res, err in
      let status = (res as? HTTPURLResponse)?.statusCode ?? 0
      let title: String
      if (200..<300).contains(status) {
        title = "수락했어요 · \(room)"
      } else {
        var why = err == nil ? "요청을 처리하지 못했어요" : "서버에 연결할 수 없어요"
        if let d = data, let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
           let e = j["error"] as? [String: Any], let m = e["message"] as? String { why = m }
        title = "수락 못 함 · \(why)"
      }
      self.notifyResult(title: title, visitId: visitId) {
        done()
        UIApplication.shared.endBackgroundTask(task)
      }
    }.resume()
  }

  private func notifyResult(title: String, visitId: Any?, done: @escaping () -> Void) {
    let c = UNMutableNotificationContent()
    c.title = title
    c.sound = .default
    if let v = visitId { c.userInfo = ["visitId": v] }
    let req = UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil)
    UNUserNotificationCenter.current().add(req) { _ in DispatchQueue.main.async { done() } }
  }
}

// ccc:// 링크 받기(장면 생명주기 — 꺼진 상태에서 열림 · 켜진 상태에서 열림 둘 다)
final class LinkHandler: NSObject, FlutterSceneLifeCycleDelegate {
  private let open: (URL) -> Void
  init(_ open: @escaping (URL) -> Void) { self.open = open }

  func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions?) -> Bool {
    guard let url = connectionOptions?.urlContexts.first(where: { $0.url.scheme?.lowercased() == "ccc" })?.url else { return false }
    open(url)
    return true
  }

  func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) -> Bool {
    guard let url = URLContexts.first(where: { $0.url.scheme?.lowercased() == "ccc" })?.url else { return false }
    open(url)
    return true
  }
}

// 설치 단위 id — 키체인(이 기기만 · 첫 잠금 해제 뒤). 앱을 지워도 키체인은 남아 재설치 뒤에도 같은 값
enum InstallId {
  private static let service = "procedure.install"
  private static let account = "id"

  static func value() -> String {
    let q: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
      kSecReturnData as String: true,
      kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var out: CFTypeRef?
    if SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data, let s = String(data: d, encoding: .utf8), !s.isEmpty {
      return s
    }
    let id = (UIDevice.current.identifierForVendor ?? UUID()).uuidString.lowercased()
    let add: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
      kSecValueData as String: Data(id.utf8),
    ]
    SecItemAdd(add as CFDictionary, nil)
    return id
  }
}

// 알림 [수락] 용 로그인 — 키체인 · 첫 잠금 해제 뒤 백그라운드에서도 읽힘(이 기기만)
enum AuthKeychain {
  private static let service = "procedure.push.auth"
  private static let account = "session"

  static func save(base: String, token: String) {
    guard let data = try? JSONSerialization.data(withJSONObject: ["base": base, "token": token]) else { return }
    clear()
    let q: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
      kSecValueData as String: data,
    ]
    SecItemAdd(q as CFDictionary, nil)
  }

  static func load() -> (base: String, token: String)? {
    let q: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
      kSecReturnData as String: true,
      kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var out: CFTypeRef?
    guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data,
          let j = try? JSONSerialization.jsonObject(with: d) as? [String: String],
          let base = j["base"], let token = j["token"] else { return nil }
    return (base, token)
  }

  static func clear() {
    let q: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
    ]
    SecItemDelete(q as CFDictionary)
  }
}


// 채팅 동영상 바꾸기(SPEC-007 §9.2 · D9-51 · r3) — 채널 "procedure/video". 기기 안에서만 · 앱 임시 폴더에만 쓴다(사진첩 저장 없음 · D9-24)
//   probe({path}) → {durationMs}(배경 큐) · audioSave · audioFollowSilent · audioRestore(재생 화면 — 무음 스위치를 따름)
//   convert({path}) → {path, width, height, durationMs, bytes, thumb} — HEVC · H.264 · MOV · 슬로모 · 고프레임 · 4K 무엇이든
//     H.264 MP4 · 긴 변 1280 · AAC(AVAssetExportPreset1280x720 — 세로 영상은 720×1280 · 더 작은 원본은 그 크기) + 0초 JPEG(품질 80 · 같은 크기)
//   실패 = FlutterError(convert_failed) — 만들다 만 파일은 지운다
final class VideoConverter {
  private var channel: FlutterMethodChannel?

  func attach(_ messenger: FlutterBinaryMessenger) {
    let ch = FlutterMethodChannel(name: "procedure/video", binaryMessenger: messenger)
    ch.setMethodCallHandler { [weak self] call, result in self?.handle(call, result) }
    channel = ch
  }

  // 재생 화면이 여는 동안 오디오 세션(review-code r2 W-4 · SPEC §9.2 「무음 스위치를 따른다」) — video_player 는 플레이어 초기화 때
  // .playback(무음 스위치 무시)으로 올리므로, 재생 화면이 audioSave → (플레이어 초기화) → audioFollowSilent(.soloAmbient) → 닫을 때 audioRestore.
  // 통역(audio_session · .playAndRecord)이 잡고 있던 세션이면 건드리지 않는다
  private var savedAudio: (AVAudioSession.Category, AVAudioSession.Mode, AVAudioSession.CategoryOptions)?

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    let session = AVAudioSession.sharedInstance()
    switch call.method {
    case "audioSave":
      savedAudio = (session.category, session.mode, session.categoryOptions)
      result(nil)
      return
    case "audioFollowSilent":
      if let a = savedAudio, a.0 == .playAndRecord || a.0 == .record {
        result(false)
        return
      }
      result((try? session.setCategory(.soloAmbient, mode: .default, options: [])) != nil)
      return
    case "audioRestore":
      if let a = savedAudio, a.0 != .playAndRecord, a.0 != .record {
        try? session.setCategory(a.0, mode: a.1, options: a.2)
      }
      savedAudio = nil
      result(nil)
      return
    default:
      break
    }
    guard let args = call.arguments as? [String: Any], let path = args["path"] as? String else {
      result(FlutterError(code: "bad_args", message: nil, details: nil))
      return
    }
    let url = URL(fileURLWithPath: path)
    switch call.method {
    case "probe":
      // 길이 읽기는 로드가 끝날 때까지 막으므로 배경에서 · 결과만 메인으로(W-6)
      DispatchQueue.global(qos: .userInitiated).async {
        let ms = Self.ms(AVURLAsset(url: url).duration)
        DispatchQueue.main.async { result(["durationMs": ms]) }
      }
    case "convert":
      convert(url, result)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private static func ms(_ t: CMTime) -> Int {
    let s = t.seconds
    return s.isFinite ? Int((s * 1000).rounded()) : 0
  }

  private func convert(_ src: URL, _ result: @escaping FlutterResult) {
    let fail: (String?) -> Void = { msg in
      DispatchQueue.main.async { result(FlutterError(code: "convert_failed", message: msg, details: nil)) }
    }
    let asset = AVURLAsset(url: src)
    guard let export = AVAssetExportSession(asset: asset, presetName: AVAssetExportPreset1280x720) else {
      fail("no_session")
      return
    }
    let out = FileManager.default.temporaryDirectory.appendingPathComponent("chat-video-\(UUID().uuidString).mp4")
    export.outputURL = out
    export.outputFileType = .mp4
    export.shouldOptimizeForNetworkUse = true
    export.exportAsynchronously {
      guard export.status == .completed else {
        try? FileManager.default.removeItem(at: out)
        fail(export.error?.localizedDescription)
        return
      }
      let made = AVURLAsset(url: out)
      let gen = AVAssetImageGenerator(asset: made)
      gen.appliesPreferredTrackTransform = true
      guard let cg = try? gen.copyCGImage(at: .zero, actualTime: nil),
            let jpeg = UIImage(cgImage: cg).jpegData(compressionQuality: 0.8) else {
        try? FileManager.default.removeItem(at: out)
        fail("no_thumb")
        return
      }
      let bytes = ((try? FileManager.default.attributesOfItem(atPath: out.path))?[.size] as? NSNumber)?.intValue ?? 0
      let info: [String: Any] = [
        "path": out.path, "width": cg.width, "height": cg.height, "durationMs": Self.ms(made.duration),
        "bytes": bytes, "thumb": FlutterStandardTypedData(bytes: jpeg),
      ]
      DispatchQueue.main.async { result(info) }
    }
  }
}
