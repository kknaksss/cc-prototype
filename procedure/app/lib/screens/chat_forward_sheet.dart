// 전달 시트 — 길게 누르기 [공유](SPEC-007 §10.14 · D9-62 ~ D9-64 · r4 · 사용자 스샷 = 카톡 「공유」 시트). 시안 없음 — 기존 위젯 · 토큰만.
//   틀 = 폰 바텀 시트(손잡이 · 끌어 내리면 닫힘) · 아이패드 가운데 · 머리 [✕] 「공유」 [전송 N]
//   검색(이름 · 대화방 · 초성) · 칩 [전체][사람] · 고른 것 줄(StatusChip + ✕) · 「대화방」(내 방 − 비활성 상대 1:1) + 「직원」(상대 목록) · 동그라미 최대 10
//   같은 사람이 두 번 보이지 않게(r4 처분 OQ-960): 1:1 방이 있는 직원은 [전체]에서 그 1:1 방으로만 · [사람] = 직원 한 번씩(1:1 이 있으면 그 방으로 보냄)
//   결과(OQ-959): 전부 됨 = 닫힘 + 「보냈어요」 · 일부 실패 = 시트 남김 · 실패한 곳만 고른 채 + 「N곳에 보내지 못했어요」 ·
//   전부 실패 = 닫힘 + 첫 실패 문구 · 요청 4xx = 닫힘 + message · 네트워크 · 5xx = 시트 남김 + 「보내지 못했어요」 · 다시 [전송] = 같은 clientId
import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api.dart' show ApiError;
import '../app_state.dart';
import '../chat/chat_model.dart';
import '../chat/chat_search.dart';
import '../chat/chat_ui.dart';
import '../chat/chat_view.dart';
import '../theme/tokens.dart';
import '../widgets/header.dart' show isTabletWidth;
import '../widgets/resv_ui.dart' show StatusChip;
import '../widgets/ui.dart';
import '../widgets/sheet.dart';

const forwardLimit = 10;
const forwardLimitText = '한 번에 10곳까지 보낼 수 있어요';

Future<void> openForwardSheet(BuildContext context, ChatMessage m) {
  // 보내는 중 = 닫히지 않음(바깥 누름 · 뒤로 · 끌어 내림 · [✕] — review-code r3 W3-3 · SPEC §10.14 「시트는 응답까지 열려 있다」)
  final busy = ValueNotifier(false);
  if (isTabletWidth(context)) {
    return showDialog<void>(
      context: context,
      barrierColor: Ms.dim,
      builder: (ctx) => Dialog(
        backgroundColor: Ms.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: 520, maxHeight: MediaQuery.sizeOf(ctx).height * 0.8),
          child: Padding(padding: const EdgeInsets.only(top: 12), child: ChatForwardSheet(message: m, busy: busy)),
        ),
      ),
    );
  }
  // 높이 = 놓인 칸(위 안전 영역 뺀 · 키보드가 열리면 그만큼 줄어든 칸) × 0.88 — 머리가 늘 상태 표시줄 아래(W3-1 · D9-65 와 같은 규칙)
  return showAppSheet<void>(
    context: context,
    heightFactor: 0.88,
    busy: busy,
    builder: (ctx) => SafeArea(top: false, child: Column(children: [const SheetHandle(), Expanded(child: ChatForwardSheet(message: m, busy: busy))])),
  );
}

// 고를 수 있는 한 곳 — key 가 같으면 같은 곳(1:1 방 = 그 사람 · OQ-960)
class _Pick {
  final String key;
  final String label;
  final Widget? badge;
  final ForwardTarget Function(String clientId) target;
  const _Pick(this.key, this.label, this.target, {this.badge});
}

class ChatForwardSheet extends StatefulWidget {
  final ChatMessage message;
  final ValueNotifier<bool>? busy; // 보내는 중(시트를 연 쪽이 닫힘을 막는다)
  const ChatForwardSheet({super.key, required this.message, this.busy});
  @override
  State<ChatForwardSheet> createState() => _ChatForwardSheetState();
}

class _ChatForwardSheetState extends State<ChatForwardSheet> {
  late final AppState _app = AppScope.read(context);
  final _search = TextEditingController();
  bool _peopleOnly = false;
  List<Person>? _people;
  bool _peopleFailed = false;
  final List<_Pick> _picked = []; // 고른 차례 = 대상 차례
  final Map<String, String> _clientIds = {}; // 시트가 열린 동안 곳마다 같은 clientId(다시 [전송] = 두 번 가지 않음 · D9-16)
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _app.api.chatPeople().then((l) {
      if (mounted) setState(() => _people = l);
    }, onError: (Object _) {
      if (mounted) setState(() => _peopleFailed = true);
    });
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  // 1:1 상대 id → 그 방(비활성 상대 1:1 은 forwardRooms 에 없음)
  Map<int, Room> get _directs => {
        for (final r in _app.chat.forwardRooms)
          if (!r.group && r.peer != null) r.peer!.id: r
      };

  _Pick _roomPick(Room r) => !r.group && r.peer != null
      ? _Pick('p:${r.peer!.id}', roomTitle(r), (c) => ForwardTarget.room(r.id, c), badge: roleBadge(r.peer!.role))
      : _Pick('r:${r.id}', roomTitle(r), (c) => ForwardTarget.room(r.id, c),
          badge: Text('${r.memberCount}명', style: Typo.caption500.copyWith(color: Ms.gray600)));

  _Pick _personPick(Person p) {
    final d = _directs[p.id];
    return _Pick('p:${p.id}', p.name, (c) => d != null ? ForwardTarget.room(d.id, c) : ForwardTarget.person(p.id, c), badge: roleBadge(p.role));
  }

  void _toggle(_Pick p) {
    setState(() {
      final i = _picked.indexWhere((x) => x.key == p.key);
      if (i >= 0) {
        _picked.removeAt(i);
      } else if (_picked.length >= forwardLimit) {
        _app.toaster.show(forwardLimitText);
      } else {
        _picked.add(p);
      }
    });
  }

  void _setSending(bool v) {
    if (mounted) setState(() => _sending = v);
    widget.busy?.value = v;
  }

  // 결과 토스트는 시트가 어떻게든 닫혔어도 띄운다(서버는 이미 보냈을 수 있다 — W3-3) · 닫기 · 상태 바꾸기만 mounted 를 본다
  Future<void> _send() async {
    if (_picked.isEmpty || _sending) return;
    final picks = [..._picked];
    final targets = [for (final p in picks) p.target(_clientIds.putIfAbsent(p.key, newClientId))];
    _setSending(true);
    final nav = Navigator.of(context);
    final toaster = _app.toaster;
    void close() {
      widget.busy?.value = false;
      if (mounted) nav.pop();
    }

    try {
      final results = await _app.chat.forward(widget.message, targets);
      final failed = <String>{};
      String? firstError;
      for (var i = 0; i < picks.length; i++) {
        final r = i < results.length ? results[i] : null;
        if (r == null || !r.ok) {
          failed.add(picks[i].key);
          firstError ??= r?.errorMessage ?? '보내지 못했어요';
        }
      }
      if (failed.isEmpty) {
        close();
        toaster.show('보냈어요');
      } else if (failed.length == picks.length) {
        close();
        toaster.show(firstError!);
      } else {
        // 일부 실패 — 시트 남김 · 실패한 곳만 고른 채(OQ-959)
        if (mounted) {
          setState(() {
            _picked.removeWhere((p) => !failed.contains(p.key));
            _clientIds.removeWhere((k, _) => !failed.contains(k));
          });
        }
        _setSending(false);
        toaster.show('${failed.length}곳에 보내지 못했어요');
      }
    } on ApiError catch (e) {
      if (e.status == 401) {
        close();
        unawaited(_app.chat.onUnauthorized());
      } else if (e.status >= 400 && e.status < 500) {
        close();
        toaster.show(e.message);
      } else {
        _setSending(false); // 네트워크 · 5xx · 시간 넘김 — 고른 것 그대로 · 다시 [전송]
        toaster.show('보내지 못했어요');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final q = _search.text.trim();
    final directs = _directs;
    final rooms = _peopleOnly ? const <_Pick>[] : [for (final r in _app.chat.forwardRooms) if (nameMatches(roomTitle(r), q)) _roomPick(r)];
    final people = [
      for (final p in _people ?? const <Person>[])
        if ((_peopleOnly || !directs.containsKey(p.id)) && nameMatches(p.name, q)) _personPick(p)
    ];
    final empty = rooms.isEmpty && people.isEmpty && _people != null;
    final n = _picked.length;
    // 보내는 중 = 뒤로 · 바깥 누름(아이패드 대화상자 포함)으로 안 닫힘(W3-3)
    return PopScope(canPop: !_sending, child: _body(rooms, people, empty, n));
  }

  Widget _body(List<_Pick> rooms, List<_Pick> people, bool empty, int n) {
    return Column(children: [
      // 머리 [✕] 「공유」 [전송 N]
      Padding(
        padding: const EdgeInsets.fromLTRB(4, 0, 12, 4),
        child: Row(children: [
          IconButton(
            key: const Key('fwd-close'),
            tooltip: '닫기',
            onPressed: _sending ? null : () => Navigator.of(context).pop(), // 보내는 중 = 꺼짐(W3-3)
            icon: Icon(Icons.close_rounded, color: _sending ? Ms.gray400 : Ms.gray700),
          ),
          Expanded(child: Text('공유', textAlign: TextAlign.center, style: Typo.headingMd600)),
          SizedBox(
            width: 104,
            child: Align(
              alignment: Alignment.centerRight,
              child: _sending
                  ? Row(key: const Key('fwd-sending'), mainAxisSize: MainAxisSize.min, children: [
                      const SizedBox.square(dimension: 14, child: CircularProgressIndicator(strokeWidth: 2)),
                      const SizedBox(width: 6),
                      Text('보내는 중…', style: Typo.caption600.copyWith(color: Ms.gray600)),
                    ])
                  : MsButton(n == 0 ? '전송' : '전송 $n', key: const Key('fwd-send'), size: BtnSize.sm, onPressed: n == 0 ? null : _send),
            ),
          ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: MsInput(
          fieldKey: const Key('fwd-search'),
          controller: _search,
          hint: '이름 · 대화방 검색(초성 가능)',
          icon: Icons.search_rounded,
          onChanged: (_) => setState(() {}),
        ),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
        child: Row(children: [
          StatusChip('전체', key: const Key('fwd-chip-all'), selected: !_peopleOnly, bg: !_peopleOnly ? Ms.primary100 : Ms.gray100,
              fg: !_peopleOnly ? Ms.primary : Ms.gray700, outline: !_peopleOnly ? Ms.primary : null, onTap: () => setState(() => _peopleOnly = false)),
          const SizedBox(width: 8),
          StatusChip('사람', key: const Key('fwd-chip-people'), selected: _peopleOnly, bg: _peopleOnly ? Ms.primary100 : Ms.gray100,
              fg: _peopleOnly ? Ms.primary : Ms.gray700, outline: _peopleOnly ? Ms.primary : null, onTap: () => setState(() => _peopleOnly = true)),
        ]),
      ),
      if (_picked.isNotEmpty)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
          child: SizedBox(
            height: 34,
            child: ListView(scrollDirection: Axis.horizontal, children: [
              for (final p in _picked)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: StatusChip(p.label,
                      key: Key('fwd-selected-${p.key}'), bg: Ms.primary100, fg: Ms.primary, outline: Ms.primary, onRemove: () => _toggle(p)),
                ),
            ]),
          ),
        ),
      const SizedBox(height: 8),
      Expanded(
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 16), children: [
          if (rooms.isNotEmpty) ...[_section('대화방'), for (final p in rooms) _row(p)],
          if (_people == null && !_peopleFailed) ...[
            _section('직원'),
            const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator(strokeWidth: 2))),
          ] else if (_peopleFailed) ...[
            _section('직원'),
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text('직원 목록을 불러오지 못했어요', key: const Key('fwd-people-failed'), style: Typo.body400.copyWith(color: Ms.gray600)),
            ),
          ] else if (people.isNotEmpty) ...[
            _section('직원'),
            for (final p in people) _row(p),
          ],
          if (empty)
            Padding(
              padding: const EdgeInsets.only(top: 32),
              child: Center(child: Text('찾는 대화방 · 직원이 없어요', style: Typo.body400.copyWith(color: Ms.gray600))),
            ),
        ]),
      ),
    ]);
  }

  Widget _section(String t) => Padding(
        padding: const EdgeInsets.only(top: 10, bottom: 6),
        child: Text(t, style: Typo.caption600.copyWith(color: Ms.gray600)),
      );

  Widget _row(_Pick p) {
    final on = _picked.any((x) => x.key == p.key);
    final dim = !on && _picked.length >= forwardLimit;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: MsCard(
        key: Key('fwd-row-${p.key}'),
        selected: on,
        onTap: () => _toggle(p),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(children: [
          Flexible(child: Text(p.label, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600)),
          if (p.badge != null) ...[const SizedBox(width: 6), p.badge!],
          const Spacer(),
          Opacity(
            opacity: dim ? 0.35 : 1,
            child: Container(
              key: Key('fwd-pick-${p.key}'),
              width: 24,
              height: 24,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: on ? Ms.primary : Ms.white,
                border: Border.all(color: on ? Ms.primary : Ms.gray400, width: 1.5),
              ),
              child: on ? const Icon(Icons.check_rounded, size: 16, color: Ms.white) : null,
            ),
          ),
        ]),
      ),
    );
  }
}
