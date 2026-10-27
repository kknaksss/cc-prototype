// Céramique — 의료진 앱(Flutter · iOS · SPEC-004) · 4탭(예약 · 내원 · 시술 현황 · 설정)
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'app_state.dart';
import 'screens/login_screen.dart';
import 'screens/shell.dart';
import 'theme/tokens.dart';
import 'widgets/ui.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle.dark);
  final state = AppState();
  state.boot();
  runApp(ProcedureApp(state: state));
}

class ProcedureApp extends StatelessWidget {
  final AppState state;
  const ProcedureApp({super.key, required this.state});

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: state,
      child: MaterialApp(
        title: 'Céramique',
        debugShowCheckedModeBanner: false,
        theme: ceramiqueTheme(),
        locale: const Locale('ko'),
        // 태블릿 글자 배율(T4) — 기기 글자 크기 설정에 곱한다
        builder: (context, child) {
          final mq = MediaQuery.of(context);
          final k = uiScale(mq.size) * mq.textScaler.scale(1);
          return MediaQuery(
            data: mq.copyWith(textScaler: TextScaler.linear(k)),
            child: ToastLayer(toaster: state.toaster, child: child ?? const SizedBox()),
          );
        },
        home: const _Root(),
      ),
    );
  }
}

class _Root extends StatelessWidget {
  const _Root();
  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return switch (app.phase) {
      Phase.booting => const Scaffold(backgroundColor: Ms.gray100, body: Center(child: CircularProgressIndicator(strokeWidth: 2))),
      Phase.loggedOut => const LoginScreen(),
      Phase.loggedIn => const _Home(),
    };
  }
}

// 로그인 뒤 — 공통 틀(탭 4). 로그아웃하면 쌓인 화면도 같이 닫히게 Navigator 를 새로
class _Home extends StatelessWidget {
  const _Home();
  @override
  Widget build(BuildContext context) => Navigator(
        key: ValueKey(AppScope.of(context).session?.id),
        onGenerateRoute: (_) => MaterialPageRoute(builder: (_) => const Shell()),
      );
}
