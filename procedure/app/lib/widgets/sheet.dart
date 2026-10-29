// 앱 바텀 시트 공용(review-code r3 W3-1 — 통역 드로어 D9-65 와 같은 규칙) — 앱의 모든 showModalBottomSheet 는 이것으로 연다.
//   · 놓인 칸 기준: 시트는 그것을 연 Navigator 의 칸(폰 = 탭바 위 본문 · 키보드가 열리면 셸이 키보드만큼 줄인 칸) 안에 그려진다
//   · 위 안전 영역(상태 표시줄 · 노치 · Dynamic Island) 아래로 제한(useSafeArea) — 큰 아이폰 · 키보드 열림에서도 머리가 화면 안
//   · heightFactor = 그 칸(위 안전 영역 뺀) 높이의 몇 % — 화면 전체 높이로 잡지 않는다(F9 · W3-1 의 원인)
//   · busy = 참인 동안 닫히지 않음(바깥 누름 · 뒤로 · 끌어 내림 — W3-3). busy 가 있으면 끌어 내림은 시트가 직접 받는다(PopScope 를 따르게)
import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/material.dart';

import '../theme/tokens.dart';

const sheetShape = RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20)));

Future<T?> showAppSheet<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  Color backgroundColor = Ms.white,
  Color barrierColor = Ms.dim,
  ShapeBorder shape = sheetShape,
  bool isScrollControlled = false,
  BoxConstraints? constraints,
  double? heightFactor,
  ValueListenable<bool>? busy,
}) {
  Widget content(BuildContext ctx) {
    Widget child = heightFactor == null
        ? builder(ctx)
        : LayoutBuilder(builder: (ctx, c) => SizedBox(height: c.maxHeight * heightFactor, child: builder(ctx)));
    if (busy != null) {
      child = ValueListenableBuilder<bool>(
        valueListenable: busy,
        child: _DragToClose(child: child),
        builder: (ctx, b, child) => PopScope(canPop: !b, child: child!),
      );
    }
    return child;
  }

  return showModalBottomSheet<T>(
    context: context,
    useSafeArea: true,
    isScrollControlled: isScrollControlled || heightFactor != null,
    backgroundColor: backgroundColor,
    barrierColor: barrierColor,
    shape: shape,
    constraints: constraints,
    enableDrag: busy == null,
    builder: content,
  );
}

// 끌어 내리면 닫기 — 시트 기본 끌기(Navigator.pop · PopScope 무시) 대신 maybePop 으로(보내는 중이면 안 닫힘)
class _DragToClose extends StatefulWidget {
  final Widget child;
  const _DragToClose({required this.child});
  @override
  State<_DragToClose> createState() => _DragToCloseState();
}

class _DragToCloseState extends State<_DragToClose> {
  double _dy = 0;
  @override
  Widget build(BuildContext context) => GestureDetector(
        behavior: HitTestBehavior.translucent,
        onVerticalDragStart: (_) => _dy = 0,
        onVerticalDragUpdate: (d) => _dy += d.delta.dy,
        onVerticalDragEnd: (d) {
          if (_dy > 60 || (d.primaryVelocity ?? 0) > 500) Navigator.of(context).maybePop();
        },
        child: widget.child,
      );
}
