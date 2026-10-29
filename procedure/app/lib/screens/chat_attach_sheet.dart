// [+] 첨부 시트(SPEC-007 §10.6 · D9-48 ~ D9-52 · r3 · 사용자 스샷 = 카톡 [+] 시트) — 1판 시트 꼴(chat_photo_screen pickPhotoSource)로:
//   위 = 「최근 사진」 가로 줄 — 맨 앞 카메라 칸(사진만 · 찍으면 그 한 장을 바로 보냄 · 고른 것은 고른 채로 남음 — r3 W-8) +
//        사진 보관함 최근 항목(새것 왼쪽 · 60개씩) · 동영상 칸 = 오른쪽 아래 「m:ss」 · 오른쪽 위 동그라미 = 고른 차례 1 ~ 10 ·
//        10개가 차면 남은 칸 흐림 · 3분 넘는 동영상 칸 흐림 · limited = 끝에 [더 고르기] · 거부 = 안내 + [설정 열기]
//   머리 오른쪽 위 = [전송 N](고른 게 있을 때) · 아래 메뉴 = 「사진」 하나(기기 갤러리 — 통화 · 선물 · 송금 · 지도 없음)
// 폰 = 아래 시트 · 아이패드 = 가운데(§10.11). 시안에 없는 화면 — 기존 MsButton · MsCard · Ms.* 색만(§10.13 #12)
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../app_state.dart';
import '../chat/chat_view.dart' show durationText;
import '../chat/photo_pick.dart';
import '../chat/video_pick.dart' show videoTooLong;
import '../theme/tokens.dart';
import '../widgets/header.dart' show isTabletWidth;
import '../widgets/ui.dart';
import '../widgets/sheet.dart';

sealed class AttachResult {
  const AttachResult();
}

// [전송] — 고른 차례 · 줄에 그린 썸네일(보내는 중 말풍선 자리)
class AttachSend extends AttachResult {
  final List<RecentItem> items;
  final Map<String, Uint8List> thumbs;
  const AttachSend(this.items, this.thumbs);
}

// 「사진」 메뉴 — 기기 갤러리
class AttachGallery extends AttachResult {
  const AttachGallery();
}

const _cell = 96.0;

Future<AttachResult?> openAttachSheet(BuildContext context, {required RecentMedia media, required Future<void> Function() onCamera}) {
  Widget body(BuildContext ctx) => ChatAttachSheet(media: media, onCamera: onCamera);
  if (isTabletWidth(context)) {
    return showDialog<AttachResult>(
      context: context,
      barrierColor: Ms.dim,
      builder: (ctx) => Dialog(
        backgroundColor: Ms.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 560), child: Padding(padding: const EdgeInsets.only(top: 12), child: body(ctx))),
      ),
    );
  }
  return showAppSheet<AttachResult>(
    context: context,
    backgroundColor: Ms.white,
    barrierColor: Ms.dim,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (ctx) => SafeArea(top: false, child: Column(mainAxisSize: MainAxisSize.min, children: [const SheetHandle(), body(ctx)])),
  );
}

class ChatAttachSheet extends StatefulWidget {
  final RecentMedia media;
  final Future<void> Function() onCamera;
  const ChatAttachSheet({super.key, required this.media, required this.onCamera});
  @override
  State<ChatAttachSheet> createState() => _ChatAttachSheetState();
}

class _ChatAttachSheetState extends State<ChatAttachSheet> {
  MediaAccess? _access;
  final List<RecentItem> _items = [];
  final Map<String, Future<Uint8List?>> _thumbs = {};
  final Map<String, Uint8List> _thumbBytes = {};
  final List<String> _picked = []; // 고른 차례
  int _page = 0;
  bool _more = true;
  bool _loading = false;

  RecentMedia get _m => widget.media;
  void _toast(String s) => AppScope.read(context).toaster.show(s);

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    final a = await _m.access();
    if (!mounted) return;
    setState(() => _access = a);
    if (a != MediaAccess.denied) await _load();
  }

  Future<void> _load({bool restart = false}) async {
    if (_loading || (!_more && !restart)) return;
    _loading = true;
    if (restart) {
      _page = 0;
      _more = true;
    }
    try {
      final l = await _m.page(_page);
      if (!mounted) return;
      setState(() {
        if (restart) {
          _items.clear();
          _picked.removeWhere((id) => !l.any((x) => x.id == id));
        }
        _items.addAll(l);
        _page++;
        _more = l.length >= 60;
      });
    } catch (_) {
      _more = false;
    } finally {
      _loading = false;
    }
  }

  Future<Uint8List?> _thumb(RecentItem it) => _thumbs.putIfAbsent(it.id, () async {
        final b = await _m.thumb(it).catchError((Object _) => null);
        if (b != null) _thumbBytes[it.id] = b;
        return b;
      });

  void _toggle(RecentItem it) {
    if (it.tooLong) return _toast(videoTooLong);
    setState(() {
      if (_picked.remove(it.id)) return;
      if (_picked.length >= pickLimit) {
        _toast(pickLimitText);
        return;
      }
      _picked.add(it.id);
    });
  }

  void _send() {
    final byId = {for (final it in _items) it.id: it};
    final items = [for (final id in _picked) ?byId[id]];
    Navigator.of(context).pop(AttachSend(items, {for (final it in items) if (_thumbBytes[it.id] != null) it.id: _thumbBytes[it.id]!}));
  }

  Future<void> _moreLimited() async {
    await _m.pickMoreLimited();
    if (mounted) await _load(restart: true);
  }

  @override
  Widget build(BuildContext context) {
    final n = _picked.length;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(child: Text('최근 사진', style: Typo.titleSm600)),
          MsButton(n == 0 ? '전송' : '전송 $n', key: const Key('attach-send'), size: BtnSize.sm, onPressed: n == 0 ? null : _send),
        ]),
        const SizedBox(height: 10),
        SizedBox(height: _cell, child: _row()),
        const SizedBox(height: 12),
        const Divider(height: 1, color: Ms.gray200),
        InkWell(
          key: const Key('attach-gallery'),
          onTap: () => Navigator.of(context).pop(const AttachGallery()),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 4),
            child: Row(children: [
              const Icon(Icons.photo_library_outlined, size: 22, color: Ms.gray700),
              const SizedBox(width: 12),
              Text('사진', style: Typo.body600.copyWith(color: Ms.gray800)),
            ]),
          ),
        ),
      ]),
    );
  }

  Widget _row() {
    final a = _access;
    final camera = _square(
      key: const Key('attach-camera'),
      onTap: widget.onCamera,
      child: Container(
        color: Ms.gray100,
        alignment: Alignment.center,
        child: const Icon(Icons.photo_camera_outlined, size: 30, color: Ms.gray700),
      ),
    );
    if (a == MediaAccess.denied) {
      return Row(children: [
        camera,
        const SizedBox(width: 12),
        Expanded(
          child: Column(key: const Key('attach-denied'), mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('사진 접근을 허용하면 최근 사진이 여기에 보여요', style: Typo.body400.copyWith(color: Ms.gray700)),
            const SizedBox(height: 8),
            MsButton('설정 열기', key: const Key('attach-settings'), variant: BtnVariant.outlined, color: BtnColor.gray, size: BtnSize.sm, onPressed: _m.openSettings),
          ]),
        ),
      ]);
    }
    final limited = a == MediaAccess.limited;
    final count = 1 + _items.length + (limited ? 1 : 0);
    return ListView.separated(
      scrollDirection: Axis.horizontal,
      itemCount: count,
      separatorBuilder: (_, _) => const SizedBox(width: 6),
      itemBuilder: (context, i) {
        if (i == 0) return camera;
        if (limited && i == count - 1) {
          return _square(
            key: const Key('attach-more'),
            onTap: _moreLimited,
            child: Container(
              color: Ms.gray100,
              alignment: Alignment.center,
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.add_photo_alternate_outlined, size: 24, color: Ms.gray700),
                const SizedBox(height: 4),
                Text('더 고르기', style: Typo.caption600.copyWith(color: Ms.gray700)),
              ]),
            ),
          );
        }
        final it = _items[i - 1];
        if (i == _items.length && _more) _load();
        return _tile(it);
      },
    );
  }

  Widget _square({Key? key, required VoidCallback onTap, required Widget child}) => GestureDetector(
        key: key,
        onTap: onTap,
        child: ClipRRect(borderRadius: BorderRadius.circular(8), child: SizedBox.square(dimension: _cell, child: child)),
      );

  Widget _tile(RecentItem it) {
    final order = _picked.indexOf(it.id);
    final on = order >= 0;
    final dim = it.tooLong || (!on && _picked.length >= pickLimit);
    return _square(
      key: Key('attach-item-${it.id}'),
      onTap: () => _toggle(it),
      child: Opacity(
        opacity: dim ? 0.4 : 1,
        child: Stack(fit: StackFit.expand, children: [
          FutureBuilder<Uint8List?>(
            future: _thumb(it),
            builder: (_, s) => s.data != null ? Image.memory(s.data!, fit: BoxFit.cover, gaplessPlayback: true) : Container(color: Ms.gray200),
          ),
          if (on) Container(decoration: BoxDecoration(border: Border.all(color: Ms.primary, width: 3), borderRadius: BorderRadius.circular(8))),
          if (it.video)
            Positioned(
              right: 5,
              bottom: 5,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                decoration: BoxDecoration(color: const Color(0x99000000), borderRadius: BorderRadius.circular(8)),
                child: Text(durationText(it.durationMs), style: Typo.caption600.copyWith(color: Ms.white)),
              ),
            ),
          Positioned(
            top: 5,
            right: 5,
            child: Container(
              key: Key('attach-pick-${it.id}'),
              width: 24,
              height: 24,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: on ? Ms.primary : const Color(0x55000000),
                border: Border.all(color: Ms.white, width: 1.5),
              ),
              child: on ? Text('${order + 1}', style: Typo.caption600.copyWith(color: Ms.white)) : null,
            ),
          ),
        ]),
      ),
    );
  }
}
