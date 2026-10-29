// 설정(SPEC-004 §6.14 · D7-61) — 계정 · 알림(그 역할이 받는 종류만) · 이 기기 이름 · 앱 정보 · [로그아웃].
// 지점 · 구역 · 언어 칸은 없다(원천 없음)
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../model/account.dart';
import '../model/notification.dart';
import '../push/push.dart' show NotifStatus;
import '../theme/tokens.dart';
import '../widgets/ui.dart';
import 'board_screen.dart' show isTablet;
import 'shell.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  List<NotifSetting>? _settings;
  String? _error;
  String _version = '';

  @override
  void initState() {
    super.initState();
    _load();
    AppScope.read(context).push.appVersion().then((v) {
      if (mounted && v != null) setState(() => _version = v);
    });
  }

  Future<void> _load() async {
    final app = AppScope.read(context);
    try {
      final l = NotifSetting.listFrom(await app.api.notificationSettings());
      if (mounted) {
        setState(() {
          _settings = l;
          _error = null;
        });
      }
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _toggle(NotifSetting s, bool v) async {
    final app = AppScope.read(context);
    if (await app.run(() => app.api.setNotificationSetting(s.kind, v))) {
      await _load();
    }
  }

  Future<void> _rename() async {
    final app = AppScope.read(context);
    final ctl = TextEditingController(text: app.deviceName ?? '');
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Ms.white,
        title: Text('이 기기 이름', style: Typo.headingMd600),
        content: TextField(
          controller: ctl,
          autofocus: true,
          maxLength: 40,
          decoration: const InputDecoration(hintText: '예: 데스크 아이패드'),
          onSubmitted: (v) => Navigator.of(ctx).pop(v),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('취소')),
          TextButton(onPressed: () => Navigator.of(ctx).pop(ctl.text), child: const Text('저장')),
        ],
      ),
    );
    if (name != null && name.trim().isNotEmpty) await app.renameDevice(name);
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final s = app.session;
    final tablet = isTablet(context);
    final settings = _settings;
    return TabScaffold(
      tab: AppTab.settings,
      body: ListView(
        padding: EdgeInsets.fromLTRB(tablet ? 24 : 16, 16, tablet ? 24 : 16, 32),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 640),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                _Section('계정', [
                  _Row('이름', s?.name ?? ''),
                  _Row('역할', s == null ? '' : roleName[s.role]!),
                  _Row('아이디', s?.id ?? ''),
                ]),
                _Section('알림', [
                  if (app.notif == NotifStatus.denied)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                      child: Text('알림 꺼짐 · 설정에서 켜기', style: Typo.body600.copyWith(color: Ms.red)),
                    ),
                  if (settings == null && _error == null)
                    const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator(strokeWidth: 2)))
                  else if (settings == null)
                    _Row('알림 설정', _error!, muted: true)
                  else if (settings.isEmpty)
                    _Row('받는 알림이 없어요', '', muted: true)
                  else
                    for (final x in settings)
                      SwitchRow(notifKindName[x.kind]!, x.enabled, (v) => _toggle(x, v)),
                ]),
                // 이름은 이 기기에 먼저 두고 등록 때 보낸다(E2E batch 1 #2) — 기기 행이 없으면(알림 꺼짐) 웹 목록엔 아직 안 보임
                _Section('이 기기', [
                  _Row('기기 이름', '${app.deviceName ?? ''} ›', onTap: _rename),
                  if (app.deviceId == null) _Row('알림을 켜면 웹 기기 목록에 보여요', '', muted: true),
                ]),
                _Section('앱 정보', [
                  _Row('버전', _version),
                  if (kDebugMode) _Row('서버 주소', app.server.base),
                ]),
                const SizedBox(height: 16),
                MsButton('로그아웃', color: BtnColor.red, variant: BtnVariant.outlined, size: BtnSize.lg, expand: true, onPressed: () => app.logout()),
              ]),
            ),
          ),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  final List<Widget> rows;
  const _Section(this.title, this.rows);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 6),
            child: Text(title, style: Typo.caption600.copyWith(color: Ms.gray600)),
          ),
          Container(
            decoration: BoxDecoration(color: Ms.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: Ms.gray200)),
            child: Column(children: [
              for (var i = 0; i < rows.length; i++) ...[
                if (i > 0) const Divider(height: 1, thickness: 1, color: Ms.gray200, indent: 16),
                rows[i],
              ],
            ]),
          ),
        ]),
      );
}

class _Row extends StatelessWidget {
  final String k;
  final String v;
  final bool muted;
  final VoidCallback? onTap;
  const _Row(this.k, this.v, {this.muted = false, this.onTap});

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(children: [
            Expanded(child: Text(k, style: Typo.body500.copyWith(color: muted ? Ms.gray600 : Ms.gray800))),
            if (v.isNotEmpty)
              Flexible(
                child: Text(v,
                    textAlign: TextAlign.right,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Typo.body400.copyWith(color: onTap != null ? Ms.primary : Ms.gray600)),
              ),
          ]),
        ),
      );
}
