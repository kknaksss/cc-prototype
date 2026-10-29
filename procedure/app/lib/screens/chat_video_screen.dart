// 동영상 재생(SPEC-007 §10.6 · D9-53 · r3) — 사진 크게 보기(chat_photo_screen ChatPhotoViewer)와 같은 검정 전체 화면(rootNavigator):
//   위 = [닫기] · 보낸 사람 · 「M월 D일 HH:MM」 / 가운데 = 영상(비율 그대로 · 열면 바로 재생 · 받는 동안 썸네일 + 도는 표시) /
//   아래 = [▶/❚❚] · 지난 시간 · 끌 수 있는 막대(옮기면 그 자리부터 끊어 받음) · 전체 길이.
// 재생기 = video_player(AVPlayer) · 무음 스위치를 따름(.soloAmbient — W-4) — #17 을 Bearer 헤더로 연다(파일을 먼저 내려받지 않고 Range 로 끊어 받음 · 디스크 캐시 없음 · §9.3).
// 저장 · 공유 버튼 없음(공유는 길게 누르기만 — §10.7) · 다 보면 처음 화면에서 멈춤 · 닫으면 재생기를 버림 · 못 열면 토스트
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../app_state.dart';
import '../chat/chat_model.dart';
import '../chat/chat_state.dart' show thumbKey;
import '../chat/chat_view.dart';
import '../chat/video_pick.dart' show VideoChannel;
import '../theme/tokens.dart';

// onReady = 재생기가 열림(그 뒤에 오디오 세션을 무음 스위치 따르게 — video_player 가 초기화 때 .playback 으로 올리므로)
typedef VideoPlayerBuilder = Widget Function(Uri url, Map<String, String> headers, Uint8List? thumb, VoidCallback onReady);

// 시험이 바꿔 끼운다(플랫폼 재생기 없음)
VideoPlayerBuilder buildChatVideoPlayer =
    (url, headers, thumb, onReady) => ChatVideoPlayer(url: url, headers: headers, thumb: thumb, onReady: onReady);

// 재생 화면 오디오 세션(review-code r2 W-4 · SPEC §9.2 「소리 = 기기 음량 · 무음 스위치를 따른다」) — 열 때 지금 세션을 적어 두고 ·
// 재생기가 열리면 .soloAmbient · 닫을 때 원래대로(통역 .playAndRecord 중이면 네이티브가 건드리지 않음)
VideoChannel chatVideoAudio = const VideoChannel();

const videoNotFound = '동영상을 찾을 수 없어요';

Future<void> openVideoPlayer(BuildContext context, ChatMessage m) {
  if (m.video == null || m.deleted) return Future.value();
  return Navigator.of(context, rootNavigator: true).push(MaterialPageRoute(fullscreenDialog: true, builder: (_) => ChatVideoViewer(message: m)));
}

class ChatVideoViewer extends StatefulWidget {
  final ChatMessage message;
  const ChatVideoViewer({super.key, required this.message});
  @override
  State<ChatVideoViewer> createState() => _ChatVideoViewerState();
}

class _ChatVideoViewerState extends State<ChatVideoViewer> {
  late final VideoChannel _audio = chatVideoAudio;

  @override
  void initState() {
    super.initState();
    _audio.audioSave();
  }

  @override
  void dispose() {
    _audio.audioRestore();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final message = widget.message;
    final app = AppScope.read(context);
    final v = message.video!;
    return Scaffold(
      backgroundColor: Ms.black,
      body: SafeArea(
        child: Column(children: [
          SizedBox(
            height: 52,
            child: Row(children: [
              TextButton(
                key: const Key('chat-video-close'),
                onPressed: () => Navigator.of(context).pop(),
                child: Text('닫기', style: Typo.headingMd500.copyWith(color: Ms.white)),
              ),
              Expanded(
                child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Text(message.sender.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600.copyWith(color: Ms.white)),
                  Text(viewerTime(message.createdAt), style: Typo.caption400.copyWith(color: Ms.gray500)),
                ]),
              ),
              const SizedBox(width: 64),
            ]),
          ),
          Expanded(
              child: buildChatVideoPlayer(app.api.chatVideoUri(v.id), app.api.authHeaders, app.chat.photos.get(thumbKey(v.id)), _audio.audioFollowSilent)),
        ]),
      ),
    );
  }
}

class ChatVideoPlayer extends StatefulWidget {
  final Uri url;
  final Map<String, String> headers;
  final Uint8List? thumb;
  final VoidCallback? onReady;
  const ChatVideoPlayer({super.key, required this.url, required this.headers, this.thumb, this.onReady});
  @override
  State<ChatVideoPlayer> createState() => _ChatVideoPlayerState();
}

class _ChatVideoPlayerState extends State<ChatVideoPlayer> {
  late final VideoPlayerController _c = VideoPlayerController.networkUrl(widget.url, httpHeaders: widget.headers);
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _c.addListener(_onTick);
    _c.initialize().then((_) {
      if (!mounted) return;
      widget.onReady?.call(); // 무음 스위치를 따르게(재생 전에)
      setState(() => _ready = true);
      _c.play();
    }, onError: (Object _) {
      if (!mounted) return;
      AppScope.read(context).toaster.show(videoNotFound);
      Navigator.of(context).maybePop();
    });
  }

  // 다 보면 처음 화면에서 멈춤
  void _onTick() {
    final v = _c.value;
    if (v.isInitialized && !v.isPlaying && v.duration > Duration.zero && v.position >= v.duration) {
      _c.seekTo(Duration.zero);
    }
  }

  @override
  void dispose() {
    _c.removeListener(_onTick);
    _c.dispose(); // 재생기를 버림 — 받은 조각은 AVPlayer 메모리에만
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final thumb = widget.thumb;
    return Column(children: [
      Expanded(
        child: Center(
          child: _ready
              ? AspectRatio(aspectRatio: _c.value.aspectRatio, child: VideoPlayer(_c))
              : Stack(alignment: Alignment.center, children: [
                  if (thumb != null) Image.memory(thumb, fit: BoxFit.contain, gaplessPlayback: true),
                  const CircularProgressIndicator(strokeWidth: 2, color: Ms.white),
                ]),
        ),
      ),
      ValueListenableBuilder<VideoPlayerValue>(
        valueListenable: _c,
        builder: (context, v, _) => Padding(
          padding: const EdgeInsets.fromLTRB(4, 4, 16, 8),
          child: Row(children: [
            IconButton(
              key: const Key('chat-video-play'),
              tooltip: v.isPlaying ? '멈춤' : '재생',
              onPressed: !_ready ? null : () => v.isPlaying ? _c.pause() : _c.play(),
              icon: Icon(v.isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded, color: Ms.white, size: 30),
            ),
            Text(durationText(v.position.inMilliseconds), style: Typo.caption500.copyWith(color: Ms.white)),
            const SizedBox(width: 10),
            Expanded(
              child: _ready
                  ? VideoProgressIndicator(_c,
                      allowScrubbing: true,
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      colors: const VideoProgressColors(playedColor: Ms.white, bufferedColor: Ms.gray600, backgroundColor: Ms.gray800))
                  : const SizedBox(height: 4),
            ),
            const SizedBox(width: 10),
            Text(durationText(v.duration.inMilliseconds), style: Typo.caption500.copyWith(color: Ms.gray500)),
          ]),
        ),
      ),
    ]);
  }
}
