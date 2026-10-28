import AVFoundation
import Flutter
import UIKit
import Vision

// 카메라 · 글자 인식(SPEC-004 §5-3 QR · §6.16 여권 스캔) · 문진 QR 그리기 · 화면 꺼짐 막기(SPEC-006 §8.2) — 채널 "procedure/scan". 외부 서비스 0 · 기기 안에서만(D7-49).
//   scanQr → QR 글자(취소 = nil)
//   scanPassport({windows, windowSec, debug}) → 여권 연속 스캔(E2E batch 1 #6 · batch 2 #4): AVCaptureSession 영상 프레임에서 가이드 틀의
//     MRZ 자리만 잘라 Vision 으로 계속 읽고 → 줄마다 Dart(checkMrz — mrz.dart 보정 · 검사 숫자 · 연속 두 번 확정)에 물어
//     confirmed 면 그 프레임을 자동 촬영 → {photo: JPEG(틀 영역 · 품질 0.8), lines}
//     [촬영](늘 보임) → 지금 프레임의 틀 영역 사진 + 그 사진 글자 → {photo, lines, shutter: true}
//     windowSec 초씩 windows 번 못 읽음 또는 [손으로 입력] → {failed: true} · [닫기] = nil · debug = 인식 글자 오버레이
//   카메라가 없거나 권한이 꺼짐(시뮬레이터 포함) = FlutterError "no_camera"
// 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 프레임 · 찍은 사진은 사진첩에 저장하지 않고 메모리로만 Dart 에 넘긴다(§6.16 원본 · D7-50).
// 이 파일은 사진을 디스크 · 사진첩 · 로그에 쓰지 않는다.
final class TextScanner: NSObject {
  private var channel: FlutterMethodChannel?

  func attach(_ messenger: FlutterBinaryMessenger) {
    let ch = FlutterMethodChannel(name: "procedure/scan", binaryMessenger: messenger)
    ch.setMethodCallHandler { [weak self] call, result in self?.handle(call, result) }
    channel = ch
  }

  private var top: UIViewController? {
    var vc = UIApplication.shared.connectedScenes
      .compactMap { ($0 as? UIWindowScene)?.windows.first { $0.isKeyWindow } }
      .first?.rootViewController
    while let p = vc?.presentedViewController { vc = p }
    return vc
  }

  private func noCamera(_ result: FlutterResult, _ message: String = "카메라가 없어요") {
    result(FlutterError(code: "no_camera", message: message, details: nil))
  }

  // 카메라 권한 — 처음이면 묻고 · 꺼져 있으면 no_camera(Dart = 손으로 입력)
  private func withCamera(_ result: @escaping FlutterResult, _ go: @escaping () -> Void) {
    switch AVCaptureDevice.authorizationStatus(for: .video) {
    case .authorized: go()
    case .notDetermined:
      AVCaptureDevice.requestAccess(for: .video) { ok in
        DispatchQueue.main.async { ok ? go() : self.noCamera(result, "카메라 권한이 꺼져 있어요") }
      }
    default: noCamera(result, "카메라 권한이 꺼져 있어요")
    }
  }

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    switch call.method {
    case "scanQr":
      guard AVCaptureDevice.default(for: .video) != nil else { return noCamera(result) }
      let vc = QrViewController()
      vc.done = { text in result(text) }
      vc.modalPresentationStyle = .fullScreen
      top?.present(vc, animated: true)
    case "scanPassport":
      guard let dev = PassportScanController.camera() else { return noCamera(result) }
      let a = call.arguments as? [String: Any]
      withCamera(result) { [weak self] in
        guard let self else { return }
        let vc = PassportScanController(device: dev,
                                        windows: (a?["windows"] as? Int) ?? 3,
                                        windowSec: (a?["windowSec"] as? Double) ?? 8,
                                        debug: (a?["debug"] as? Bool) ?? false)
        // 읽은 줄 → Dart 판정(보정 · 검사 숫자 · 연속 두 번 규칙은 mrz.dart 한 곳) — none · lines · pending · confirmed
        vc.check = { [weak self] lines, answer in
          guard let ch = self?.channel else { return answer("none") }
          ch.invokeMethod("checkMrz", arguments: lines) { r in answer((r as? String) ?? "none") }
        }
        vc.done = { out in result(out) }
        vc.modalPresentationStyle = .fullScreen
        self.top?.present(vc, animated: true)
      }
    case "qrImage":
      // 문진 QR 화면(SPEC-006 §8.2) — 글자(qrUrl)를 QR PNG 로. 기기 안 CoreImage · 외부 서비스 0 · 파일 · 로그에 쓰지 않는다
      let a = call.arguments as? [String: Any]
      guard let text = a?["text"] as? String, let png = Self.qrPng(text, size: (a?["size"] as? Double) ?? 600) else {
        return result(FlutterError(code: "qr_failed", message: "QR 을 만들지 못했어요", details: nil))
      }
      result(FlutterStandardTypedData(bytes: png))
    case "keepAwake":
      // QR 화면이 떠 있는 동안 화면 꺼짐 막기(wakelock) — 닫힐 때 false
      UIApplication.shared.isIdleTimerDisabled = (call.arguments as? Bool) == true
      result(nil)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  // QR — 오류 정정 M · 칸을 정수 배로 키워 흐림 없이(긴 변 size px 안팎) · 흰 바탕 검은 칸
  static func qrPng(_ text: String, size: Double) -> Data? {
    guard let f = CIFilter(name: "CIQRCodeGenerator") else { return nil }
    f.setValue(Data(text.utf8), forKey: "inputMessage")
    f.setValue("M", forKey: "inputCorrectionLevel")
    guard let raw = f.outputImage else { return nil }
    let k = max(1, floor(size / raw.extent.width))
    let img = raw.transformed(by: CGAffineTransform(scaleX: k, y: k))
    let ctx = CIContext()
    guard let cg = ctx.createCGImage(img, from: img.extent) else { return nil }
    return UIImage(cgImage: cg).pngData()
  }
}

// 여권 연속 스캔(§6.16 ① · E2E batch 1 #6 · batch 2 #4)
// - 카메라: 자동 매크로가 되는 가상 기기 먼저(builtInTripleCamera → builtInDualWideCamera → builtInWideAngleCamera).
//   가상 기기는 첫 전환 배율(= 보통 「1x」 광각)로 두고, 가까우면 iOS 가 초광각(매크로)으로 스스로 바꾼다
//   광각만 있는 기기는 최소 초점거리에 맞춰 조금 확대(가까이 대지 않아도 틀이 차게)
// - 틀 ↔ 영상 좌표: 미리보기 레이어의 metadataOutputRectConverted(fromLayerRect:) — aspect fill · 회전 · 크기를 레이어가 계산한
//   센서 좌표(가로 · 왼쪽 위 원점 · 0~1). 그 영역을 버퍼에서 자른 뒤 화면 방향으로 세워 Vision 에 넘긴다(regionOfInterest 안 씀)
// - 프레임마다(앞 것이 끝난 뒤) MRZ 자리 글자 → Dart 판정 → confirmed(같은 판독 연속 두 번) 면 그 프레임을 찍음
// - [촬영] 늘 보임 · windowSec 초 동안 확정 못 하면 실패 1번(n / windows) · windows 번이면 끝(failed) · 1번 실패 뒤 [손으로 입력]
final class PassportScanController: UIViewController, AVCaptureVideoDataOutputSampleBufferDelegate {
  var check: (([String], @escaping (String) -> Void) -> Void)?
  var done: (([String: Any]?) -> Void)?

  private let device: AVCaptureDevice
  private let windows: Int
  private let windowSec: Double
  private let debug: Bool
  private let session = AVCaptureSession()
  private let queue = DispatchQueue(label: "procedure.scan.video")
  private let preview = AVCaptureVideoPreviewLayer()
  private let dim = CAShapeLayer()
  private let frameLine = CAShapeLayer()
  private let mrzLine = CAShapeLayer()
  private let titleLabel = UILabel()
  private let tipLabel = UILabel()
  private let statusLabel = UILabel()
  private let debugLabel = UILabel()
  private let shutterButton = UIButton(type: .custom)
  private let manualButton = UIButton(type: .system)
  private let ci = CIContext()

  // video 큐에서만 — 지금 읽는 중 · 끝남 · 마지막 읽은 때 · 마지막 프레임([촬영]) · 틀 · MRZ 자리(센서 좌표) · 화면 방향
  private var busy = false
  private var finished = false
  private var lastRun = Date.distantPast
  private var lastPixels: CVPixelBuffer?
  private var boxSensor: CGRect?
  private var mrzSensor: CGRect?
  private var upright = CGImagePropertyOrientation.right

  // main
  private var fails = 0
  private var timer: Timer?
  private var sent = false
  private var stateText = "판독 줄 찾는 중"

  init(device: AVCaptureDevice, windows: Int, windowSec: Double, debug: Bool) {
    self.device = device
    self.windows = max(1, windows)
    self.windowSec = max(2, windowSec)
    self.debug = debug
    super.init(nibName: nil, bundle: nil)
  }
  required init?(coder: NSCoder) { fatalError() }

  static func camera() -> AVCaptureDevice? {
    for t: AVCaptureDevice.DeviceType in [.builtInTripleCamera, .builtInDualWideCamera, .builtInWideAngleCamera] {
      if let d = AVCaptureDevice.default(t, for: .video, position: .back) { return d }
    }
    return nil
  }

  override var supportedInterfaceOrientations: UIInterfaceOrientationMask {
    UIDevice.current.userInterfaceIdiom == .pad ? .all : .portrait
  }

  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = .black
    configureSession()
    preview.session = session
    preview.videoGravity = .resizeAspectFill
    view.layer.addSublayer(preview)
    dim.fillRule = .evenOdd
    dim.fillColor = UIColor(white: 0, alpha: 0.55).cgColor
    view.layer.addSublayer(dim)
    frameLine.strokeColor = UIColor.white.cgColor
    frameLine.fillColor = UIColor.clear.cgColor
    frameLine.lineWidth = 3
    view.layer.addSublayer(frameLine)
    mrzLine.strokeColor = UIColor(white: 1, alpha: 0.9).cgColor
    mrzLine.fillColor = UIColor.clear.cgColor
    mrzLine.lineWidth = 2
    mrzLine.lineDashPattern = [8, 6]
    view.layer.addSublayer(mrzLine)

    titleLabel.text = "여권 사진면을 틀에 맞춰 주세요"
    titleLabel.font = .systemFont(ofSize: 18, weight: .semibold)
    tipLabel.text = "아래 두 줄(MRZ)이 점선 안에 · 빛 반사가 없게\n읽히면 자동으로 찍혀요 · 안 되면 [촬영]"
    tipLabel.font = .systemFont(ofSize: 14)
    statusLabel.font = .systemFont(ofSize: 16, weight: .bold)
    statusLabel.text = stateText
    for l in [titleLabel, tipLabel, statusLabel] {
      l.textColor = .white
      l.textAlignment = .center
      l.numberOfLines = 0
      l.translatesAutoresizingMaskIntoConstraints = false
      view.addSubview(l)
    }
    // debug 빌드만 — 인식 글자(원인 확인용 · 화면에만 · 저장 · 로그 없음)
    debugLabel.font = .monospacedSystemFont(ofSize: 10, weight: .regular)
    debugLabel.textColor = .yellow
    debugLabel.backgroundColor = UIColor(white: 0, alpha: 0.6)
    debugLabel.numberOfLines = 0
    debugLabel.isHidden = !debug
    debugLabel.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(debugLabel)

    let close = UIButton(type: .system)
    close.setTitle("닫기", for: .normal)
    close.setTitleColor(.white, for: .normal)
    close.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
    close.addTarget(self, action: #selector(cancel), for: .touchUpInside)
    close.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(close)
    // [촬영] — 늘 보임(자동이 안 되면 사람이 찍는다)
    shutterButton.backgroundColor = .white
    shutterButton.layer.cornerRadius = 36
    shutterButton.layer.borderColor = UIColor(white: 1, alpha: 0.5).cgColor
    shutterButton.layer.borderWidth = 5
    shutterButton.accessibilityLabel = "촬영"
    shutterButton.addTarget(self, action: #selector(shutter), for: .touchUpInside)
    shutterButton.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(shutterButton)
    let shutterText = UILabel()
    shutterText.text = "촬영"
    shutterText.textColor = .white
    shutterText.font = .systemFont(ofSize: 13, weight: .semibold)
    shutterText.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(shutterText)
    var cfg = UIButton.Configuration.bordered()
    cfg.title = "손으로 입력"
    cfg.baseForegroundColor = .white
    cfg.baseBackgroundColor = UIColor(white: 1, alpha: 0.15)
    manualButton.configuration = cfg
    manualButton.addTarget(self, action: #selector(manual), for: .touchUpInside)
    manualButton.isHidden = true
    manualButton.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(manualButton)
    NSLayoutConstraint.activate([
      close.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
      close.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
      titleLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      titleLabel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 56),
      titleLabel.widthAnchor.constraint(lessThanOrEqualTo: view.widthAnchor, constant: -32),
      debugLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 8),
      debugLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 8),
      debugLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -8),
      shutterButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      shutterButton.bottomAnchor.constraint(equalTo: shutterText.topAnchor, constant: -6),
      shutterButton.widthAnchor.constraint(equalToConstant: 72),
      shutterButton.heightAnchor.constraint(equalToConstant: 72),
      shutterText.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      shutterText.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -16),
      manualButton.centerYAnchor.constraint(equalTo: shutterButton.centerYAnchor),
      manualButton.leadingAnchor.constraint(equalTo: shutterButton.trailingAnchor, constant: 24),
      statusLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      statusLabel.bottomAnchor.constraint(equalTo: shutterButton.topAnchor, constant: -20),
      statusLabel.widthAnchor.constraint(lessThanOrEqualTo: view.widthAnchor, constant: -32),
      tipLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      tipLabel.bottomAnchor.constraint(equalTo: statusLabel.topAnchor, constant: -10),
      tipLabel.widthAnchor.constraint(lessThanOrEqualTo: view.widthAnchor, constant: -32),
    ])
  }

  override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    queue.async { [weak self] in
      guard let self else { return }
      self.session.startRunning()
      // 세션이 돌기 시작해야 미리보기 레이어가 센서 좌표로 바꿀 수 있다
      DispatchQueue.main.async { self.layoutGuide() }
    }
    startWindow()
  }

  override func viewDidLayoutSubviews() {
    super.viewDidLayoutSubviews()
    preview.frame = view.bounds
    layoutGuide()
  }

  // ---------------------------------------------------------------- 카메라
  private func configureSession() {
    session.beginConfiguration()
    session.sessionPreset = session.canSetSessionPreset(.hd1920x1080) ? .hd1920x1080 : .high
    if let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) { session.addInput(input) }
    let out = AVCaptureVideoDataOutput()
    out.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange]
    out.alwaysDiscardsLateVideoFrames = true
    out.setSampleBufferDelegate(self, queue: queue)
    if session.canAddOutput(out) { session.addOutput(out) }
    session.commitConfiguration()
    do {
      try device.lockForConfiguration()
      if device.isFocusModeSupported(.continuousAutoFocus) { device.focusMode = .continuousAutoFocus }
      if device.isAutoFocusRangeRestrictionSupported { device.autoFocusRangeRestriction = .near }
      if device.isExposureModeSupported(.continuousAutoExposure) { device.exposureMode = .continuousAutoExposure }
      if device.isVirtualDevice {
        // 매크로 자동 전환 — 가상 기기의 기본 동작(.auto)을 분명히
        device.setPrimaryConstituentDeviceSwitchingBehavior(.auto, restrictedSwitchingBehaviorConditions: [])
        if let wide = device.virtualDeviceSwitchOverVideoZoomFactors.first?.doubleValue {
          device.videoZoomFactor = min(CGFloat(wide), device.activeFormat.videoMaxZoomFactor)
        }
      } else {
        // 광각만 — 최소 초점거리에서 여권(125mm)이 틀(화면 폭 80%)을 채우는 거리보다 가까워야 하면 그만큼 확대(Apple AVCamBarcode 식)
        let fov = Double(device.activeFormat.videoFieldOfView) * .pi / 180
        let subject = (125.0 / 0.8) / tan(fov / 2) // mm
        let minFocus = Double(device.minimumFocusDistance)
        if minFocus > 0, minFocus > subject {
          device.videoZoomFactor = min(CGFloat(minFocus / subject), min(2.5, device.activeFormat.videoMaxZoomFactor))
        }
      }
      device.unlockForConfiguration()
    } catch {}
  }

  // 지금 화면 방향 → 미리보기 회전 · 세운 이미지 방향(가로는 iPad 만)
  private func orientation() -> (AVCaptureVideoOrientation, CGImagePropertyOrientation) {
    switch view.window?.windowScene?.interfaceOrientation ?? .portrait {
    case .landscapeRight: return (.landscapeRight, .up)
    case .landscapeLeft: return (.landscapeLeft, .down)
    case .portraitUpsideDown: return (.portraitUpsideDown, .left)
    default: return (.portrait, .right)
    }
  }

  // 가이드 틀(사진면 125 × 88) · 아래 MRZ 자리 · 어두운 바깥 — 그리고 틀 · MRZ 자리를 센서 좌표로
  private func layoutGuide() {
    let b = view.bounds
    guard b.width > 0, b.height > 0 else { return }
    let (vo, io) = orientation()
    if let c = preview.connection, c.isVideoOrientationSupported { c.videoOrientation = vo }
    let w = min(b.width * 0.8, b.height * 0.5 * 125 / 88)
    let h = w * 88 / 125
    let box = CGRect(x: (b.width - w) / 2, y: b.height * 0.42 - h / 2, width: w, height: h)
    let mrz = CGRect(x: box.minX + 6, y: box.maxY - h * 0.3, width: box.width - 12, height: h * 0.3 - 6)
    let hole = UIBezierPath(rect: b)
    hole.append(UIBezierPath(roundedRect: box, cornerRadius: 12))
    dim.path = hole.cgPath
    frameLine.path = UIBezierPath(roundedRect: box, cornerRadius: 12).cgPath
    mrzLine.path = UIBezierPath(roundedRect: mrz, cornerRadius: 6).cgPath
    // 레이어가 계산 — 세션이 아직 안 돌면 빈 · 이상한 값이라 다음 레이아웃(세션 시작 뒤)에 다시
    let unit = CGRect(x: 0, y: 0, width: 1, height: 1)
    let boxS = preview.metadataOutputRectConverted(fromLayerRect: box.insetBy(dx: -10, dy: -10)).intersection(unit)
    let mrzS = preview.metadataOutputRectConverted(fromLayerRect: mrz.insetBy(dx: -14, dy: -14)).intersection(unit)
    let valid = !boxS.isNull && !mrzS.isNull && boxS.width > 0.05 && mrzS.width > 0.02
    queue.async { [weak self] in
      guard let self else { return }
      self.upright = io
      if valid {
        self.boxSensor = boxS
        self.mrzSensor = mrzS
      }
    }
  }

  // ---------------------------------------------------------------- 상태 · 실패 창(windowSec 초씩 windows 번)
  private func setState(_ text: String) {
    stateText = text
    statusLabel.text = fails == 0 ? text : "\(text) · 못 읽음 \(fails) / \(windows)"
  }

  private func startWindow() {
    timer?.invalidate()
    timer = Timer.scheduledTimer(withTimeInterval: windowSec, repeats: false) { [weak self] _ in self?.windowFailed() }
  }

  private func windowFailed() {
    guard !sent else { return }
    fails += 1
    if fails >= windows { return finish(["failed": true]) }
    setState(stateText)
    manualButton.isHidden = false
    UINotificationFeedbackGenerator().notificationOccurred(.warning)
    startWindow()
  }

  @objc private func cancel() { finish(nil) }
  @objc private func manual() { finish(["failed": true]) }

  // [촬영] — 지금 프레임의 틀 영역 사진 + 그 사진 전체 글자(Dart 가 다시 읽고 · 못 읽으면 손 입력)
  @objc private func shutter() {
    guard !sent else { return }
    shutterButton.isEnabled = false
    setState("사진에서 읽는 중")
    queue.async { [weak self] in
      guard let self, let pixels = self.lastPixels, let box = self.boxSensor,
            let img = self.uprightCrop(pixels, box), let jpeg = self.jpeg(img) else {
        DispatchQueue.main.async { self?.shutterButton.isEnabled = true }
        return
      }
      let lines = self.read(img)
      DispatchQueue.main.async {
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        self.finish(["photo": FlutterStandardTypedData(bytes: jpeg), "lines": lines, "shutter": true])
      }
    }
  }

  private func finish(_ out: [String: Any]?) {
    guard !sent else { return }
    sent = true
    timer?.invalidate()
    queue.async { [session, weak self] in
      self?.finished = true
      self?.lastPixels = nil
      session.stopRunning()
    }
    dismiss(animated: true) { [done] in done?(out) }
  }

  // ---------------------------------------------------------------- 프레임(video 큐)
  func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
    guard !finished, let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
    lastPixels = pixels
    guard !busy, Date().timeIntervalSince(lastRun) > 0.1, let mrz = mrzSensor, let img = uprightCrop(pixels, mrz) else { return }
    busy = true
    lastRun = Date()
    let lines = read(img)
    DispatchQueue.main.async { [weak self] in
      guard let self, !self.sent else { return }
      if self.debug { self.debugLabel.text = lines.isEmpty ? "(글자 없음)" : lines.joined(separator: "\n") }
      // 빈 프레임도 묻는다 — 연속 두 번 판정이 사이에 끊긴 프레임을 알게
      guard let check = self.check else {
        self.setState("판독 줄 찾는 중")
        self.queue.async { self.busy = false }
        return
      }
      check(lines) { state in
        switch state {
        case "confirmed":
          self.setState("확인됨")
          self.queue.async {
            let photo = self.boxSensor.flatMap { self.uprightCrop(pixels, $0) }.flatMap { self.jpeg($0) }
            DispatchQueue.main.async {
              guard let photo else { self.queue.async { self.busy = false }; return }
              UINotificationFeedbackGenerator().notificationOccurred(.success)
              self.finish(["photo": FlutterStandardTypedData(bytes: photo), "lines": lines])
            }
          }
          return
        case "pending": self.setState("확인 중 — 그대로 들고 있어 주세요")
        case "lines": self.setState("두 줄 읽음 — 맞추는 중")
        default: self.setState("판독 줄 찾는 중")
        }
        self.queue.async { self.busy = false }
      }
    }
  }

  // 센서 좌표(가로 · 왼쪽 위 원점 · 0~1) 영역을 버퍼에서 잘라 화면 방향으로 세운 그림 — 메모리에서만
  private func uprightCrop(_ pixels: CVPixelBuffer, _ r: CGRect) -> CIImage? {
    let img = CIImage(cvPixelBuffer: pixels)
    let e = img.extent // CI 는 왼쪽 아래 원점 — y 를 뒤집는다
    let rect = CGRect(x: e.minX + r.minX * e.width, y: e.minY + (1 - r.maxY) * e.height, width: r.width * e.width, height: r.height * e.height)
    guard rect.width > 10, rect.height > 10 else { return nil }
    let out = img.cropped(to: rect).oriented(upright)
    return out.transformed(by: CGAffineTransform(translationX: -out.extent.minX, y: -out.extent.minY))
  }

  // 글자 인식(기기 안 · 외부 서비스 0)
  private func read(_ img: CIImage) -> [String] {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false // MRZ 는 사전 단어가 아니다
    req.recognitionLanguages = ["en-US"]
    let h = VNImageRequestHandler(ciImage: img, options: [:])
    try? h.perform([req])
    return (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
  }

  // JPEG(긴 변 2000 이하 · 품질 0.8) — 메모리에서만
  private func jpeg(_ src: CIImage) -> Data? {
    var img = src
    let long = max(img.extent.width, img.extent.height)
    if long > 2000 { img = img.transformed(by: CGAffineTransform(scaleX: 2000 / long, y: 2000 / long)) }
    img = img.transformed(by: CGAffineTransform(translationX: -img.extent.minX, y: -img.extent.minY))
    guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
    return ci.jpegRepresentation(of: img, colorSpace: space, options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.8])
  }
}

// QR 읽기(§6.10 [QR 읽기] · §5-3) — 처음 읽힌 QR 글자를 돌려준다 · [닫기] = nil
final class QrViewController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
  var done: ((String?) -> Void)?
  private let session = AVCaptureSession()
  private var sent = false

  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = .black
    if let dev = AVCaptureDevice.default(for: .video), let input = try? AVCaptureDeviceInput(device: dev), session.canAddInput(input) {
      session.addInput(input)
      let out = AVCaptureMetadataOutput()
      if session.canAddOutput(out) {
        session.addOutput(out)
        out.setMetadataObjectsDelegate(self, queue: .main)
        out.metadataObjectTypes = [.qr]
      }
      let layer = AVCaptureVideoPreviewLayer(session: session)
      layer.videoGravity = .resizeAspectFill
      layer.frame = view.bounds
      view.layer.addSublayer(layer)
    }
    let label = UILabel()
    label.text = "데스크 화면의 QR 을 비춰 주세요"
    label.textColor = .white
    label.font = .systemFont(ofSize: 17, weight: .semibold)
    label.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(label)
    let close = UIButton(type: .system)
    close.setTitle("닫기", for: .normal)
    close.setTitleColor(.white, for: .normal)
    close.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
    close.addTarget(self, action: #selector(cancel), for: .touchUpInside)
    close.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(close)
    NSLayoutConstraint.activate([
      label.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      label.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -48),
      close.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
      close.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
    ])
    DispatchQueue.global(qos: .userInitiated).async { [session] in session.startRunning() }
  }

  @objc private func cancel() { finish(nil) }

  func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
    guard let s = (objects.first as? AVMetadataMachineReadableCodeObject)?.stringValue else { return }
    finish(s)
  }

  private func finish(_ text: String?) {
    if sent { return }
    sent = true
    session.stopRunning()
    dismiss(animated: true) { [done] in done?(text) }
  }
}
