// medikit 모양을 Flutter 로(SPEC-004 §6.6) — Button(lg 48 · md 40 · sm 33) · Badge(sm · dot) · 토스트
import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import '../view/view.dart';

enum BtnVariant { solid, outlined }

enum BtnColor { blue, gray, red }

enum BtnSize { lg, md, sm }

class MsButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final BtnVariant variant;
  final BtnColor color;
  final BtnSize size;
  final bool expand;
  const MsButton(
    this.label, {
    super.key,
    this.onPressed,
    this.variant = BtnVariant.solid,
    this.color = BtnColor.blue,
    this.size = BtnSize.md,
    this.expand = false,
  });

  @override
  Widget build(BuildContext context) {
    final off = onPressed == null;
    final main = switch (color) {
      BtnColor.blue => Ms.primary,
      BtnColor.gray => Ms.gray800,
      BtnColor.red => Ms.red,
    };
    final h = switch (size) {
      BtnSize.lg => 48.0,
      BtnSize.md => 40.0,
      BtnSize.sm => 33.0,
    };
    final text = switch (size) {
      BtnSize.lg => Typo.headingMd600,
      BtnSize.md => Typo.body600,
      BtnSize.sm => Typo.caption600.copyWith(fontSize: 13),
    };
    Color bg, fg, border;
    if (off) {
      bg = variant == BtnVariant.solid ? Ms.gray300 : Ms.white;
      fg = Ms.gray600;
      border = variant == BtnVariant.solid ? Ms.gray300 : Ms.gray300;
    } else if (variant == BtnVariant.solid) {
      bg = color == BtnColor.gray ? Ms.gray700 : main;
      fg = Ms.white;
      border = bg;
    } else {
      bg = Ms.white;
      fg = main;
      border = color == BtnColor.gray ? Ms.gray300 : main;
    }
    final child = Container(
      height: h,
      padding: EdgeInsets.symmetric(horizontal: size == BtnSize.sm ? 14 : 16),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: border),
      ),
      alignment: Alignment.center,
      child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: text.copyWith(color: fg)),
    );
    return Semantics(
      button: true,
      enabled: !off,
      label: label,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onPressed,
        child: expand ? SizedBox(width: double.infinity, child: child) : IntrinsicWidth(child: child),
      ),
    );
  }
}

(Color, Color) badgeColors(BadgeVariant v) => switch (v) {
      BadgeVariant.neutral => (Ms.gray200, Ms.gray800),
      BadgeVariant.primary => (Ms.primary100, Ms.primary),
      BadgeVariant.warning => (Ms.yellow100, Ms.yellow),
      BadgeVariant.danger => (Ms.red100, Ms.red),
      BadgeVariant.purple => (Ms.purple100, Ms.purple),
    };

class MsBadge extends StatelessWidget {
  final String text;
  final BadgeVariant variant;
  final bool dot;
  const MsBadge(this.text, this.variant, {super.key, this.dot = true});

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = badgeColors(variant);
    final dotColor = switch (variant) {
      BadgeVariant.neutral => Ms.gray600,
      BadgeVariant.primary => Ms.primary,
      BadgeVariant.warning => Ms.yellow,
      BadgeVariant.danger => Ms.red,
      BadgeVariant.purple => Ms.purple,
    };
    return Container(
      height: 22,
      padding: const EdgeInsets.symmetric(horizontal: 8),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (dot) ...[
          Container(width: 6, height: 6, decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle)),
          const SizedBox(width: 5),
        ],
        Flexible(child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.caption600.copyWith(color: fg))),
      ]),
    );
  }
}

// 작은 칩(국적 · 첫/재내원 · 수납 필요)
class Tag extends StatelessWidget {
  final String text;
  final Color bg;
  final Color fg;
  final bool bold;
  const Tag(this.text, {super.key, this.bg = Ms.gray200, this.fg = Ms.gray700, this.bold = false});
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(4)),
        child: Text(text, style: (bold ? Typo.caption600 : Typo.caption500).copyWith(color: fg)),
      );
}

Widget visitTag(bool isNew) => isNew
    ? Tag(visitText(true), bg: Ms.primary100, fg: Ms.primary, bold: true)
    : Tag(visitText(false), bg: Ms.gray200, fg: Ms.gray700, bold: true);

// 토스트 — 앱 한 곳(아래 쪽)에 2.6초
class Toaster extends ChangeNotifier {
  String? text;
  int _n = 0;
  Timer? _t;
  void show(String msg) {
    text = msg;
    _n++;
    final n = _n;
    _t?.cancel();
    _t = Timer(const Duration(milliseconds: 2600), () {
      if (n == _n) {
        text = null;
        notifyListeners();
      }
    });
    notifyListeners();
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }
}

class ToastLayer extends StatelessWidget {
  final Toaster toaster;
  final Widget child;
  const ToastLayer({super.key, required this.toaster, required this.child});
  @override
  Widget build(BuildContext context) => Stack(children: [
        child,
        ListenableBuilder(
          listenable: toaster,
          builder: (context, _) {
            final t = toaster.text;
            // 화면 위 — safe area + 머리(56~64) 아래(E2E A3)
            return Positioned(
              left: 16,
              right: 16,
              top: MediaQuery.paddingOf(context).top + 68,
              child: IgnorePointer(
                child: AnimatedOpacity(
                  opacity: t == null ? 0 : 1,
                  duration: const Duration(milliseconds: 180),
                  // Navigator 밖(MaterialApp.builder)이라 Material 이 없다 — 없으면 글자에 노란 이중 밑줄(E2E A3)
                  child: Material(
                    type: MaterialType.transparency,
                    child: Center(
                      child: t == null
                          ? const SizedBox.shrink()
                          : Container(
                              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                              decoration: BoxDecoration(
                                color: const Color(0xE6222222),
                                borderRadius: BorderRadius.circular(10),
                                boxShadow: const [BoxShadow(color: Color(0x29000000), blurRadius: 12, offset: Offset(0, 4))],
                              ),
                              child: Text(t, textAlign: TextAlign.center, style: Typo.body500.copyWith(color: Ms.white)),
                            ),
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ]);
}

// 1초마다 다시 그리기 — 경과 타이머 · 시계
class Ticker extends StatefulWidget {
  final Widget Function(BuildContext context) builder;
  const Ticker({super.key, required this.builder});
  @override
  State<Ticker> createState() => _TickerState();
}

class _TickerState extends State<Ticker> {
  Timer? _t;
  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.builder(context);
}

// 바텀 시트 머리 손잡이
class SheetHandle extends StatelessWidget {
  const SheetHandle({super.key});
  @override
  Widget build(BuildContext context) => SizedBox(
        height: 20,
        child: Center(
          child: Container(width: 44, height: 5, decoration: BoxDecoration(color: Ms.gray300, borderRadius: BorderRadius.circular(3))),
        ),
      );
}

class Boxed extends StatelessWidget {
  final Widget child;
  final Color color;
  final Color? border;
  final double borderWidth;
  final EdgeInsets padding;
  const Boxed({super.key, required this.child, this.color = Ms.white, this.border, this.borderWidth = 1, this.padding = const EdgeInsets.fromLTRB(14, 12, 14, 12)});
  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: padding,
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(14),
          border: border == null ? null : Border.all(color: border!, width: borderWidth),
        ),
        child: child,
      );
}
