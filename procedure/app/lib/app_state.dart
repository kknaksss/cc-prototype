// 앱 상태 한 곳 — 서버 주소 · 로그인 · 판 스트림 · 토스트 · 조작 호출
import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api/api.dart';
import 'api/session_store.dart';
import 'config/server.dart';
import 'interpret/quick_speech.dart';
import 'model/account.dart';
import 'push/push.dart';
import 'sse/board_stream.dart';
import 'view/view.dart' show Me;
import 'widgets/ui.dart';

enum Phase { booting, loggedOut, loggedIn }

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

  AppState({ServerConfig? server, SessionStore? store, Api? api, BoardStream? stream, PushChannel? push})
      : server = server ?? ServerConfig(),
        store = store ?? SessionStore(),
        push = push ?? PushChannel() {
    this.api = api ?? Api(base: () => this.server.base, token: () => session?.token);
    this.stream = stream ??
        BoardStream(
          uri: () => this.api.streamUri(session?.token ?? ''),
          onUnauthorized: () => logout(message: '로그인이 풀렸어요 — 다시 로그인하세요'),
        );
  }

  // 시작 — 저장된 서버 주소 · 토큰. GET /api/auth/me 200 이면 로그인 건너뜀 · 401 이면 로그인으로(§6.1)
  Future<void> boot() async {
    WidgetsBinding.instance.addObserver(this);
    await server.load();
    try {
      deviceToken = (await SharedPreferences.getInstance()).getString(_tokenKey);
    } catch (_) {}
    push.onToken = _onDeviceToken;
    push.onTap = (v) => openVisit.value = v;
    final launched = await push.ready();
    if (launched != null) openVisit.value = launched;
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

  Future<void> login(String id) async {
    final s = await api.login(id);
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
      await api.registerDevice(token);
    } on ApiError {
      // 등록 실패는 조용히 — 다음 시작 · 로그인 때 다시
    }
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
    session = null;
    await store.clear();
    phase = Phase.loggedOut;
    if (message != null) toaster.show(message);
    notifyListeners();
  }

  // 조작 — 응답은 {ok…} 만, 화면은 SSE 로 바뀐다. 403 · 409 는 message 를 그대로 토스트
  Future<bool> run(Future<void> Function() action, [String? okMessage]) async {
    try {
      await action();
      if (okMessage != null) toaster.show(okMessage);
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
