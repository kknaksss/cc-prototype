import AVFoundation
import Flutter
import UIKit
import Vision

// 카메라 · 글자 인식(SPEC-004 §5-3 QR · §6.16 여권 스캔) — 채널 "procedure/scan". 외부 서비스 0 · 기기 안에서만(D7-49).
//   scanQr → QR 글자(취소 = nil) · takePassportPhoto → JPEG(긴 변 2000 · 품질 0.8 · 취소 = nil) · recognizeText(bytes) → 줄 목록
//   카메라가 없으면(시뮬레이터) FlutterError "no_camera"
// 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 찍은 사진은 사진첩에 저장하지 않고 메모리로만 Dart 에 넘긴다(§6.16 원본 · D7-50).
// 이 파일은 사진을 디스크 · 사진첩 · 로그에 쓰지 않는다.
final class TextScanner: NSObject {
  private var channel: FlutterMethodChannel?
  private var pending: FlutterResult?

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

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    switch call.method {
    case "scanQr":
      guard AVCaptureDevice.default(for: .video) != nil else { return result(FlutterError(code: "no_camera", message: "카메라가 없어요", details: nil)) }
      let vc = QrViewController()
      vc.done = { text in result(text) }
      vc.modalPresentationStyle = .fullScreen
      top?.present(vc, animated: true)
    case "takePassportPhoto":
      guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
        return result(FlutterError(code: "no_camera", message: "카메라가 없어요", details: nil))
      }
      pending = result
      let p = UIImagePickerController()
      p.sourceType = .camera
      p.cameraCaptureMode = .photo
      p.delegate = self
      p.cameraOverlayView = PassportGuide(frame: UIScreen.main.bounds)
      p.modalPresentationStyle = .fullScreen
      top?.present(p, animated: true)
    case "recognizeText":
      guard let data = (call.arguments as? FlutterStandardTypedData)?.data, let cg = UIImage(data: data)?.cgImage else {
        return result(FlutterError(code: "bad_image", message: "사진을 읽지 못했어요", details: nil))
      }
      DispatchQueue.global(qos: .userInitiated).async {
        let req = VNRecognizeTextRequest()
        req.recognitionLevel = .accurate
        req.usesLanguageCorrection = false // MRZ 는 사전 단어가 아니다
        let h = VNImageRequestHandler(cgImage: cg, options: [:])
        try? h.perform([req])
        let lines = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
        DispatchQueue.main.async { result(lines) }
      }
    default:
      result(FlutterMethodNotImplemented)
    }
  }
}

extension TextScanner: UIImagePickerControllerDelegate, UINavigationControllerDelegate {
  func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
    let img = info[.originalImage] as? UIImage
    picker.dismiss(animated: true)
    let r = pending
    pending = nil
    guard let img else { r?(nil); return }
    r?(Self.jpeg(img).map { FlutterStandardTypedData(bytes: $0) })
  }

  func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
    picker.dismiss(animated: true)
    pending?(nil)
    pending = nil
  }

  // 긴 변 2000px · 품질 0.8(§6.16 ④) — 메모리에서만
  static func jpeg(_ img: UIImage) -> Data? {
    let long = max(img.size.width, img.size.height)
    let k = long > 2000 ? 2000 / long : 1
    let size = CGSize(width: floor(img.size.width * k), height: floor(img.size.height * k))
    let fmt = UIGraphicsImageRendererFormat()
    fmt.scale = 1
    let out = UIGraphicsImageRenderer(size: size, format: fmt).image { _ in img.draw(in: CGRect(origin: .zero, size: size)) }
    return out.jpegData(compressionQuality: 0.8)
  }
}

// 여권 촬영 가이드 틀(§6.16 ① — 사진면 125 × 88 · 아래 MRZ 두 줄 자리) · 안내 문구. 누름은 아래 카메라로 넘긴다
final class PassportGuide: UIView {
  override init(frame: CGRect) {
    super.init(frame: frame)
    isUserInteractionEnabled = false
    backgroundColor = .clear
  }
  required init?(coder: NSCoder) { fatalError() }

  override func draw(_ rect: CGRect) {
    let w = rect.width * 0.86
    let h = w * 88 / 125
    let box = CGRect(x: (rect.width - w) / 2, y: rect.height * 0.42 - h / 2, width: w, height: h)
    UIColor.white.setStroke()
    let p = UIBezierPath(roundedRect: box, cornerRadius: 12)
    p.lineWidth = 3
    p.stroke()
    // MRZ 두 줄 자리(아래 22%)
    let mrz = CGRect(x: box.minX + 8, y: box.maxY - h * 0.22, width: box.width - 16, height: h * 0.22 - 8)
    let d = UIBezierPath(roundedRect: mrz, cornerRadius: 6)
    d.setLineDash([8, 6], count: 2, phase: 0)
    d.lineWidth = 2
    UIColor(white: 1, alpha: 0.85).setStroke()
    d.stroke()
    let attrs: [NSAttributedString.Key: Any] = [.font: UIFont.systemFont(ofSize: 17, weight: .semibold), .foregroundColor: UIColor.white]
    let tip: [NSAttributedString.Key: Any] = [.font: UIFont.systemFont(ofSize: 14), .foregroundColor: UIColor(white: 1, alpha: 0.85)]
    let t1 = "여권 사진면을 틀에 맞춰 주세요" as NSString
    let t2 = "아래 두 줄(MRZ)이 점선 안에 · 빛 반사가 없게" as NSString
    let s1 = t1.size(withAttributes: attrs)
    t1.draw(at: CGPoint(x: (rect.width - s1.width) / 2, y: box.minY - s1.height - 36), withAttributes: attrs)
    let s2 = t2.size(withAttributes: tip)
    t2.draw(at: CGPoint(x: (rect.width - s2.width) / 2, y: box.maxY + 16), withAttributes: tip)
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
