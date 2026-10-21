import Flutter
import UIKit
import UserNotifications

// 원장 호출 푸시(SPEC-004 §5-1) — APNs 직접(Firebase 0). Dart 와는 채널 "procedure/push" 하나로:
//   Dart → 앱: ready(눌러서 연 알림이 있으면 그 payload 를 돌려줌) · requestPermission · status · register
//             · setAuth({base, token}) · clearAuth — 알림 [수락] 을 앱 없이 보내려고 키체인에 둔다
//   앱 → Dart: onToken(16진 기기 토큰) · onTokenError · onTap({visitId, callId})
// 알림에서 바로 수락(카테고리 CALL · 액션 ACCEPT「수락」 — 앱을 안 열고 · 잠금 해제 요구 없음 · 워치에서도)
//   → 백그라운드에서 POST /api/calls/{callId}/accept(doctorId 없음 = 의사 자기 자신) → 로컬 알림으로 결과
@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var channel: FlutterMethodChannel?
  private var dartReady = false
  private var pendingTap: [String: Any]?

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
    case "setAuth":
      let a = call.arguments as? [String: Any]
      if let base = a?["base"] as? String, let token = a?["token"] as? String {
        AuthKeychain.save(base: base, token: token)
      }
      result(nil)
    case "clearAuth":
      AuthKeychain.clear()
      result(nil)
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
  override func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    willPresent notification: UNNotification,
    withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
  ) {
    if #available(iOS 14.0, *) {
      completionHandler([.banner, .list, .sound])
    } else {
      completionHandler([.alert, .sound])
    }
  }

  // 알림을 누름 → payload visitId · callId 를 Dart 로(아직 준비 전이면 ready 때 넘김)
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
    if let v = info["visitId"] { tap["visitId"] = v }
    if let c = info["callId"] { tap["callId"] = c }
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

