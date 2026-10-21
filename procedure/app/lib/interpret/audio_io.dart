// iOS 오디오 — 마이크 PCM16 16kHz mono 40ms 조각(record) · 번역 음성 24kHz PCM 재생(flutter_pcm_sound)
// 오디오 세션 = playAndRecord + defaultToSpeaker(번역 음성이 수화기 아닌 스피커로) · 백그라운드 오디오 없음(§2.4)
import 'dart:async';
import 'dart:typed_data';

import 'package:audio_session/audio_session.dart';
import 'package:flutter_pcm_sound/flutter_pcm_sound.dart' as pcm;
import 'package:record/record.dart';

import 'interpret_client.dart';

const micRate = 16000;
const chunkBytes = 640 * 2; // 40ms = 640 샘플 × 2바이트

// 녹음 스트림 조각을 1280바이트씩 다시 자른다
class Chunker {
  final int size;
  Chunker([this.size = chunkBytes]);
  final BytesBuilder _b = BytesBuilder(copy: true);
  List<Uint8List> add(Uint8List data) {
    _b.add(data);
    final out = <Uint8List>[];
    if (_b.length < size) return out;
    final all = _b.takeBytes();
    var i = 0;
    for (; i + size <= all.length; i += size) {
      out.add(Uint8List.sublistView(all, i, i + size));
    }
    if (i < all.length) _b.add(Uint8List.sublistView(all, i));
    return out;
  }
}

Future<void> configureSession() async {
  final s = await AudioSession.instance;
  await s.configure(AudioSessionConfiguration(
    avAudioSessionCategory: AVAudioSessionCategory.playAndRecord,
    avAudioSessionCategoryOptions: AVAudioSessionCategoryOptions.defaultToSpeaker | AVAudioSessionCategoryOptions.allowBluetooth,
    avAudioSessionMode: AVAudioSessionMode.defaultMode,
  ));
  await s.setActive(true);
}

class Mic {
  final AudioRecorder _rec = AudioRecorder();
  StreamSubscription<Uint8List>? _sub;

  Future<bool> permitted() => _rec.hasPermission();

  Future<void> start(void Function(Uint8List chunk) onChunk) async {
    final chunker = Chunker();
    final stream = await _rec.startStream(const RecordConfig(
      encoder: AudioEncoder.pcm16bits,
      sampleRate: micRate,
      numChannels: 1,
      echoCancel: true,
      noiseSuppress: true,
      autoGain: true,
      iosConfig: IosRecordConfig(categoryOptions: [
        IosAudioCategoryOption.defaultToSpeaker,
        IosAudioCategoryOption.allowBluetooth,
      ]),
    ));
    _sub = stream.listen((d) {
      for (final c in chunker.add(d)) {
        onChunk(c);
      }
    });
  }

  Future<void> stop() async {
    await _sub?.cancel();
    _sub = null;
    try {
      await _rec.stop();
    } catch (_) {}
  }

  Future<void> dispose() async {
    await stop();
    await _rec.dispose();
  }
}

class PcmPlayer implements PcmSink {
  int? _rate;

  @override
  Future<Duration> feed(Uint8List bytes, int sampleRate) async {
    if (_rate != sampleRate) {
      _rate = sampleRate;
      await pcm.FlutterPcmSound.setLogLevel(pcm.LogLevel.error);
      await pcm.FlutterPcmSound.setup(
          sampleRate: sampleRate, channelCount: 1, iosAudioCategory: pcm.IosAudioCategory.playAndRecord);
      // setup 이 옵션 없이 category 를 다시 정한다 — 스피커 출력을 되돌린다
      await configureSession();
    }
    // feed 는 ByteData 의 버퍼 전체를 보낸다 — 딱 맞는 새 버퍼로
    final copy = Uint8List.fromList(bytes);
    await pcm.FlutterPcmSound.feed(pcm.PcmArrayInt16(bytes: copy.buffer.asByteData()));
    return Duration(microseconds: (bytes.length ~/ 2) * 1000000 ~/ sampleRate);
  }

  @override
  Future<void> flush() async {
    if (_rate == null) return;
    _rate = null;
    try {
      await pcm.FlutterPcmSound.release();
    } catch (_) {}
  }
}
