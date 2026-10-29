// medikit 모양을 Flutter 로(SPEC-004 §6.6) — Button(lg 48 · md 40 · sm 33) · Badge(sm · dot) · 토스트
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show TextInputFormatter;

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
  final IconData? icon; // 왼쪽 아이콘(채팅 [사진] — medikit leftIcon)
  const MsButton(
    this.label, {
    super.key,
    this.onPressed,
    this.variant = BtnVariant.solid,
    this.color = BtnColor.blue,
    this.size = BtnSize.md,
    this.expand = false,
    this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final off = onPressed == null;
    final main = switch (color) {
      BtnColor.blue => Ms.primary,
      BtnColor.gray => Ms.gray800,
      BtnColor.red => Ms.red,
    };
    // 높이도 태블릿 글자 배율만큼(T4)
    final h = uiScale(MediaQuery.sizeOf(context)) *
        switch (size) {
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
      child: icon == null
          ? Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: text.copyWith(color: fg))
          : Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(icon, size: 18, color: fg),
              const SizedBox(width: 4),
              Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: text.copyWith(color: fg)),
            ]),
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
  final ChipLook? look; // 2계층 칩 색으로 덮기(§6.9)
  const MsBadge(this.text, this.variant, {super.key, this.dot = true, this.look});

  // 카드 · 머리 상태 Badge(덮어쓰기면 점 · 아니면 2계층 칩)
  factory MsBadge.of(BadgeView v, {Key? key}) => MsBadge(v.text, v.variant, key: key, dot: v.dot, look: v.look);

  // 칩 하나(2계층 · 점 없음)
  factory MsBadge.chip(ChipLook l, {Key? key}) => MsBadge(l.text, BadgeVariant.neutral, key: key, dot: false, look: l);

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = look != null ? (look!.bg, look!.fg) : badgeColors(variant);
    final dotColor = switch (variant) {
      BadgeVariant.neutral => Ms.gray600,
      BadgeVariant.primary => Ms.primary,
      BadgeVariant.warning => Ms.yellow,
      BadgeVariant.danger => Ms.red,
      BadgeVariant.purple => Ms.purple,
    };
    return Container(
      height: 22 * uiScale(MediaQuery.sizeOf(context)),
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
  String? action; // 버튼 글자(예: 되돌리기) — 있으면 5초(웹 UNDO_TOAST_MS)
  VoidCallback? onAction;
  int _n = 0;
  Timer? _t;
  void show(String msg, {String? action, VoidCallback? onAction}) {
    text = msg;
    this.action = onAction == null ? null : action;
    this.onAction = onAction;
    _n++;
    final n = _n;
    _t?.cancel();
    _t = Timer(Duration(milliseconds: this.action != null ? 5000 : 2600), () {
      if (n == _n) hide();
    });
    notifyListeners();
  }

  void hide() {
    text = null;
    action = null;
    onAction = null;
    notifyListeners();
  }

  void tapAction() {
    final f = onAction;
    hide();
    f?.call();
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
                ignoring: t == null || toaster.action == null,
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
                              child: Row(mainAxisSize: MainAxisSize.min, children: [
                                Flexible(child: Text(t, textAlign: TextAlign.center, style: Typo.body500.copyWith(color: Ms.white))),
                                if (toaster.action != null) ...[
                                  const SizedBox(width: 16),
                                  GestureDetector(
                                    behavior: HitTestBehavior.opaque,
                                    onTap: toaster.tapAction,
                                    child: Text(toaster.action!, style: Typo.body600.copyWith(color: Ms.primary300)),
                                  ),
                                ],
                              ]),
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

// ─── 채팅 시안 medikit 컴포넌트(SPEC-007 §10.0 — 앱에 같은 위젯이 없던 것) · 토큰 색만

// Input(size m · 40) — 왼쪽 아이콘(검색) · 여러 줄(메시지 입력) · 입력 제한
class MsInput extends StatelessWidget {
  final TextEditingController? controller;
  final String? hint;
  final IconData? icon;
  final int minLines, maxLines;
  final ValueChanged<String>? onChanged;
  final List<TextInputFormatter>? formatters;
  final FocusNode? focusNode;
  final Key? fieldKey;
  const MsInput({super.key, this.controller, this.hint, this.icon, this.minLines = 1, this.maxLines = 1, this.onChanged, this.formatters, this.focusNode, this.fieldKey});

  @override
  Widget build(BuildContext context) => TextField(
        key: fieldKey,
        controller: controller,
        focusNode: focusNode,
        minLines: minLines,
        maxLines: maxLines,
        onChanged: onChanged,
        inputFormatters: formatters,
        textInputAction: maxLines == 1 ? TextInputAction.search : TextInputAction.newline,
        keyboardType: maxLines == 1 ? TextInputType.text : TextInputType.multiline,
        style: Typo.body400,
        decoration: InputDecoration(
          hintText: hint,
          prefixIcon: icon == null ? null : Icon(icon, size: 18, color: Ms.gray600),
          prefixIconConstraints: const BoxConstraints(minWidth: 36, minHeight: 36),
        ),
      );
}

// Label — 입력 칸 위 글자
class MsLabel extends StatelessWidget {
  final String text;
  const MsLabel(this.text, {super.key});
  @override
  Widget build(BuildContext context) => Text(text, style: Typo.caption600.copyWith(color: Ms.gray700));
}

// Checkbox(20 · 둥근 4) — 켬 = primary 채움 + ✓ · 꺼짐(못 고름) = gray-200
class MsCheckbox extends StatelessWidget {
  final bool value;
  final bool enabled;
  const MsCheckbox(this.value, {super.key, this.enabled = true});
  @override
  Widget build(BuildContext context) => Container(
        width: 20,
        height: 20,
        decoration: BoxDecoration(
          color: value ? (enabled ? Ms.primary : Ms.gray400) : (enabled ? Ms.white : Ms.gray200),
          borderRadius: BorderRadius.circular(4),
          border: Border.all(color: value ? (enabled ? Ms.primary : Ms.gray400) : Ms.gray300, width: 1.5),
        ),
        child: value ? const Icon(Icons.check_rounded, size: 15, color: Ms.white) : null,
      );
}

// Card — 흰 바탕 · gray-200 테두리 · 둥근 12 · 고름(selected) = primary-100 바탕 · 누르기(interactive)
class MsCard extends StatelessWidget {
  final Widget child;
  final bool selected;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final EdgeInsets padding;
  final bool shadow;
  const MsCard({super.key, required this.child, this.selected = false, this.onTap, this.onLongPress, this.padding = const EdgeInsets.all(12), this.shadow = false});
  @override
  Widget build(BuildContext context) {
    final box = Container(
      padding: padding,
      decoration: BoxDecoration(
        color: selected ? Ms.primary100 : Ms.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: selected ? Ms.primary : Ms.gray200),
        boxShadow: shadow ? const [BoxShadow(color: Color(0x29000000), blurRadius: 16, offset: Offset(0, 6))] : null,
      ),
      child: child,
    );
    if (onTap == null && onLongPress == null) return box;
    return GestureDetector(behavior: HitTestBehavior.opaque, onTap: onTap, onLongPress: onLongPress, child: box);
  }
}

// Progress(sm · primary) — 얇은 막대
class MsProgress extends StatelessWidget {
  final double value;
  const MsProgress(this.value, {super.key});
  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(2),
        child: SizedBox(
          height: 4,
          child: LinearProgressIndicator(value: value.clamp(0, 1), backgroundColor: Ms.gray300, color: Ms.primary, minHeight: 4),
        ),
      );
}

// Banner(primary · 그림자 · 오른쪽 동작) — 앱 안 채팅 배너(DS:S11 · S13d)
class MsBanner extends StatelessWidget {
  final String text;
  final String? action;
  final VoidCallback? onAction;
  const MsBanner(this.text, {super.key, this.action, this.onAction});
  @override
  Widget build(BuildContext context) => Material(
        type: MaterialType.transparency,
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
          decoration: BoxDecoration(
            color: Ms.primary100,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Ms.primary500),
            boxShadow: const [BoxShadow(color: Color(0x29000000), blurRadius: 16, offset: Offset(0, 6))],
          ),
          child: Row(children: [
            const Icon(Icons.chat_bubble_rounded, size: 18, color: Ms.primary),
            const SizedBox(width: 8),
            Expanded(child: Text(text, maxLines: 2, overflow: TextOverflow.ellipsis, style: Typo.body500)),
            if (action != null) ...[const SizedBox(width: 8), MsButton(action!, size: BtnSize.sm, onPressed: onAction)],
          ]),
        ),
      );
}

// 켬/끔 한 줄 — 설정 알림 칸과 방 정보 「알림」이 같은 꼴(Switch.adaptive · SPEC-007 §10.0 · R1:W-7)
class SwitchRow extends StatelessWidget {
  final String k;
  final bool v;
  final ValueChanged<bool>? onChanged;
  final String? sub;
  const SwitchRow(this.k, this.v, this.onChanged, {super.key, this.sub});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 6, 8, 6),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(k, style: Typo.body500),
              if (sub != null) Text(sub!, style: Typo.caption400.copyWith(color: Ms.gray600)),
            ]),
          ),
          Switch.adaptive(value: v, activeTrackColor: Ms.primary, onChanged: onChanged),
        ]),
      );
}
