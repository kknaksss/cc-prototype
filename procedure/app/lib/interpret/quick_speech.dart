// 빠른 말하기(SPEC-004 §5) — 기기 TTS(iOS 음성 · flutter_tts)로 고객 언어 문장을 읽는다. back · Soniox 를 거치지 않는다
import 'package:flutter_tts/flutter_tts.dart';

import 'langs.dart';

class QuickSpeech {
  final FlutterTts _tts = FlutterTts();
  bool _ready = false;

  Future<void> _init() async {
    if (_ready) return;
    _ready = true;
    await _tts.awaitSpeakCompletion(false);
    await _tts.setSharedInstance(true);
    // 통역 중(마이크 열림)에도 스피커로 나오게
    await _tts.setIosAudioCategory(IosTextToSpeechAudioCategory.playAndRecord, [
      IosTextToSpeechAudioCategoryOptions.defaultToSpeaker,
      IosTextToSpeechAudioCategoryOptions.allowBluetooth,
      IosTextToSpeechAudioCategoryOptions.mixWithOthers,
    ]);
  }

  // 읽는다 — 그 언어 음성이 기기에 없으면 false(호출한 쪽이 토스트)
  Future<bool> say(String text, String code, bool traditional) async {
    try {
      await _init();
      final locale = ttsLocale(code, traditional);
      final ok = await _tts.isLanguageAvailable(locale);
      if (ok != true) return false;
      await _tts.stop();
      await _tts.setLanguage(locale);
      await _tts.speak(text);
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<void> stop() async {
    try {
      await _tts.stop();
    } catch (_) {}
  }
}
