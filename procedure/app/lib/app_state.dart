// 앱 상태 한 곳 — 서버 주소 · 로그인 · 판 스트림 · 탭 · 알림 배지 · 기기 · 토스트 · 조작 호출
import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api/api.dart';
import 'api/session_store.dart';
import 'config/server.dart';
import 'interpret/quick_speech.dart';
import 'model/account.dart';
import 'model/display.dart';
import 'model/notification.dart';
import 'push/push.dart';
import 'sse/board_stream.dart';
import 'view/view.dart' show Me;
import 'widgets/ui.dart';

enum Phase { booting, loggedOut, loggedIn }

// 4탭 차례(SPEC-004 §6.8) — 첫 화면 = 예약 현황(D7-60)
enum AppTab { reservations, visits, board, settings }

// 이 기기 배치(§5-1.1 kind · §6.0 짧은 변 600)
String deviceKind() {
  final views = WidgetsBinding.instance.platformDispatcher.views;
  if (views.isEmpty) return 'phone';
  final v = views.first;
  final size = v.physicalSize / v.devicePixelRatio;
  return size.shortestSide >= 600 ? 'tablet' : 'phone';
}

class AppState extends ChangeNotifier with WidgetsBindingObserver {
  final ServerConfig server;
  final SessionStore store;
  late final Api api;
  late final BoardStream stream;
  final Toaster toaster = Toaster();
  final QuickSpeech speech = QuickSpeech();
  final PushChannel push;

  Phase phase = Phase.booting;
  Session? session;

  // 받는 사람(나에게 온 호출 · 수락 버튼) — 의사 = 연결 원장 · 관리자 = 모든 호출(A-15)
  Me get me => switch (session) {
        Session(isAdmin: true) => const Me(admin: true),
        Session(isDoctor: true, :final staffId) => Me(staffId: staffId),
        _ => Me.none,
      };
  // 백그라운드로 가면 열린 통역을 닫으라고 알린다(드로어가 듣는다)
  final ValueNotifier<int> backgrounded = ValueNotifier(0);

  // 푸시(§5-1) — 기기 토큰 · 알림 권한 · 눌러서 열 룸(visitId · 로그인 전이면 로그인 뒤)
  String? deviceToken;
  NotifStatus notif = NotifStatus.unknown;
  final ValueNotifier<int?> openVisit = ValueNotifier(null);
  static const _tokenKey = 'push.deviceToken';

  // 기기 행 id(§5-3 · r2) — POST /api/devices 응답. 알림 거부 기기 = null(띄우기 · pending 안 씀). 로그아웃 · 계정 바뀜 때 지운다
  int? deviceId;
  // 이 기기 이름(설정 「이 기기」 · D7-70) — 고친 값을 기억해 다시 등록할 때 덮지 않는다
  String? deviceName;
  static const _deviceIdKey = 'push.deviceId';
  static const _deviceNameKey = 'device.name';

  // 탭(§6.8) · 상담사 호출로 열 예약(§5-2) · 종 배지 안 읽은 수(§5-4)
  final ValueNotifier<AppTab> tab = ValueNotifier(AppTab.reservations);
  final ValueNotifier<int?> openReservation = ValueNotifier(null);
  final ValueNotifier<int> unread = ValueNotifier(0);

  AppState({ServerConfig? server, SessionStore? store, Api? api, BoardStream? stream, PushChannel? push})
      : server = server ?? ServerConfig(),
        store = store ?? SessionStore(),
        push = push ?? PushChannel() {
    this.api = api ?? Api(base: () => this.server.base, token: () => session?.token);
    this.stream = stream ??
        BoardStream(
          uri: () => this.api.streamUri(session?.token ?? '', deviceId: deviceId),
          onUnauthorized: () => logout(message: '로그인이 풀렸어요 — 다시 로그인하세요'),
        );
    this.stream.onEvent = _onStreamEvent;
    this.stream.addListener(_onStreamChange);
  }

  // SSE notification {unread} → 종 배지(§7.1 · §5-4) · display → 이 기기 것이면 pending 을 읽어 연다(§5-3 ①)
  void _onStreamEvent(String event, Map<String, dynamic> data) {
    if (event == 'notification') {
      final n = data['unread'];
      if (n is num) unread.value = n.toInt();
    } else if (event == 'display' && isMyDisplay(data, deviceId)) {
      refreshDisplays();
    }
  }

  // 띄우기 — 열 차례(오래된 것 먼저). Shell 이 하나씩 연다 · 지금 문진 · 스캔 화면이면 끝날 때까지 기다린다(§5-3 · OQ-621)
  final ValueNotifier<List<DisplayReq>> displays = ValueNotifier(const []);
  // 이미 연 요청 id — pending 은 opened 도 돌려주므로(코디 확정 #1) 앞으로 올 때 · SSE 때 다시 열지 않게 거른다(r1 W1)
  final Set<int> _openedDisplays = {};

  void enqueueDisplays(List<DisplayReq> items) {
    final have = displays.value.map((x) => x.requestId).toSet();
    final add = items.where((x) =>
        !have.contains(x.requestId) && !_openedDisplays.contains(x.requestId) && (x.status == 'pending' || x.status == 'opened'));
    if (add.isNotEmpty) displays.value = [...displays.value, ...add];
  }

  void markDisplayOpened(int requestId) {
    _openedDisplays.add(requestId);
    displays.value = displays.value.where((x) => x.requestId != requestId).toList();
  }

  DisplayReq? takeDisplay() {
    final l = displays.value;
    if (l.isEmpty) return null;
    displays.value = l.sublist(1);
    _openedDisplays.add(l.first.requestId);
    return l.first;
  }

  // 이 기기 pending 읽기 — 로그인 · 앞으로 올 때 · SSE display · 띄우기 푸시. 기기 행 없는 앱은 부르지 않는다(r2)
  Future<void> refreshDisplays() async {
    final id = deviceId;
    if (session == null || id == null) return;
    try {
      enqueueDisplays(await api.pendingDisplays(id));
    } on ApiError {
      // 조용히 — 다음 기회에
    }
  }

  // [QR 읽기] 결과 → claim → 연다(§5-3 QR · D7-44)
  Future<bool> claimQr(String raw) async {
    final t = qrTokenOf(raw);
    if (t == null) {
      toaster.show('Céramique 고객 입력 QR 이 아니에요');
      return false;
    }
    try {
      final r = await api.claimDisplay(t, deviceId: deviceId);
      if (r != null) enqueueDisplays([r]);
      return r != null;
    } on ApiError catch (e) {
      toaster.show(e.message);
      return false;
    }
  }

  // SSE 가 (다시) 붙으면 종 배지를 다시 읽는다(§5-4 「SSE 연결 · 앞으로 올 때」)
  bool _wasConnected = false;
  void _onStreamChange() {
    if (stream.connected && !_wasConnected) refreshUnread();
    _wasConnected = stream.connected;
  }

  // 안 읽은 수 다시 읽기 — 실패(옛 back 404 · 네트워크)는 조용히 그대로
  Future<void> refreshUnread() async {
    if (session == null) return;
    try {
      final j = await api.notifications();
      final n = j['unread'];
      if (n is num) unread.value = n.toInt();
    } on ApiError {
      // 그대로
    }
  }

  // 알림을 누름(§5-1.3 · §5-2) — 원장 호출 = 시술 현황 탭 그 방 · 상담사 호출 = 예약 현황 탭 그 예약
  // markRead = 푸시를 눌러 연 때만 그 발송(callId · reservationId)으로 읽음 · 알림 목록 누름은 목록이 ids 로 읽는다(§5-4 · r1 W3)
  void _onTap(PushTap t, {bool markRead = true}) {
    switch (t.kind) {
      case PushKind.doctorCall:
        tab.value = AppTab.board;
        openVisit.value = t.visitId;
      case PushKind.counselorCall:
        tab.value = AppTab.reservations;
        openReservation.value = t.reservationId;
      case PushKind.display:
        refreshDisplays(); // 띄우기 푸시 → 그 화면(pending 이 돌려준다)
        return;
    }
    // 푸시를 눌러 연 발송의 알림 행을 읽음으로(§5-4 · 후속 #3)
    if (markRead && session != null && (t.callId != null || t.reservationId != null)) {
      api.readNotificationOf(callId: t.callId, reservationId: t.kind == PushKind.counselorCall ? t.reservationId : null).then((_) => refreshUnread(),
          onError: (_) => refreshUnread());
    } else {
      refreshUnread();
    }
  }

  // 알림 목록 항목 누름(§6.13) — 원장 호출 = 시술 현황 탭 그 방 · 상담사 호출 = 그 예약 상세
  void openNotification(AppNotification n) => _onTap(
      n.kind == 'counselor_call'
          ? PushTap(PushKind.counselorCall, reservationId: n.reservationId)
          : PushTap(PushKind.doctorCall, visitId: n.visitId),
      markRead: false);

  // 시작 — 저장된 서버 주소 · 토큰. GET /api/auth/me 200 이면 로그인 건너뜀 · 401 이면 로그인으로(§6.1)
  Future<void> boot() async {
    WidgetsBinding.instance.addObserver(this);
    await server.load();
    try {
      final p = await SharedPreferences.getInstance();
      deviceToken = p.getString(_tokenKey);
      deviceId = p.getInt(_deviceIdKey);
      deviceName = p.getString(_deviceNameKey);
    } catch (_) {}
    push.onToken = _onDeviceToken;
    push.onTap = _onTap;
    final launched = await push.ready();
    if (launched != null) _onTap(launched);
    final saved = await store.read();
    if (saved != null) {
      try {
        session = await api.me(saved.token);
        await store.write(session!);
        _enter();
        return;
      } on ApiError catch (e) {
        if (e.status != 401 && e.status != 403) {
          // 서버에 못 닿음 — 저장된 계정으로 들어가 스트림이 다시 붙기를 기다린다
          session = saved;
          _enter();
          return;
        }
        await store.clear();
      }
    }
    phase = Phase.loggedOut;
    notifyListeners();
  }

  Future<void> login(String id, String password) async {
    final s = await api.login(id, password);
    await store.writeLastId(id); // 아이디만 기억 — 비밀번호는 저장하지 않는다
    if (session?.id != s.id) await _setDeviceId(null); // 계정 바뀜 — 새로 등록해 받는다(r2)
    session = s;
    await store.write(s);
    _enter();
    // 로그인 직후 알림 권한 요청 → 허용되면 기기 토큰이 onToken 으로 온다(§5-1.1 ①②)
    final granted = await push.requestPermission();
    notif = granted ? NotifStatus.authorized : await push.status();
    notifyListeners();
  }

  void _enter() {
    phase = Phase.loggedIn;
    stream.reset();
    stream.start();
    notifyListeners();
    _refreshPush();
    refreshDisplays(); // 로그인 · 시작 때 놓친 띄우기(§5-3 ③)
  }

  // 앱 시작 · 다시 로그인 — 이미 허용이면 토큰을 다시 받아 등록(멱등)
  Future<void> _refreshPush() async {
    final s = session;
    if (s != null) await push.setAuth(server.base, s.token);
    notif = await push.status();
    if (notif == NotifStatus.authorized) {
      if (deviceToken != null) await _registerDevice(deviceToken!);
      await push.register();
    }
    notifyListeners();
  }

  Future<void> _onDeviceToken(String token) async {
    deviceToken = token;
    try {
      await (await SharedPreferences.getInstance()).setString(_tokenKey, token);
    } catch (_) {}
    await _registerDevice(token);
  }

  Future<void> _registerDevice(String token) async {
    if (session == null) return;
    try {
      deviceName ??= await push.deviceName();
      final id = await api.registerDevice(token, name: deviceName, kind: deviceKind());
      if (id != null && id != deviceId) {
        await _setDeviceId(id);
        stream.stop(); // SSE 를 deviceId 를 실어 다시 연다(§7.1)
        stream.start();
      }
      refreshDisplays();
    } on ApiError {
      // 등록 실패는 조용히 — 다음 시작 · 로그인 때 다시
    }
    notifyListeners();
  }

  Future<void> _setDeviceId(int? id) async {
    deviceId = id;
    try {
      final p = await SharedPreferences.getInstance();
      id == null ? await p.remove(_deviceIdKey) : await p.setInt(_deviceIdKey, id);
    } catch (_) {}
  }

  // 설정 「이 기기」 이름 고치기(§6.14 · D7-70) — POST /api/devices {token, name}
  Future<bool> renameDevice(String raw) async {
    final name = raw.trim();
    final t = deviceToken;
    if (t == null || name.isEmpty || name.length > 40) return false;
    final ok = await run(() async {
      await api.registerDevice(t, name: name, kind: deviceKind());
    }, '기기 이름을 바꿨어요');
    if (ok) {
      deviceName = name;
      try {
        await (await SharedPreferences.getInstance()).setString(_deviceNameKey, name);
      } catch (_) {}
      notifyListeners();
    }
    return ok;
  }

  // 로그아웃 — 기기 토큰 해제 먼저(§5-1.1 ③) → 토큰 지움 → 로그인 화면
  Future<void> logout({String? message}) async {
    final t = deviceToken;
    if (t != null && session != null) {
      try {
        await api.unregisterDevice(t);
      } on ApiError {
        // 이미 풀린 로그인(401) 등 — 그래도 로그아웃은 한다
      }
    }
    await push.clearAuth();
    stream.reset();
    await _setDeviceId(null);
    unread.value = 0;
    displays.value = const [];
    _openedDisplays.clear();
    tab.value = AppTab.reservations;
    session = null;
    await store.clear();
    phase = Phase.loggedOut;
    if (message != null) toaster.show(message);
    notifyListeners();
  }

  // 조작 — 응답은 {ok…} 만, 화면은 SSE 로 바뀐다. 403 · 409 는 message 를 그대로 토스트
  // actionLabel · onAction = 성공 토스트 버튼(예: [시작] · [종료] 의 [되돌리기] · 5초)
  Future<bool> run(Future<void> Function() action, [String? okMessage, String? actionLabel, VoidCallback? onAction]) async {
    try {
      await action();
      if (okMessage != null) toaster.show(okMessage, action: actionLabel, onAction: onAction);
      return true;
    } on ApiError catch (e) {
      if (e.status == 401) {
        await logout(message: '로그인이 풀렸어요 — 다시 로그인하세요');
      } else {
        toaster.show(e.message);
      }
      return false;
    }
  }

  // 앱 생명주기(SPEC-004 §7.1) — 백그라운드면 스트림 닫고, 앞으로 오면 다시(첫 스냅샷으로 전부 바뀜)
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final s = state;
    if (phase != Phase.loggedIn) return;
    if (s == AppLifecycleState.paused || s == AppLifecycleState.hidden) {
      stream.stop();
      backgrounded.value++;
    } else if (s == AppLifecycleState.resumed) {
      stream.start();
      refreshUnread();
      refreshDisplays();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    stream.dispose();
    toaster.dispose();
    super.dispose();
  }
}

// 위젯 트리에서 꺼내 쓰기
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child}) : super(notifier: state);
  static AppState of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;
  static AppState read(BuildContext context) => context.getInheritedWidgetOfExactType<AppScope>()!.notifier!;
}
