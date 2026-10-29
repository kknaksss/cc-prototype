// 사진 · 동영상 모아보기(SPEC-007 §10.16 · D9-67 · F11 · r5) — 방 정보 「사진 · 동영상」 줄에서 연다. 시안 없음 — 기존 위젯 · 토큰만.
//   폰 = 채팅 탭 스택(방 정보 위) · 아이패드 = 방 정보 오른쪽 시트 안 다음 화면(r5 처분 W-3 — [‹ 방 정보]로 돌아감)
//   격자 3열 · 칸 사이 2px · 최근 것 왼쪽 위(#20 차례) · 사진 칸 = 대화와 같은 메모리 캐시 · 동영상 칸 = 썸네일 + ▶ + 「m:ss」
//   60씩 · 끝에서 before 로 더 · 빈 상태 · 실패 + [다시 시도] · 누르면 크게 보기 · 재생(전체 화면) · 못 열면 토스트 + 칸 뺌 ·
//   길게 누르기 메뉴 없음 · 저장 · 공유 없음 · SSE 새 사진 = 맨 앞 · 지움 = 뺌 · 다시 연결 · 앞으로 옴 = 처음 60 다시 · 로그아웃 = 비움
import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api.dart' show ApiError;
import '../app_state.dart';
import '../chat/chat_model.dart';
import '../chat/chat_state.dart';
import '../theme/tokens.dart';
import '../widgets/header.dart';
import '../widgets/ui.dart';
import 'chat_photo_screen.dart' show openPhotoViewer;
import 'chat_room_screen.dart' show ChatPhoto, VideoMarks;
import 'chat_video_screen.dart' show openVideoPlayer;

const mediaPage = 60;

class ChatMediaScreen extends StatefulWidget {
  final int roomId;
  final bool sheet; // 아이패드 방 정보 시트 안
  const ChatMediaScreen({super.key, required this.roomId, this.sheet = false});
  @override
  State<ChatMediaScreen> createState() => _ChatMediaScreenState();
}

class _ChatMediaScreenState extends State<ChatMediaScreen> {
  late final AppState _app = AppScope.read(context);
  ChatState get _chat => _app.chat;
  final List<ChatMessage> _items = [];
  bool _hasMore = false;
  bool _loading = false;
  bool _loaded = false;
  bool _failed = false;
  StreamSubscription<ChatChange>? _sub;
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _sub = _chat.changes.stream.listen(_onChange);
    _scroll.addListener(() {
      final p = _scroll.position;
      if (p.pixels >= p.maxScrollExtent - 200) _more();
    });
    _first();
  }

  @override
  void dispose() {
    _sub?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _first() => _load(reset: true);
  Future<void> _more() async {
    if (!_hasMore || _loading || _items.isEmpty) return;
    await _load(before: _items.last.id);
  }

  Future<void> _load({bool reset = false, int? before}) async {
    if (_loading) return;
    _loading = true;
    if (reset) setState(() => _failed = false);
    try {
      final r = await _app.api.chatAttachments(widget.roomId, before: before, limit: mediaPage);
      if (!mounted) return;
      setState(() {
        if (reset) _items.clear();
        _merge(r.items);
        _hasMore = r.hasMore;
        _loaded = true;
        _failed = false;
      });
    } on ApiError catch (e) {
      if (e.status == 401) return unawaited(_chat.onUnauthorized());
      if (mounted && (reset || !_loaded)) setState(() => _failed = true);
    } finally {
      _loading = false;
    }
  }

  // id 로 겹침 지움 · 최근 것 위(id 내림차순)
  void _merge(Iterable<ChatMessage> l) {
    final byId = {for (final m in _items) m.id: m};
    for (final m in l) {
      if (!m.deleted && (m.photo != null || m.video != null)) byId[m.id] = m;
    }
    _items
      ..clear()
      ..addAll(byId.values.toList()..sort((a, b) => b.id.compareTo(a.id)));
  }

  void _onChange(ChatChange c) {
    if (!mounted) return;
    switch (c.kind) {
      case 'message':
        final m = c.message!;
        if (m.roomId == widget.roomId && _loaded) setState(() => _merge([m]));
      case 'deleted':
        if (c.roomId == widget.roomId) setState(() => _items.removeWhere((m) => m.id == c.messageId));
      case 'resync':
        _first();
      case 'clear':
        setState(() {
          _items.clear();
          _loaded = false;
        });
    }
  }

  // 누르면 크게 보기 · 재생 — 그새 지워짐(404) = 토스트 + 칸 뺌
  Future<void> _open(ChatMessage m) async {
    final video = m.video != null;
    final ok = video ? await _chat.thumb(m.video!.id) != null : await _chat.photo(m.photo!.id) != null;
    if (!mounted) return;
    if (!ok) {
      _app.toaster.show(video ? '동영상을 찾을 수 없어요' : '사진을 찾을 수 없어요');
      setState(() => _items.removeWhere((x) => x.id == m.id));
      return;
    }
    video ? await openVideoPlayer(context, m) : await openPhotoViewer(context, m);
  }

  @override
  Widget build(BuildContext context) {
    final body = Column(children: [
      DetailHeader(back: '방 정보', title: '사진 · 동영상'),
      Expanded(child: _grid()),
    ]);
    if (widget.sheet) return Material(color: Ms.gray100, child: SafeArea(left: false, child: body));
    return Scaffold(backgroundColor: Ms.gray100, body: SafeArea(bottom: false, child: body));
  }

  Widget _grid() {
    if (_failed) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text('사진 · 동영상을 불러오지 못했어요', style: Typo.body400.copyWith(color: Ms.gray600)),
          const SizedBox(height: 10),
          MsButton('다시 시도', key: const Key('chat-media-retry'), variant: BtnVariant.outlined, color: BtnColor.gray, size: BtnSize.sm, onPressed: _first),
        ]),
      );
    }
    if (!_loaded) return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    if (_items.isEmpty) {
      return Center(child: Text('아직 주고받은 사진 · 동영상이 없어요', key: const Key('chat-media-empty'), style: Typo.body400.copyWith(color: Ms.gray600)));
    }
    return GridView.builder(
      key: const Key('chat-media-grid'),
      controller: _scroll,
      padding: const EdgeInsets.all(2),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 3, mainAxisSpacing: 2, crossAxisSpacing: 2),
      itemCount: _items.length + (_hasMore ? 1 : 0),
      itemBuilder: (context, i) {
        if (i == _items.length) {
          _more();
          return const Center(child: SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2)));
        }
        final m = _items[i];
        final v = m.video;
        return GestureDetector(
          key: Key('chat-media-${m.id}'),
          onTap: () => _open(m),
          child: Stack(fit: StackFit.expand, children: [
            ChatPhoto(key: ValueKey('cell-${m.id}'), photoId: v?.id ?? m.photo!.id, video: v != null, fit: BoxFit.cover),
            if (v != null) VideoMarks(durationMs: v.durationMs, compact: true),
          ]),
        );
      },
    );
  }
}
