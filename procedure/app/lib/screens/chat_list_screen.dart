// 채팅 탭 루트(SPEC-007 §10.2 · §10.11 · DS:S1 · S2 · S13a ~ S13d) — 머리 = 지금 공통 헤더 그대로(TabScaffold · [Céramique][채팅][종] · D9-38)
// → 그 아래 제목 없는 줄에 [새 대화](오른쪽) → 방 목록. 아이패드 = 방 목록 칸 360(위 [새 대화]) + 오른쪽 대화 칸(뒤로 없음)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../chat/chat_model.dart';
import '../chat/chat_state.dart';
import '../chat/chat_ui.dart';
import '../theme/tokens.dart';
import '../widgets/header.dart' show isTabletWidth;
import '../widgets/ui.dart';
import 'chat_new_screen.dart';
import 'chat_room_screen.dart';
import 'shell.dart' show TabScaffold;

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with RouteAware {
  late final AppState _app = AppScope.read(context);
  ChatState get _chat => _app.chat;
  int? _selected; // 아이패드 오른쪽 칸
  bool _onTop = true; // 채팅 탭 스택 맨 위가 이 목록(아이패드 = 오른쪽 칸이 보고 있는 방)
  ModalRoute<void>? _route;

  @override
  void initState() {
    super.initState();
    _chat.openRequest.addListener(_onOpenRequest);
    _chat.removed.addListener(_onRemoved);
    if (!_chat.roomsLoaded) _chat.refreshRooms();
    WidgetsBinding.instance.addPostFrameCallback((_) => _onOpenRequest()); // 로그인 전 · 시작 때 누른 푸시
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final r = ModalRoute.of(context);
    if (r != _route && r is PageRoute<void>) {
      _chat.chatRoutes.unsubscribe(this);
      _route = r;
      _chat.chatRoutes.subscribe(this, r);
    }
  }

  @override
  void dispose() {
    _chat.chatRoutes.unsubscribe(this);
    _chat.openRequest.removeListener(_onOpenRequest);
    _chat.removed.removeListener(_onRemoved);
    final s = _selected;
    if (s != null) _chat.clearTop(s);
    super.dispose();
  }

  bool get _tablet => isTabletWidth(context);

  // 아이패드: 목록이 맨 위이고 오른쪽 칸에 방이 있으면 그 방이 보고 있는 방
  void _syncTop() {
    if (!_tablet) return;
    final s = _selected;
    if (s == null) return;
    _onTop ? _chat.setTop(s) : _chat.clearTop(s);
  }

  @override
  void didPushNext() {
    _onTop = false;
    _syncTop();
  }

  @override
  void didPopNext() {
    _onTop = true;
    _syncTop();
  }

  void _select(int roomId) {
    final old = _selected;
    if (old != null && old != roomId) _chat.clearTop(old);
    setState(() => _selected = roomId);
    _syncTop();
  }

  // 방 열기 — 폰 = 채팅 스택에 대화 · 아이패드 = 오른쪽 칸
  void open(Room r) {
    if (_tablet) return _select(r.id);
    final nav = Navigator.of(context);
    nav.popUntil((x) => x.isFirst);
    nav.push(chatRoomRoute(r.id));
  }

  // 푸시 누름 · 배너 [보기](§8 · §10.12) — 내 목록에 없으면(나감) 토스트 → 방 목록(OQ-923)
  Future<void> _onOpenRequest() async {
    final id = _chat.openRequest.value;
    if (id == null || !mounted || _app.session == null) return;
    _chat.openRequest.value = null;
    if (_chat.room(id) == null) await _chat.refreshRooms();
    if (!mounted) return;
    final r = _chat.room(id);
    if (r == null) {
      Navigator.of(context).popUntil((x) => x.isFirst);
      _app.toaster.show('대화방을 찾을 수 없어요');
      return;
    }
    open(r);
  }

  // 내 목록에서 빠진 방 — 아이패드 오른쪽 칸을 비운다(폰 대화 화면은 스스로 닫는다 — ChatRoomView)
  void _onRemoved() {
    final id = _chat.removed.value;
    if (id != null && mounted && _tablet && _selected == id) setState(() => _selected = null);
  }

  Future<void> _newChat() async {
    final r = await pickNewChat(context);
    if (r != null && mounted) open(r);
  }

  Widget _newRow() => Container(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
        decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
        child: Row(children: [
          const Spacer(),
          MsButton('새 대화', key: const Key('chat-new'), variant: BtnVariant.outlined, size: BtnSize.sm, onPressed: _newChat),
        ]),
      );

  Widget _list() => ListenableBuilder(
        listenable: _chat,
        builder: (context, _) {
          if (!_chat.roomsLoaded && _chat.rooms.isEmpty) return const Center(child: CircularProgressIndicator(strokeWidth: 2));
          if (_chat.rooms.isEmpty) return _empty();
          return RefreshIndicator(
            onRefresh: _chat.refreshRooms,
            child: ListView.builder(
              itemCount: _chat.rooms.length,
              itemBuilder: (context, i) {
                final r = _chat.rooms[i];
                return RoomRow(key: ValueKey('room-${r.id}'), room: r, selected: _tablet && _selected == r.id, onTap: () => open(r));
              },
            ),
          );
        },
      );

  // 빈 목록(DS:S2)
  Widget _empty() => Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.chat_bubble_outline_rounded, size: 40, color: Ms.gray500),
            const SizedBox(height: 12),
            Text('아직 대화가 없어요', style: Typo.headingMd600),
            const SizedBox(height: 6),
            Text('함께 일하는 직원을 골라 메시지와 사진을 보내 보세요. 한 명이면 1:1, 여러 명이면 그룹이에요.',
                textAlign: TextAlign.center, style: Typo.body400.copyWith(color: Ms.gray600)),
            const SizedBox(height: 16),
            MsButton('새 대화', onPressed: _newChat),
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) {
    if (!_tablet) return TabScaffold(tab: AppTab.chat, body: Column(children: [_newRow(), Expanded(child: _list())]));
    final s = _selected;
    return TabScaffold(
      tab: AppTab.chat,
      body: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(
          width: 360,
          decoration: const BoxDecoration(color: Ms.white, border: Border(right: BorderSide(color: Ms.gray200))),
          child: Column(children: [_newRow(), Expanded(child: _list())]),
        ),
        Expanded(
          child: s == null
              ? Center(child: Text('왼쪽에서 대화를 골라 주세요', style: Typo.body500.copyWith(color: Ms.gray600)))
              : ChatRoomView(key: ValueKey('pane-$s'), roomId: s, pane: true),
        ),
      ]),
    );
  }
}
