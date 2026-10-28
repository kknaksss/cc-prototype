// 알림 목록(SPEC-004 §6.13) — 폰 = 전체 화면([‹ 닫기] · [모두 읽음]) · 태블릿 = 오른쪽 시트.
// 항목 = 원장 호출 · 상담사 호출 둘만 · 점 색(원장 primary · 상담사 cons) · 안 읽은 것 파란 바탕 · 누르면 읽음 → 그 화면
import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../model/notification.dart';
import '../theme/tokens.dart';
import '../view/time.dart';
import '../widgets/header.dart' show DetailHeader;

class NotificationsScreen extends StatefulWidget {
  final bool sheet;
  const NotificationsScreen({super.key, this.sheet = false});
  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  NotificationList? _list;
  String? _error;
  late final AppState _app;

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    _app.unread.addListener(_load); // 새 알림(SSE notification) → 다시 읽기
    _load();
  }

  @override
  void dispose() {
    _app.unread.removeListener(_load);
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final l = NotificationList.fromJson(await _app.api.notifications());
      if (!mounted) return;
      setState(() {
        _list = l;
        _error = null;
      });
      if (_app.unread.value != l.unread) _app.unread.value = l.unread;
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _readAll() async {
    if (await _app.run(() => _app.api.readNotifications())) {
      _app.unread.value = 0;
      await _load();
    }
  }

  Future<void> _open(AppNotification n) async {
    if (n.unread) {
      await _app.run(() => _app.api.readNotifications([n.id]));
      _app.refreshUnread();
    }
    if (!mounted) return;
    Navigator.of(context).pop();
    _app.openNotification(n);
  }

  @override
  Widget build(BuildContext context) {
    final l = _list;
    final hasUnread = (l?.items ?? const []).any((n) => n.unread);
    // 머리 = 다른 상세와 같은 꼴 — [‹ 닫기] · 「알림」 정가운데 · [모두 읽음]
    final head = DetailHeader(
      back: '닫기',
      chevron: !widget.sheet,
      title: '알림',
      trailing: TextButton(
        onPressed: hasUnread ? _readAll : null,
        child: Text('모두 읽음', style: Typo.headingMd500.copyWith(color: hasUnread ? Ms.primary : Ms.gray500)),
      ),
    );
    Widget body;
    if (l == null && _error == null) {
      body = const Center(child: CircularProgressIndicator(strokeWidth: 2));
    } else if (l == null) {
      body = Center(child: Text(_error!, style: Typo.body500.copyWith(color: Ms.gray600)));
    } else if (l.items.isEmpty) {
      body = Center(child: Text('오늘 받은 알림이 없어요', style: Typo.body500.copyWith(color: Ms.gray600)));
    } else {
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView.builder(
          itemCount: l.items.length,
          itemBuilder: (_, i) => NotificationRow(n: l.items[i], onTap: () => _open(l.items[i])),
        ),
      );
    }
    return Material(
      color: Ms.white,
      child: SafeArea(
        left: false,
        child: Column(children: [head, Expanded(child: body)]),
      ),
    );
  }
}

class NotificationRow extends StatelessWidget {
  final AppNotification n;
  final VoidCallback onTap;
  const NotificationRow({super.key, required this.n, required this.onTap});

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          decoration: BoxDecoration(
            color: n.unread ? Ms.primary100 : Ms.white,
            border: const Border(bottom: BorderSide(color: Ms.gray200)),
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 8,
              height: 8,
              margin: const EdgeInsets.only(top: 7, right: 10),
              decoration: BoxDecoration(color: n.kind == 'counselor_call' ? Ms.cons : Ms.primary, shape: BoxShape.circle),
            ),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(n.title, style: Typo.body600)),
                  Text(hm(n.createdAt), style: Typo.caption400.copyWith(color: Ms.gray600, fontFeatures: tabular)),
                ]),
                const SizedBox(height: 2),
                Text(n.body, style: Typo.body400.copyWith(color: Ms.gray700)),
              ]),
            ),
          ]),
        ),
      );
}
