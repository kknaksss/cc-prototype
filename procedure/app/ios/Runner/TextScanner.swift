import AVFoundation
import Flutter
import UIKit
import Vision

// 카메라 · 글자 인식(SPEC-004 §5-3 QR · §6.16 여권 스캔) — 채널 "procedure/scan". 외부 서비스 0 · 기기 안에서만(D7-49).
//   scanQr → QR 글자(취소 = nil)
//   scanPassport({windows, windowSec}) → 여권 연속 스캔(E2E batch 1 #6): AVCaptureSession 영상 프레임에서 가이드 틀의 MRZ 자리만
//     Vision 으로 계속 읽고 → 후보 줄을 Dart(checkMrz — mrz.dart 검사 숫자)에 물어 맞으면 그 프레임을 자동 촬영
//     → {photo: JPEG(틀 영역 · 품질 0.8), lines} · windowSec 초씩 windows 번 못 읽음 또는 [손으로 입력] → {failed: true} · [닫기] = nil
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
                                        windowSec: (a?["windowSec"] as? Double) ?? 8)
        // 후보 줄 → Dart 검사(검사 숫자 규칙은 mrz.dart 한 곳)
        vc.check = { [weak self] lines, answer in
          guard let ch = self?.channel else { return answer(false) }
          ch.invokeMethod("checkMrz", arguments: lines) { r in answer((r as? Bool) == true) }
        }
        vc.done = { out in result(out) }
        vc.modalPresentationStyle = .fullScreen
        self.top?.present(vc, animated: true)
      }
    default:
      result(FlutterMethodNotImplemented)
    }
  }
}

// 여권 연속 스캔(§6.16 ① · E2E batch 1 #6)
// - 카메라: 자동 매크로가 되는 가상 기기 먼저(builtInTripleCamera → builtInDualWideCamera → builtInWideAngleCamera).
//   가상 기기는 확대 1 = 초광각이라 첫 전환 배율(= 보통 「1x」 광각)로 두고, 가까우면 iOS 가 초광각(매크로)으로 스스로 바꾼다
//   광각만 있는 기기는 최소 초점거리에 맞춰 조금 확대(가까이 대지 않아도 틀이 차게)
// - 프레임마다(앞 것이 끝난 뒤) 가이드 틀 아래 MRZ 자리만 Vision 글자 인식 → 44자 안팎 두 줄 후보면 Dart 검사 → 맞으면 그 프레임을 찍음
// - windowSec 초 동안 못 읽으면 실패 1번(n / windows) · windows 번이면 끝(failed) · 1번 실패 뒤 [손으로 입력] 보임
final class PassportScanController: UIViewController, AVCaptureVideoDataOutputSampleBufferDelegate {
  var check: (([String], @escaping (Bool) -> Void) -> Void)?
  var done: (([String: Any]?) -> Void)?

  private let device: AVCaptureDevice
  private let windows: Int
  private let windowSec: Double
  private let session = AVCaptureSession()
  private let queue = DispatchQueue(label: "procedure.scan.video")
  private let preview = AVCaptureVideoPreviewLayer()
  private let dim = CAShapeLayer()
  private let frameLine = CAShapeLayer()
  private let mrzLine = CAShapeLayer()
  private let titleLabel = UILabel()
  private let tipLabel = UILabel()
  private let statusLabel = UILabel()
  private let manualButton = UIButton(type: .system)
  private let ci = CIContext()

  // video 큐에서만 — 지금 읽는 중 · 끝남 · 마지막 읽은 때 · 화면 → 이미지 변환(main 에서 정해 넘김)
  private var busy = false
  private var finished = false
  private var lastRun = Date.distantPast
  private var roi = CGRect(x: 0.1, y: 0.3, width: 0.8, height: 0.15) // Vision 정규화(왼쪽 아래 원점)
  private var crop = CGRect(x: 0.1, y: 0.3, width: 0.8, height: 0.5)
  private var visionOrientation = CGImagePropertyOrientation.right

  private var fails = 0
  private var timer: Timer?
  private var sent = false

  init(device: AVCaptureDevice, windows: Int, windowSec: Double) {
    self.device = device
    self.windows = max(1, windows)
    self.windowSec = max(2, windowSec)
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
    tipLabel.text = "아래 두 줄(MRZ)이 점선 안에 · 빛 반사가 없게\n맞으면 자동으로 찍혀요"
    tipLabel.font = .systemFont(ofSize: 14)
    statusLabel.font = .systemFont(ofSize: 15, weight: .semibold)
    statusLabel.text = "읽는 중…"
    for l in [titleLabel, tipLabel, statusLabel] {
      l.textColor = .white
      l.textAlignment = .center
      l.numberOfLines = 0
      l.translatesAutoresizingMaskIntoConstraints = false
      view.addSubview(l)
    }
    let close = UIButton(type: .system)
    close.setTitle("닫기", for: .normal)
    close.setTitleColor(.white, for: .normal)
    close.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
    close.addTarget(self, action: #selector(cancel), for: .touchUpInside)
    close.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(close)
    manualButton.setTitle("손으로 입력", for: .normal)
    manualButton.setTitleColor(.white, for: .normal)
    manualButton.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
    manualButton.layer.borderColor = UIColor.white.cgColor
    manualButton.layer.borderWidth = 1.5
    manualButton.layer.cornerRadius = 10
    manualButton.contentEdgeInsets = UIEdgeInsets(top: 10, left: 20, bottom: 10, right: 20)
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
      statusLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      statusLabel.bottomAnchor.constraint(equalTo: manualButton.topAnchor, constant: -16),
      tipLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      tipLabel.bottomAnchor.constraint(equalTo: statusLabel.topAnchor, constant: -10),
      tipLabel.widthAnchor.constraint(lessThanOrEqualTo: view.widthAnchor, constant: -32),
      manualButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      manualButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -24),
    ])
  }

  override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    queue.async { [session] in session.startRunning() }
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

  // 지금 화면 방향 → 미리보기 회전 · Vision 방향(가로는 iPad 만)
  private func orientation() -> (AVCaptureVideoOrientation, CGImagePropertyOrientation) {
    switch view.window?.windowScene?.interfaceOrientation ?? .portrait {
    case .landscapeRight: return (.landscapeRight, .up)
    case .landscapeLeft: return (.landscapeLeft, .down)
    case .portraitUpsideDown: return (.portraitUpsideDown, .left)
    default: return (.portrait, .right)
    }
  }

  // 가이드 틀(사진면 125 × 88) · 아래 MRZ 자리 · 어두운 바깥 — 그리고 틀 · MRZ 자리를 이미지 정규화 좌표로
  private func layoutGuide() {
    let b = view.bounds
    guard b.width > 0, b.height > 0 else { return }
    let (vo, io) = orientation()
    if let c = preview.connection, c.isVideoOrientationSupported { c.videoOrientation = vo }
    let w = min(b.width * 0.8, b.height * 0.55 * 125 / 88)
    let h = w * 88 / 125
    let box = CGRect(x: (b.width - w) / 2, y: b.height * 0.45 - h / 2, width: w, height: h)
    let mrz = CGRect(x: box.minX + 6, y: box.maxY - h * 0.27, width: box.width - 12, height: h * 0.27 - 6)
    let hole = UIBezierPath(rect: b)
    hole.append(UIBezierPath(roundedRect: box, cornerRadius: 12))
    dim.path = hole.cgPath
    frameLine.path = UIBezierPath(roundedRect: box, cornerRadius: 12).cgPath
    mrzLine.path = UIBezierPath(roundedRect: mrz, cornerRadius: 6).cgPath

    // 화면 → 이미지(aspect fill) — 센서 1920 × 1080 을 방향대로 세운 크기
    let dims = CMVideoFormatDescriptionGetDimensions(device.activeFormat.formatDescription)
    var iw = CGFloat(max(dims.width, dims.height)), ih = CGFloat(min(dims.width, dims.height))
    if session.sessionPreset == .hd1920x1080 { iw = 1920; ih = 1080 }
    let portrait = io == .right || io == .left
    let imgW = portrait ? ih : iw, imgH = portrait ? iw : ih
    let k = max(b.width / imgW, b.height / imgH)
    let ox = (b.width - imgW * k) / 2, oy = (b.height - imgH * k) / 2
    func norm(_ r: CGRect, pad: CGFloat) -> CGRect {
      let x = (r.minX - pad - ox) / k / imgW, y = (r.minY - pad - oy) / k / imgH
      let rw = (r.width + pad * 2) / k / imgW, rh = (r.height + pad * 2) / k / imgH
      return CGRect(x: x, y: 1 - y - rh, width: rw, height: rh).intersection(CGRect(x: 0, y: 0, width: 1, height: 1))
    }
    let roiN = norm(mrz, pad: 14) // 조금 넉넉히(틀에 딱 맞추지 않아도)
    let cropN = norm(box, pad: 10)
    queue.async { [weak self] in
      self?.roi = roiN
      self?.crop = cropN
      self?.visionOrientation = io
    }
  }

  // ---------------------------------------------------------------- 실패 창(windowSec 초씩 windows 번)
  private func startWindow() {
    timer?.invalidate()
    timer = Timer.scheduledTimer(withTimeInterval: windowSec, repeats: false) { [weak self] _ in self?.windowFailed() }
  }

  private func windowFailed() {
    guard !sent else { return }
    fails += 1
    if fails >= windows { return finish(["failed": true]) }
    statusLabel.text = "아직 못 읽었어요 (\(fails) / \(windows)) · 조금 멀리 · 반사 없게"
    manualButton.isHidden = false
    UINotificationFeedbackGenerator().notificationOccurred(.warning)
    startWindow()
  }

  @objc private func cancel() { finish(nil) }
  @objc private func manual() { finish(["failed": true]) }

  private func finish(_ out: [String: Any]?) {
    guard !sent else { return }
    sent = true
    timer?.invalidate()
    queue.async { [session, weak self] in
      self?.finished = true
      session.stopRunning()
    }
    dismiss(animated: true) { [done] in done?(out) }
  }

  // ---------------------------------------------------------------- 프레임(video 큐)
  func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
    guard !busy, !finished, Date().timeIntervalSince(lastRun) > 0.12,
          let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
    busy = true
    lastRun = Date()
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false // MRZ 는 사전 단어가 아니다
    req.recognitionLanguages = ["en-US"]
    req.regionOfInterest = roi
    let h = VNImageRequestHandler(cvPixelBuffer: pixels, orientation: visionOrientation, options: [:])
    try? h.perform([req])
    let lines = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    // 후보 = '<' 가 든 긴 줄 둘 이상(TD3 44자 — 인식이 조금 덜 · 더 읽어도)
    let long = lines.filter { $0.count >= 30 && $0.contains("<") }
    guard long.count >= 2, let jpeg = jpeg(pixels) else { busy = false; return }
    DispatchQueue.main.async { [weak self] in
      guard let self, !self.sent, let check = self.check else { self?.queue.async { self?.busy = false }; return }
      check(lines) { ok in
        if ok {
          UINotificationFeedbackGenerator().notificationOccurred(.success)
          self.finish(["photo": FlutterStandardTypedData(bytes: jpeg), "lines": lines])
        } else {
          self.queue.async { self.busy = false }
        }
      }
    }
  }

  // 그 프레임의 틀 영역만 JPEG(긴 변 2000 이하 · 품질 0.8) — 메모리에서만
  private func jpeg(_ pixels: CVPixelBuffer) -> Data? {
    var img = CIImage(cvPixelBuffer: pixels).oriented(visionOrientation)
    let e = img.extent
    let r = CGRect(x: e.minX + crop.minX * e.width, y: e.minY + crop.minY * e.height, width: crop.width * e.width, height: crop.height * e.height)
    if r.width > 10, r.height > 10 { img = img.cropped(to: r) }
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
