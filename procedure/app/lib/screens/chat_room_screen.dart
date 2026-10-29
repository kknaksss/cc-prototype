// 대화(SPEC-007 §10.4 ~ §10.7 · DS:S4 ~ S9b) — 폰 = 채팅 탭 스택의 상세 화면(DetailHeader 「‹ 채팅」 · 탭바 유지) ·
// 아이패드 = 오른쪽 칸(뒤로 없음 · D9-38). 말풍선 · 날짜 구분선 · 시스템 줄 · 그룹 보낸 사람 이름 · 보내는 중 · 실패 · 사진 · 길게 눌러 삭제
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../app_state.dart';
import '../chat/chat_model.dart';
import '../chat/chat_state.dart';
import '../chat/chat_ui.dart';
import '../chat/chat_view.dart';
import '../chat/photo_pick.dart';
import '../theme/tokens.dart';
import '../view/view.dart' show BadgeVariant;
import '../widgets/header.dart';
import '../widgets/ui.dart';
import 'chat_info_screen.dart';
import 'chat_photo_screen.dart';

const chatRoomRouteName = 'chat-room';

// 폰 — 채팅 탭 스택에 쌓는 대화(이름 = 참여자 추가 뒤 돌아올 자리)
Route<void> chatRoomRoute(int roomId) =>
    MaterialPageRoute(settings: RouteSettings(name: chatRoomRouteName, arguments: roomId), builder: (_) => ChatRoomView(roomId: roomId));

const _bubbleMax = 300.0;
const photoMaxWidth = 240.0; // OQ-927

class ChatRoomView extends StatefulWidget {
  final int roomId;
  final bool pane; // 아이패드 오른쪽 칸
  const ChatRoomView({super.key, required this.roomId, this.pane = false});
  @override
  State<ChatRoomView> createState() => _ChatRoomViewState();
}

class _ChatRoomViewState extends State<ChatRoomView> with RouteAware {
  late final AppState _app = AppScope.read(context);
  ChatState get _chat => _app.chat;
  final _text = TextEditingController();
  final _scroll = ScrollController();
  ModalRoute<void>? _route;
  int _shownLast = 0; // 그린 마지막 메시지 id — 새 메시지가 붙었는지
  double _extentBefore = 0;

  int get _id => widget.roomId;

  @override
  void initState() {
    super.initState();
    _chat.viewOpened(_id);
    if (!_chat.thread(_id).loaded) _chat.loadLatest(_id);
    _scroll.addListener(_onScroll);
    _chat.removed.addListener(_onRemoved);
    _chat.addListener(_onChat);
    if (widget.pane) WidgetsBinding.instance.addPostFrameCallback((_) => _chat.reevaluate());
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (widget.pane) return; // 아이패드 칸 = 목록(ChatScreen)이 맨 위를 안다
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
    _chat.removed.removeListener(_onRemoved);
    _chat.removeListener(_onChat);
    if (!widget.pane) _chat.clearTop(_id);
    _chat.viewClosed(_id);
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  // 채팅 스택 맨 위 = 보고 있는 방 후보(앞 · 채팅 탭 · 루트 위 화면 없음은 ChatState 가 본다 — D9-40)
  @override
  void didPush() => _chat.setTop(_id);
  @override
  void didPopNext() => _chat.setTop(_id);
  @override
  void didPushNext() => _chat.clearTop(_id);
  @override
  void didPop() => _chat.clearTop(_id);

  void _onRemoved() {
    if (_chat.removed.value == _id && mounted && !widget.pane) Navigator.of(context).popUntil((r) => r.isFirst);
  }

  // 위 끝에 닿으면 before 로 50 더(§5) — reverse 목록이라 위 끝 = maxScrollExtent
  void _onScroll() {
    final p = _scroll.position;
    if (p.pixels >= p.maxScrollExtent - 200) _chat.loadOlder(_id);
  }

  // 새 메시지 — 맨 아래 근처면 따라 내려가고(reverse 목록은 0 에 붙어 있음), 위를 보고 있으면 자리를 지킨다(OQ-927)
  void _onChat() {
    final last = _chat.thread(_id).lastId;
    if (last == _shownLast || !_scroll.hasClients) {
      _shownLast = last;
      return;
    }
    final prev = _shownLast;
    _shownLast = last;
    if (prev == 0) return;
    final p = _scroll.position;
    if (p.pixels <= 80) return;
    _extentBefore = p.maxScrollExtent;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      final d = _scroll.position.maxScrollExtent - _extentBefore;
      if (d > 0) _scroll.jumpTo(_scroll.position.pixels + d);
    });
  }

  void _send() {
    final t = _text.text.trim();
    if (t.isEmpty) return;
    _chat.sendText(_id, t);
    _text.clear();
    setState(() {});
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  Future<void> _photo() async {
    final src = await pickPhotoSource(context);
    if (src == null) return;
    try {
      final p = await pickChatPhoto(src);
      if (p == null) return;
      _chat.sendPhoto(_id, p.jpeg, p.width, p.height);
      if (_scroll.hasClients) _scroll.jumpTo(0);
    } on PhotoDenied {
      _app.toaster.show('설정에서 카메라(사진) 권한을 켜 주세요');
    } catch (_) {
      _app.toaster.show('사진을 불러오지 못했어요');
    }
  }

  Future<void> _info(Room r) async {
    if (widget.pane) return showRightSheet(context, ChatInfoScreen(roomId: r.id, sheet: true));
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ChatInfoScreen(roomId: r.id)));
  }

  Widget _header(Room? r) {
    final title = r == null ? '' : roomTitle(r);
    final head = r == null
        ? null
        : Row(mainAxisSize: MainAxisSize.min, children: [
            Flexible(child: Text(title, key: const Key('detail-title'), maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.headingMd600)),
            const SizedBox(width: 6),
            if (r.group)
              Text('${r.memberCount}명', style: Typo.caption500.copyWith(color: Ms.gray600))
            else if (r.peer != null)
              roleBadge(r.peer!.role),
            if (peerInactive(r)) ...[const SizedBox(width: 4), Text(inactiveMark, style: Typo.caption500.copyWith(color: Ms.gray600))],
          ]);
    return DetailHeader(
      back: widget.pane ? null : '채팅',
      title: title,
      titleWidget: head,
      trailing: r == null
          ? null
          : IconButton(
              tooltip: '방 정보',
              onPressed: () => _info(r),
              icon: const Icon(Icons.info_outline_rounded, color: Ms.gray700),
            ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final body = ListenableBuilder(
      listenable: _chat,
      builder: (context, _) {
        final r = _chat.room(_id);
        final t = _chat.thread(_id);
        return Column(children: [
          _header(r),
          Expanded(child: _messages(r, t)),
          if (r != null) peerInactive(r) ? _inactiveLine() : _inputBar(),
        ]);
      },
    );
    if (widget.pane) return Material(color: Ms.gray100, child: body);
    return Scaffold(backgroundColor: Ms.gray100, body: SafeArea(bottom: false, child: body));
  }

  Widget _messages(Room? r, ChatThread t) {
    if (!t.loaded && t.loading) return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    final items = buildChatItems(t.messages, t.pending, group: r?.group ?? false, mine: _chat.isMine);
    if (items.isEmpty) return const SizedBox.expand();
    final rev = items.reversed.toList();
    return ListView.builder(
      controller: _scroll,
      reverse: true,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      itemCount: rev.length + (t.hasOlder ? 1 : 0),
      itemBuilder: (context, i) {
        if (i == rev.length) {
          return const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator(strokeWidth: 2)));
        }
        return Padding(padding: const EdgeInsets.only(top: 10), child: _item(rev[i]));
      },
    );
  }

  Widget _item(ChatItem it) => switch (it) {
        DayItem(:final label) => Center(child: MsBadge(label, BadgeVariant.neutral, dot: false)),
        MessageItem(:final m, :final mine, :final name) => m.kind == MsgKind.system
            ? Center(child: Text(m.text ?? '', textAlign: TextAlign.center, style: Typo.caption500.copyWith(color: Ms.gray600)))
            : _messageRow(m, mine, name),
        PendingItem(:final p) => _pendingRow(p),
      };

  Widget _messageRow(ChatMessage m, bool mine, String? name) {
    final time = Text(bubbleTime(m.createdAt), style: Typo.caption400.copyWith(color: Ms.gray600));
    final bubble = m.deleted ? _deletedBubble(mine) : (m.photo != null ? _photoBubble(m) : _textBubble(m.text ?? '', mine));
    final row = Row(
      mainAxisAlignment: mine ? MainAxisAlignment.end : MainAxisAlignment.start,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: mine
          ? [time, const SizedBox(width: 6), Flexible(child: bubble)]
          : [Flexible(child: bubble), const SizedBox(width: 6), time],
    );
    final canDelete = mine && !m.deleted;
    final content = Column(crossAxisAlignment: mine ? CrossAxisAlignment.end : CrossAxisAlignment.start, children: [
      if (name != null)
        Padding(
          padding: const EdgeInsets.only(left: 2, bottom: 3),
          child: Text(m.sender.active ? name : '$name $inactiveMark', style: Typo.caption600.copyWith(color: Ms.gray700)),
        ),
      ConstrainedBox(constraints: const BoxConstraints(maxWidth: _bubbleMax + 50), child: row),
    ]);
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Builder(
        builder: (ctx) => GestureDetector(
          onLongPress: canDelete ? () => _deleteMenu(ctx, m) : null,
          child: content,
        ),
      ),
    );
  }

  Widget _textBubble(String text, bool mine) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          color: mine ? Ms.primary : Ms.white,
          border: mine ? null : Border.all(color: Ms.gray200),
          borderRadius: mine
              ? const BorderRadius.only(topLeft: Radius.circular(14), topRight: Radius.circular(14), bottomLeft: Radius.circular(14), bottomRight: Radius.circular(4))
              : const BorderRadius.only(topLeft: Radius.circular(14), topRight: Radius.circular(14), bottomLeft: Radius.circular(4), bottomRight: Radius.circular(14)),
        ),
        child: Text(text, style: Typo.body400.copyWith(color: mine ? Ms.white : Ms.gray800)),
      );

  Widget _deletedBubble(bool mine) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(border: Border.all(color: Ms.gray300), borderRadius: BorderRadius.circular(14)),
        child: Text('삭제된 메시지예요', style: Typo.body400.copyWith(color: Ms.gray600)),
      );

  Size _photoSize(int w, int h) {
    if (w <= 0 || h <= 0) return const Size(photoMaxWidth, 160);
    final width = w < photoMaxWidth ? w.toDouble() : photoMaxWidth;
    return Size(width, (width * h / w).clamp(60, 320));
  }

  Widget _photoBubble(ChatMessage m) {
    final ref = m.photo!;
    final size = _photoSize(ref.width, ref.height);
    return GestureDetector(
      onTap: () => openPhotoViewer(context, m),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: SizedBox.fromSize(size: size, child: ChatPhoto(photoId: ref.id, fit: BoxFit.cover)),
      ),
    );
  }

  // 보내는 중 · 실패(DS:S6 · S7b)
  Widget _pendingRow(PendingMessage p) {
    final failed = p.state == SendState.failed;
    final Widget bubble;
    if (p.isPhoto) {
      final size = _photoSize(p.width, p.height);
      final pct = ((p.progress ?? 0) * 100).round();
      bubble = ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: SizedBox.fromSize(
          size: size,
          child: Stack(fit: StackFit.expand, children: [
            Image.memory(p.photoBytes!, fit: BoxFit.cover, gaplessPlayback: true),
            if (!failed && p.photoId == null)
              Positioned(
                left: 0,
                right: 0,
                bottom: 0,
                child: Container(
                  color: const Color(0xCCFFFFFF),
                  padding: const EdgeInsets.fromLTRB(10, 6, 10, 8),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text('올리는 중 $pct%', style: Typo.caption600.copyWith(color: Ms.gray800)),
                    const SizedBox(height: 4),
                    MsProgress(p.progress ?? 0),
                  ]),
                ),
              ),
          ]),
        ),
      );
    } else {
      bubble = _textBubble(p.text ?? '', true);
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
      ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: _bubbleMax + 80),
        child: Row(mainAxisAlignment: MainAxisAlignment.end, crossAxisAlignment: CrossAxisAlignment.end, children: [
          if (failed)
            Semantics(label: '보내기 실패', child: const Icon(Icons.error_outline_rounded, size: 18, color: Ms.red))
          else if (!p.isPhoto || p.photoId != null)
            Text('보내는 중…', style: Typo.caption400.copyWith(color: Ms.gray600)),
          const SizedBox(width: 6),
          // 흐림 = 보내는 중(올리는 중인 사진은 진행률이 보이게 그대로)
          Flexible(child: Opacity(opacity: failed || (p.isPhoto && p.photoId == null) ? 1 : 0.55, child: bubble)),
        ]),
      ),
      if (failed)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Text('보내지 못했어요', style: Typo.caption600.copyWith(color: Ms.red)),
            const SizedBox(width: 8),
            MsButton('다시 보내기', variant: BtnVariant.outlined, color: BtnColor.gray, size: BtnSize.sm, onPressed: () => _chat.retry(p)),
          ]),
        ),
    ]);
  }

  // 내 메시지 길게 누름(DS:S9a) — 그 말풍선만 떠오르고(뒤 흐림) 아래 [삭제] 하나 → 확인(DS:S9b)
  Future<void> _deleteMenu(BuildContext bubbleContext, ChatMessage m) async {
    final box = bubbleContext.findRenderObject() as RenderBox?;
    if (box == null) return;
    final rect = box.localToGlobal(Offset.zero) & box.size;
    final del = await showGeneralDialog<bool>(
      context: context,
      barrierDismissible: true,
      barrierLabel: '닫기',
      barrierColor: Ms.dim,
      transitionDuration: const Duration(milliseconds: 120),
      pageBuilder: (ctx, _, _) => Material(type: MaterialType.transparency, child: Stack(children: [
        Positioned.fromRect(rect: rect, child: IgnorePointer(child: _bubbleCopy(m))),
        Positioned(
          top: rect.bottom + 8,
          right: MediaQuery.sizeOf(ctx).width - rect.right,
          child: SizedBox(
            width: 180,
            child: MsCard(
              padding: const EdgeInsets.symmetric(vertical: 4),
              shadow: true,
              child: InkWell(
                key: const Key('chat-delete-menu'),
                onTap: () => Navigator.of(ctx).pop(true),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  child: Text('삭제', style: Typo.body600.copyWith(color: Ms.red)),
                ),
              ),
            ),
          ),
        ),
      ])),
    );
    if (del != true || !mounted) return;
    final ok = await confirmChat(context, title: '메시지를 삭제할까요?', body: '대화방의 모두에게 「삭제된 메시지예요」로 보여요. 되돌릴 수 없어요.', ok: '삭제');
    if (ok) await _app.run(() => _chat.delete(m));
  }

  Widget _bubbleCopy(ChatMessage m) => Material(
        type: MaterialType.transparency,
        child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Row(mainAxisAlignment: MainAxisAlignment.end, crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(bubbleTime(m.createdAt), style: Typo.caption400.copyWith(color: Ms.white)),
            const SizedBox(width: 6),
            Flexible(child: m.photo != null ? _photoBubble(m) : _textBubble(m.text ?? '', true)),
          ]),
        ]),
      );

  // 입력줄(DS:S4) — [사진] · 입력(여러 줄 · 코드 포인트 2000) · [보내기](비면 꺼짐)
  Widget _inputBar() => Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
        decoration: const BoxDecoration(color: Ms.white, border: Border(top: BorderSide(color: Ms.gray200))),
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          MsButton('사진', key: const Key('chat-photo'), icon: Icons.photo_camera_outlined, variant: BtnVariant.outlined, color: BtnColor.gray, onPressed: _photo),
          const SizedBox(width: 8),
          Expanded(
            child: MsInput(
              fieldKey: const Key('chat-input'),
              controller: _text,
              hint: '메시지 입력',
              minLines: 1,
              maxLines: 5,
              formatters: const [RuneLimitFormatter()],
              onChanged: (_) => setState(() {}),
            ),
          ),
          const SizedBox(width: 8),
          MsButton('보내기', key: const Key('chat-send'), onPressed: _text.text.trim().isEmpty ? null : _send),
        ]),
      );

  // 비활성 상대 1:1(D9-42) — 입력줄 대신 안내 한 줄
  Widget _inactiveLine() => Container(
        key: const Key('chat-inactive'),
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: const BoxDecoration(color: Ms.gray200, border: Border(top: BorderSide(color: Ms.gray300))),
        child: Text('비활성 계정이에요', textAlign: TextAlign.center, style: Typo.body500.copyWith(color: Ms.gray600)),
      );
}

// 대화 목록 한 줄(날짜 구분선 · 메시지 · 보내는 중)
sealed class ChatItem {
  const ChatItem();
}

class DayItem extends ChatItem {
  final String label;
  const DayItem(this.label);
}

class MessageItem extends ChatItem {
  final ChatMessage m;
  final bool mine;
  final String? name; // 그룹 남의 말풍선 위 이름(연달아면 null)
  const MessageItem(this.m, this.mine, this.name);
}

class PendingItem extends ChatItem {
  final PendingMessage p;
  const PendingItem(this.p);
}

// 시간 순 메시지 → 날짜 구분선을 끼운 줄(보내는 중은 맨 아래 · 오늘)
List<ChatItem> buildChatItems(List<ChatMessage> messages, List<PendingMessage> pending,
    {required bool group, required bool Function(ChatMessage) mine}) {
  final out = <ChatItem>[];
  ChatMessage? prev;
  for (final m in messages) {
    if (prev == null || !sameDay(prev.createdAt, m.createdAt)) out.add(DayItem(dayLabel(m.createdAt)));
    final me = mine(m);
    out.add(MessageItem(m, me, showSenderName(group: group, cur: m, prev: prev, mine: me) ? m.sender.name : null));
    prev = m;
  }
  if (pending.isNotEmpty) {
    final today = DateTime.now().toIso8601String();
    if (prev == null || !sameDay(prev.createdAt, today)) out.add(DayItem(dayLabel(today)));
    out.addAll(pending.map(PendingItem.new));
  }
  return out;
}

// 채팅 사진 — Bearer 로 받아 메모리 캐시 · Image.memory(Image.network 안 씀 · D9-24). 받는 동안 회색 자리
class ChatPhoto extends StatefulWidget {
  final int photoId;
  final BoxFit fit;
  const ChatPhoto({super.key, required this.photoId, this.fit = BoxFit.cover});
  @override
  State<ChatPhoto> createState() => _ChatPhotoState();
}

class _ChatPhotoState extends State<ChatPhoto> {
  Uint8List? _bytes;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    final chat = AppScope.read(context).chat;
    _bytes = chat.photos.get(widget.photoId);
    if (_bytes == null) {
      chat.photo(widget.photoId).then((b) {
        if (mounted) setState(() => b == null ? _failed = true : _bytes = b);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final b = _bytes;
    if (b != null) return Image.memory(b, fit: widget.fit, gaplessPlayback: true);
    return Container(
      color: Ms.gray300,
      alignment: Alignment.center,
      child: Icon(_failed ? Icons.broken_image_outlined : Icons.image_outlined, size: 40, color: Ms.gray600),
    );
  }
}
