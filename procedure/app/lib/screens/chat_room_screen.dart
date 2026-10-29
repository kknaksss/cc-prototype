// 대화(SPEC-007 §10.4 ~ §10.7 · DS:S4 ~ S9b) — 폰 = 채팅 탭 스택의 상세 화면(DetailHeader 「‹ 채팅」 · 탭바 유지) ·
// 아이패드 = 오른쪽 칸(뒤로 없음 · D9-38). 말풍선 · 날짜 구분선 · 시스템 줄 · 그룹 보낸 사람 이름 · 보내는 중 · 실패 · 사진 · 길게 눌러 삭제.
// r3: 넓은 입력창(D9-47) · [+] 시트(D9-48) · 여러 개(D9-50) · 동영상 말풍선 · 재생(D9-53) · 링크(D9-46) · 5메뉴 · 수정(D9-54 · D9-55) · [공유] = 앱 안 전달(r4 D9-62)
import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/gestures.dart' show TapGestureRecognizer;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;

import '../api/api.dart' show ApiError;

import '../app_state.dart';
import '../chat/chat_model.dart';
import '../chat/chat_link.dart';
import '../chat/chat_state.dart';
import '../chat/chat_ui.dart';
import '../chat/chat_view.dart';
import '../chat/photo_pick.dart';
import '../theme/tokens.dart';
import '../view/view.dart' show BadgeVariant;
import '../widgets/header.dart';
import '../widgets/ui.dart';
import 'chat_attach_sheet.dart';
import 'chat_forward_sheet.dart';
import 'chat_info_screen.dart';
import 'chat_photo_screen.dart';
import 'chat_video_screen.dart';
import '../widgets/sheet.dart';

const chatRoomRouteName = 'chat-room';

// 폰 — 채팅 탭 스택에 쌓는 대화(이름 = 초대 뒤 돌아올 자리)
Route<void> chatRoomRoute(int roomId) =>
    MaterialPageRoute(settings: RouteSettings(name: chatRoomRouteName, arguments: roomId), builder: (_) => ChatRoomView(roomId: roomId));

const _bubbleMax = 300.0;
const maxInputLines = 5; // 알약 입력 상한(D9-60) — 넘으면 칸 안 스크롤
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
    _focus.dispose();
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
    final e = _editing;
    if (e != null && (_chat.thread(_id).byId[e.id]?.deleted ?? false)) _cancelEdit(); // 고치던 글이 지워짐(다른 기기)
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

  // [+] → 시트(최근 줄 · 카메라 칸 · 「사진」 메뉴 — §10.6)
  Future<void> _plus() async {
    final r = await openAttachSheet(context, media: recentMedia, onCamera: _camera);
    if (!mounted) return;
    switch (r) {
      case AttachSend(:final items, :final thumbs):
        await _sendMany([for (final it in items) recentMedia.item(it, preview: thumbs[it.id])]); // 사본은 항목마다 지움(W-3)
      case AttachGallery():
        try {
          await _sendMany(await pickChatGallery());
        } on PhotoDenied {
          _app.toaster.show('설정에서 카메라(사진) 권한을 켜 주세요');
        } catch (_) {
          _app.toaster.show(photoFailed);
        }
      case null:
    }
  }

  // 카메라 칸 — 사진만 · 찍은 한 장을 바로 보냄(시트는 그대로 · 고른 것은 고른 채 — r3 W-8)
  Future<void> _camera() async {
    try {
      final p = await pickChatPhoto(PhotoSource.camera);
      if (p == null) return;
      _chat.sendPhoto(_id, p.jpeg, p.width, p.height);
      if (_scroll.hasClients) _scroll.jumpTo(0);
    } on PhotoDenied {
      _app.toaster.show('설정에서 카메라(사진) 권한을 켜 주세요');
    } catch (_) {
      _app.toaster.show(photoFailed);
    }
  }

  Future<void> _sendMany(List<MediaItem> items) async {
    if (items.isEmpty) return;
    if (_scroll.hasClients) _scroll.jumpTo(0);
    await _chat.sendMany(_id, items);
  }

  Future<void> _info(Room r) async {
    // 아이패드 = 오른쪽 시트 안 작은 Navigator — 방 정보 → 사진 · 동영상이 같은 시트 안에서 넘어감(r5 처분 W-3)
    if (widget.pane) return showRightSheet(context, ChatInfoSheet(roomId: r.id));
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
          // 바깥(대화 목록)을 누르면 키보드 닫힘(D9-61) — 말풍선 누름 · 길게 누르기는 안쪽이 먼저 받는다
          Expanded(
            child: GestureDetector(
              key: const Key('chat-list-area'),
              behavior: HitTestBehavior.translucent,
              onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
              child: _messages(r, t),
            ),
          ),
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
    // reverse 목록 = 0 이 맨 아래 — 키보드가 열려 칸이 줄어도 맨 아래를 보고 있었으면 마지막 메시지가 그대로 보인다(D9-61) ·
    // 끌면 키보드 닫힘
    return ListView.builder(
      controller: _scroll,
      reverse: true,
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
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

  // 말풍선 줄(시각 · 「수정됨」 · 그룹 이름) — onDim = 길게 누르기 막 위 복사본(글자 흰색)
  Widget _content(ChatMessage m, bool mine, String? name, {bool onDim = false}) {
    final grey = Typo.caption400.copyWith(color: onDim ? Ms.white : Ms.gray600);
    final time = Row(mainAxisSize: MainAxisSize.min, children: [
      if (m.edited && !m.deleted) ...[Text('수정됨', key: const Key('chat-edited'), style: grey), const SizedBox(width: 3)],
      Text(bubbleTime(m.createdAt), style: grey),
    ]);
    final bubble = _bubbleOf(m, mine);
    final row = Row(
      mainAxisAlignment: mine ? MainAxisAlignment.end : MainAxisAlignment.start,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: mine
          ? [time, const SizedBox(width: 6), Flexible(child: bubble)]
          : [Flexible(child: bubble), const SizedBox(width: 6), time],
    );
    return Column(crossAxisAlignment: mine ? CrossAxisAlignment.end : CrossAxisAlignment.start, children: [
      if (name != null)
        Padding(
          padding: const EdgeInsets.only(left: 2, bottom: 3),
          child: Text(m.sender.active ? name : '$name $inactiveMark', style: Typo.caption600.copyWith(color: onDim ? Ms.white : Ms.gray700)),
        ),
      ConstrainedBox(constraints: const BoxConstraints(maxWidth: _bubbleMax + 50), child: row),
    ]);
  }

  Widget _messageRow(ChatMessage m, bool mine, String? name) {
    final r = _chat.room(_id);
    final menu = chatMenuOf(m, mine: mine, peerInactive: r != null && peerInactive(r));
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Builder(
        builder: (ctx) => GestureDetector(
          key: Key('chat-msg-${m.id}'),
          onLongPress: menu.isEmpty ? null : () => _menu(ctx, m, mine, name, menu),
          child: _content(m, mine, name),
        ),
      ),
    );
  }

  Widget _bubbleOf(ChatMessage m, bool mine) {
    if (m.deleted) return _deletedBubble(mine);
    if (m.video != null) return _videoBubble(m);
    if (m.photo != null) return _photoBubble(m);
    return _textBubble(m.text ?? '', mine);
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
        child: ChatLinkText(text, mine: mine),
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

  // 동영상 말풍선(r3 · D9-53) — 사진과 같은 자리 · 크기 규칙 · 썸네일 + 가운데 ▶ + 오른쪽 아래 「m:ss」 · 누르면 재생 화면
  Widget _videoBubble(ChatMessage m) {
    final v = m.video!;
    return GestureDetector(
      key: Key('chat-video-${v.id}'),
      onTap: () => openVideoPlayer(context, m),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: SizedBox.fromSize(
          size: _photoSize(v.width, v.height),
          child: Stack(fit: StackFit.expand, children: [
            ChatPhoto(photoId: v.id, video: true, fit: BoxFit.cover),
            VideoMarks(durationMs: v.durationMs),
          ]),
        ),
      ),
    );
  }

  // 보내는 중 · 실패(DS:S6 · S7b) — 동영상 = 썸네일 + 「바꾸는 중…」 → 「올리는 중 N%」(r3)
  Widget _pendingRow(PendingMessage p) {
    final failed = p.state == SendState.failed;
    final Widget bubble;
    if (p.isMedia) {
      final size = _photoSize(p.width, p.height);
      final pct = ((p.progress ?? 0) * 100).round();
      final bytes = p.photoBytes;
      bubble = ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: SizedBox.fromSize(
          size: size,
          child: Stack(fit: StackFit.expand, children: [
            if (bytes != null)
              Image.memory(bytes, fit: BoxFit.cover, gaplessPlayback: true)
            else
              Container(color: Ms.gray300, child: Icon(p.isVideo ? Icons.videocam_outlined : Icons.image_outlined, size: 36, color: Ms.gray600)),
            if (p.isVideo && !p.preparing) VideoMarks(durationMs: p.durationMs),
            if (!failed && !p.uploaded)
              Positioned(
                left: 0,
                right: 0,
                bottom: 0,
                child: Container(
                  color: const Color(0xCCFFFFFF),
                  padding: const EdgeInsets.fromLTRB(10, 6, 10, 8),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text(p.isVideo && p.preparing ? '바꾸는 중…' : '올리는 중 $pct%', style: Typo.caption600.copyWith(color: Ms.gray800)),
                    const SizedBox(height: 4),
                    MsProgress(p.preparing ? 0 : p.progress ?? 0),
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
          else if (p.uploaded)
            Text('보내는 중…', style: Typo.caption400.copyWith(color: Ms.gray600)),
          const SizedBox(width: 6),
          // 흐림 = 보내는 중(올리는 중인 사진 · 동영상은 진행률이 보이게 그대로)
          Flexible(child: Opacity(opacity: failed || !p.uploaded ? 1 : 0.55, child: bubble)),
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

  // 길게 누르기(DS:S9a · r3 D9-54) — 그 말풍선만 떠오르고(뒤 흐림 · 1판 막) 아래 메뉴 카드(내 것 = 오른쪽 · 상대 = 왼쪽 맞춤 ·
  // 아래 자리가 모자라면 말풍선 위). 줄 = chatMenuOf(§10.7 표)
  Future<void> _menu(BuildContext bubbleContext, ChatMessage m, bool mine, String? name, List<ChatMenu> items) async {
    final box = bubbleContext.findRenderObject() as RenderBox?;
    if (box == null) return;
    final rect = box.localToGlobal(Offset.zero) & box.size;
    final pick = await showGeneralDialog<ChatMenu>(
      context: context,
      barrierDismissible: true,
      barrierLabel: '닫기',
      barrierColor: Ms.dim,
      transitionDuration: const Duration(milliseconds: 120),
      pageBuilder: (ctx, _, _) {
        final screen = MediaQuery.sizeOf(ctx);
        final h = items.length * 44.0 + 8;
        final below = rect.bottom + 8 + h <= screen.height - MediaQuery.paddingOf(ctx).bottom - 8;
        return Material(
          type: MaterialType.transparency,
          child: Stack(children: [
            Positioned.fromRect(rect: rect, child: IgnorePointer(child: _content(m, mine, name, onDim: true))),
            Positioned(
              top: below ? rect.bottom + 8 : null,
              bottom: below ? null : screen.height - rect.top + 8,
              left: mine ? null : rect.left,
              right: mine ? screen.width - rect.right : null,
              child: SizedBox(
                width: 180,
                child: MsCard(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  shadow: true,
                  child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    for (final it in items)
                      InkWell(
                        key: Key(it == ChatMenu.delete ? 'chat-delete-menu' : 'chat-menu-${it.name}'),
                        onTap: () => Navigator.of(ctx).pop(it),
                        child: SizedBox(
                          height: 44,
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 16),
                            child: Row(children: [
                              Icon(it.icon, size: 18, color: it == ChatMenu.delete ? Ms.red : Ms.gray700),
                              const SizedBox(width: 10),
                              Text(it.label, style: Typo.body600.copyWith(color: it == ChatMenu.delete ? Ms.red : Ms.gray800)),
                            ]),
                          ),
                        ),
                      ),
                  ]),
                ),
              ),
            ),
          ]),
        );
      },
    );
    if (pick == null || !mounted) return;
    switch (pick) {
      case ChatMenu.copy:
        await Clipboard.setData(ClipboardData(text: m.text ?? ''));
        _app.toaster.show('복사했어요');
      case ChatMenu.select:
        await showSelectCopy(context, m.text ?? '');
      case ChatMenu.share:
        await openForwardSheet(context, m); // r4 D9-62 — 앱 안 전달(시스템 공유 시트 없음)
      case ChatMenu.edit:
        _startEdit(m);
      case ChatMenu.delete:
        final ok = await confirmChat(context, title: '메시지를 삭제할까요?', body: '대화방의 모두에게 「삭제된 메시지예요」로 보여요. 되돌릴 수 없어요.', ok: '삭제');
        if (ok) await _app.run(() => _chat.delete(m));
    }
  }

  // ─── 수정 모드(r3 · D9-55 · §10.4) — 입력창 위 「메시지 수정」 줄 + [✕] · 입력칸 = 원문 · [+] 꺼짐 · [전송] 자리 = [저장]
  ChatMessage? _editing;
  final _focus = FocusNode();

  void _startEdit(ChatMessage m) {
    setState(() {
      _editing = m;
      _text.text = m.text ?? '';
      _text.selection = TextSelection.collapsed(offset: _text.text.length);
    });
    _focus.requestFocus();
  }

  void _cancelEdit() {
    setState(() {
      _editing = null;
      _text.clear();
    });
  }

  bool get _canSave {
    final t = _text.text.trim();
    return t.isNotEmpty && t != (_editing?.text ?? '').trim();
  }

  Future<void> _saveEdit() async {
    final m = _editing;
    if (m == null || !_canSave) return;
    try {
      await _chat.edit(m, _text.text.trim());
      if (mounted && _editing?.id == m.id) _cancelEdit();
    } on ApiError catch (e) {
      if (e.status == 401) return unawaited(_chat.onUnauthorized());
      _app.toaster.show(e.status >= 400 && e.status < 500 ? e.message : '고치지 못했어요'); // 원문이 남아 있다 — 실패 말풍선 없음
    }
  }

  // 여러 개 보내는 중(r3 · §10.5) — 입력창 위 얇은 줄 「N개 보내는 중 · k/N」(2개 이상 · 다 끝나면 없음)
  Widget _batchLine() {
    final b = _chat.batches[_id];
    if (b == null || b.total < 2) return const SizedBox.shrink();
    final k = (b.done + 1).clamp(1, b.total);
    return Container(
      key: const Key('chat-batch'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 5),
      color: Ms.primary100,
      child: Text('${b.total}개 보내는 중 · $k/${b.total}', style: Typo.caption600.copyWith(color: Ms.primary)),
    );
  }

  // 입력줄(D9-60 — D9-47 고침 · 카톡 모바일 꼴 알약 한 줄) — 코드 포인트 2000 · 줄바꿈 키 = 줄바꿈(보내기는 [↑]만) · 수정 모드 줄은 알약 위
  Widget _inputBar() => Column(mainAxisSize: MainAxisSize.min, children: [
        _batchLine(),
        Container(
          padding: const EdgeInsets.fromLTRB(10, 6, 10, 6),
          decoration: const BoxDecoration(color: Ms.white, border: Border(top: BorderSide(color: Ms.gray200))),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (_editing != null)
              Padding(
                key: const Key('chat-edit-bar'),
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(children: [
                  const Icon(Icons.edit_outlined, size: 16, color: Ms.primary),
                  const SizedBox(width: 6),
                  Expanded(child: Text('메시지 수정', style: Typo.caption600.copyWith(color: Ms.primary))),
                  IconButton(
                    key: const Key('chat-edit-cancel'),
                    tooltip: '수정 취소',
                    visualDensity: VisualDensity.compact,
                    onPressed: _cancelEdit,
                    icon: const Icon(Icons.close_rounded, size: 20, color: Ms.gray700),
                  ),
                ]),
              ),
            // 알약 한 줄(D9-60 · 카톡 모바일 꼴) — 둥근 [+] · 입력(테두리 없음 · 1줄 → 5줄까지 늘고 그 뒤 칸 안 스크롤) · 둥근 [↑] 보내기
            // (수정 모드 = 같은 자리 [✓] 저장). 이모지 버튼 없음 · 색 = 기존 토큰
            Container(
              key: const Key('chat-pill'),
              padding: const EdgeInsets.all(4),
              decoration: BoxDecoration(color: Ms.gray100, borderRadius: BorderRadius.circular(22), border: Border.all(color: Ms.gray200)),
              child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                _round(
                  key: const Key('chat-plus'),
                  tooltip: '첨부',
                  icon: Icons.add_rounded,
                  bg: Ms.white,
                  fg: Ms.gray700,
                  onPressed: _editing != null ? null : _plus,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: TextField(
                    key: const Key('chat-input'),
                    controller: _text,
                    focusNode: _focus,
                    minLines: 1,
                    maxLines: maxInputLines,
                    inputFormatters: const [RuneLimitFormatter()],
                    keyboardType: TextInputType.multiline,
                    textInputAction: TextInputAction.newline,
                    style: Typo.body400,
                    onChanged: (_) => setState(() {}),
                    decoration: InputDecoration(
                      hintText: '메시지 입력',
                      hintStyle: Typo.body400.copyWith(color: Ms.gray500),
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      disabledBorder: InputBorder.none,
                      filled: false,
                      isDense: true,
                      contentPadding: const EdgeInsets.symmetric(vertical: 8),
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                if (_editing != null)
                  _round(key: const Key('chat-save'), tooltip: '저장', icon: Icons.check_rounded, bg: Ms.primary, fg: Ms.white, onPressed: _canSave ? _saveEdit : null)
                else
                  _round(
                    key: const Key('chat-send'),
                    tooltip: '보내기',
                    icon: Icons.arrow_upward_rounded,
                    bg: Ms.primary,
                    fg: Ms.white,
                    onPressed: _text.text.trim().isEmpty ? null : _send,
                  ),
              ]),
            ),
          ]),
        ),
      ]);

  // 둥근 버튼(36) — 꺼지면 같은 색 그대로 흐림
  Widget _round({required Key key, required String tooltip, required IconData icon, required Color bg, required Color fg, VoidCallback? onPressed}) =>
      Opacity(
        opacity: onPressed == null ? 0.4 : 1,
        child: SizedBox.square(
          dimension: 36,
          child: IconButton(
            key: key,
            tooltip: tooltip,
            onPressed: onPressed,
            padding: EdgeInsets.zero,
            style: IconButton.styleFrom(
              backgroundColor: bg,
              disabledBackgroundColor: bg,
              foregroundColor: fg,
              disabledForegroundColor: fg,
              shape: const CircleBorder(),
            ),
            icon: Icon(icon, size: 22),
          ),
        ),
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
// 동영상 썸네일도 같은 꼴(video: true · #18 · 같은 캐시 · 키는 따로)
class ChatPhoto extends StatefulWidget {
  final int photoId;
  final bool video;
  final BoxFit fit;
  const ChatPhoto({super.key, required this.photoId, this.video = false, this.fit = BoxFit.cover});
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
    _bytes = chat.photos.get(widget.video ? thumbKey(widget.photoId) : widget.photoId);
    if (_bytes == null) {
      (widget.video ? chat.thumb(widget.photoId) : chat.photo(widget.photoId)).then((b) {
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

// 동영상 표시(D9-53 · OQ-953) — 가운데 ▶(흰 원 · 반투명 검정 바탕) + 오른쪽 아래 길이 「m:ss」(검정 알약 · 흰 글자)
class VideoMarks extends StatelessWidget {
  final int durationMs;
  final bool compact; // 모아보기 칸(작은 ▶ — §10.16)
  const VideoMarks({super.key, required this.durationMs, this.compact = false});
  @override
  Widget build(BuildContext context) => Stack(fit: StackFit.expand, children: [
        Center(
          child: Container(
            width: compact ? 28 : 44,
            height: compact ? 28 : 44,
            decoration: BoxDecoration(shape: BoxShape.circle, color: const Color(0x66000000), border: Border.all(color: Ms.white, width: 2)),
            child: Icon(Icons.play_arrow_rounded, color: Ms.white, size: compact ? 18 : 28),
          ),
        ),
        Positioned(
          right: compact ? 4 : 8,
          bottom: compact ? 4 : 8,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
            decoration: BoxDecoration(color: const Color(0xB3000000), borderRadius: BorderRadius.circular(10)),
            child: Text(durationText(durationMs), key: const Key('chat-video-duration'), style: Typo.caption600.copyWith(color: Ms.white)),
          ),
        ),
      ]);
}

// 길게 누르기 메뉴 줄(§10.7 표 · D9-54 · r3 처분 FAIL-2) — 차례 = 복사 · 선택 복사 · 공유 · 수정 · 삭제 중 맞는 것만.
// 시스템 줄 · 지운 메시지 = 없음(보내는 중 · 실패 말풍선은 길게 누르기 자체가 없다 — OQ-955) · 비활성 1:1(입력줄 없음) = [수정] 숨김
enum ChatMenu {
  copy('복사', Icons.content_copy_rounded),
  select('선택 복사', Icons.text_fields_rounded),
  share('공유', Icons.ios_share_rounded),
  edit('수정', Icons.edit_outlined),
  delete('삭제', Icons.delete_outline_rounded);

  final String label;
  final IconData icon;
  const ChatMenu(this.label, this.icon);
}

List<ChatMenu> chatMenuOf(ChatMessage m, {required bool mine, bool peerInactive = false}) {
  if (m.kind == MsgKind.system || m.deleted) return const [];
  if (m.photo != null || m.video != null) return [ChatMenu.share, if (mine) ChatMenu.delete];
  return [ChatMenu.copy, ChatMenu.select, ChatMenu.share, if (mine && !peerInactive) ChatMenu.edit, if (mine) ChatMenu.delete];
}

// 선택 복사(D9-54 · OQ-955) — 그 본문만 담은 시트(폰 = 아래 · 아이패드 = 가운데) · 처음부터 전부 골라 둔 상태 ·
// iOS 기본 선택 메뉴의 [복사]로 · [닫기]. 처음 골라 두기를 하려고 SelectableText 대신 읽기 전용 TextField(같은 EditableText)
Future<void> showSelectCopy(BuildContext context, String text) {
  if (isTabletWidth(context)) {
    return showDialog<void>(
      context: context,
      barrierColor: Ms.dim,
      builder: (ctx) => Dialog(
        backgroundColor: Ms.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 480), child: Padding(padding: const EdgeInsets.only(top: 12), child: _SelectCopy(text))),
      ),
    );
  }
  return showAppSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Ms.white,
    barrierColor: Ms.dim,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (ctx) => SafeArea(top: false, child: Column(mainAxisSize: MainAxisSize.min, children: [const SheetHandle(), _SelectCopy(text)])),
  );
}

// 시트 본문 — 컨트롤러는 이 화면이 갖는다(닫히는 애니메이션이 끝난 뒤 버림)
class _SelectCopy extends StatefulWidget {
  final String text;
  const _SelectCopy(this.text);
  @override
  State<_SelectCopy> createState() => _SelectCopyState();
}

class _SelectCopyState extends State<_SelectCopy> {
  late final _c = TextEditingController(text: widget.text)..selection = TextSelection(baseOffset: 0, extentOffset: widget.text.length);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Expanded(child: Text('선택 복사', style: Typo.titleSm600)),
            MsButton('닫기', key: const Key('chat-select-close'), variant: BtnVariant.outlined, color: BtnColor.gray, size: BtnSize.sm, onPressed: () => Navigator.of(context).pop()),
          ]),
          const SizedBox(height: 12),
          ConstrainedBox(
            constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.5),
            child: TextField(
              key: const Key('chat-select-text'),
              controller: _c,
              readOnly: true,
              autofocus: true,
              showCursor: false,
              maxLines: null,
              style: Typo.body400,
              decoration: const InputDecoration(border: InputBorder.none, enabledBorder: InputBorder.none, focusedBorder: InputBorder.none, isDense: true),
            ),
          ),
        ]),
      );
}

// 본문 + 밑줄 링크(D9-46 · §10.4) — 내 말풍선 = 흰 밑줄 · 상대 = Ms.primary 밑줄 · 누르면 기기 브라우저 ·
// 길게 누르면 링크 메뉴가 아니라 말풍선 메뉴(누름 인식기만 달아 길게 누르기는 바깥 GestureDetector 로 감)
class ChatLinkText extends StatefulWidget {
  final String text;
  final bool mine;
  const ChatLinkText(this.text, {super.key, required this.mine});
  @override
  State<ChatLinkText> createState() => _ChatLinkTextState();
}

class _ChatLinkTextState extends State<ChatLinkText> {
  final List<TapGestureRecognizer> _taps = [];

  void _drop() {
    for (final r in _taps) {
      r.dispose();
    }
    _taps.clear();
  }

  @override
  void dispose() {
    _drop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final base = Typo.body400.copyWith(color: widget.mine ? Ms.white : Ms.gray800);
    final links = findLinks(widget.text);
    if (links.isEmpty) return Text(widget.text, style: base);
    _drop();
    final linkStyle = base.copyWith(
      color: widget.mine ? Ms.white : Ms.primary,
      decoration: TextDecoration.underline,
      decorationColor: widget.mine ? Ms.white : Ms.primary,
    );
    final spans = <InlineSpan>[];
    var at = 0;
    for (final l in links) {
      if (l.start > at) spans.add(TextSpan(text: widget.text.substring(at, l.start)));
      final url = widget.text.substring(l.start, l.end);
      final tap = TapGestureRecognizer()..onTap = () => openChatLink(Uri.parse(url));
      _taps.add(tap);
      spans.add(TextSpan(text: url, style: linkStyle, recognizer: tap));
      at = l.end;
    }
    if (at < widget.text.length) spans.add(TextSpan(text: widget.text.substring(at)));
    return Text.rich(TextSpan(style: base, children: spans), key: const Key('chat-link-text'));
  }
}
