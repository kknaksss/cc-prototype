// flutter drive 드라이버 — 앱 안 takeScreenshot 결과를 SHOT_DIR 에 저장(시뮬레이터 스크린샷 · SPEC-004 §8.2)
import 'dart:io';

import 'package:integration_test/integration_test_driver_extended.dart';

Future<void> main() => integrationDriver(
      onScreenshot: (name, bytes, [args]) async {
        final dir = Platform.environment['SHOT_DIR'] ?? 'build/screenshots';
        final f = File('$dir/$name.png');
        await f.parent.create(recursive: true);
        await f.writeAsBytes(bytes);
        return true;
      },
    );
