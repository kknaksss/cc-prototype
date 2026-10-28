// 자동 저장 칸(웹 E2E batch 3 #3 ~ #5 와 같은 규칙 · 사용자 「자동 저장으로 하기로 한 거 아니야?」 2026-10-28) —
// [저장] · [수정] 버튼 없음. 입력을 멈추고 1초 뒤 · 칸을 벗어날 때 · 화면을 나갈 때(남은 것) 저장. 칸 옆 작은 상태
// 「저장 중 · 저장됨 · 저장 못 함(다시)」 · 실패하면 쓴 글자 그대로. 같은 값이면 부르지 않는다(back 도 같은 값이면 KOS 안 부름)
import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api.dart';
import '../theme/tokens.dart';

enum SaveState { idle, saving, saved, failed }

// 칸 옆 상태 글자 — 실패면 [다시]
class SaveStatus extends StatelessWidget {
  final SaveState state;
  final VoidCallback? onRetry;
  const SaveStatus(this.state, {super.key, this.onRetry});

  @override
  Widget build(BuildContext context) => switch (state) {
        SaveState.idle => const SizedBox.shrink(),
        SaveState.saving => Text('저장 중…', key: const Key('save-saving'), style: Typo.caption500.copyWith(color: Ms.gray500)),
        SaveState.saved => Text('저장됨', key: const Key('save-saved'), style: Typo.caption500.copyWith(color: Ms.gray500)),
        SaveState.failed => GestureDetector(
            onTap: onRetry,
            child: Text('저장 못 함 · 다시', key: const Key('save-failed'), style: Typo.caption600.copyWith(color: Ms.red)),
          ),
      };
}

class AutoSaveField extends StatefulWidget {
  final String value; // 서버 값 — 고치는 중이 아니면 새 값으로 바뀐다(5초 폴링)
  final Future<void> Function(String v) onSave; // ApiError 를 던지면 「저장 못 함」
  final String? label; // 있으면 위에 이름 + 상태 · 없으면 상태만 오른쪽 위
  final String? hint;
  final bool enabled;
  final int minLines, maxLines;
  final TextInputType? keyboardType;
  final void Function(ApiError e)? onError; // 401 등 화면이 처리할 것
  final Duration debounce;
  const AutoSaveField({
    super.key,
    required this.value,
    required this.onSave,
    this.label,
    this.hint,
    this.enabled = true,
    this.minLines = 1,
    this.maxLines = 1,
    this.keyboardType,
    this.onError,
    this.debounce = const Duration(seconds: 1),
  });

  @override
  State<AutoSaveField> createState() => _AutoSaveFieldState();
}

class _AutoSaveFieldState extends State<AutoSaveField> {
  late final TextEditingController _ctl;
  final _focus = FocusNode();
  late String _saved; // 마지막으로 서버와 같은 값(initState 에서 바로 — 늦게 읽히면 새 서버 값이 들어가 갱신이 막혔다)
  SaveState _state = SaveState.idle;
  Timer? _timer;
  Future<void>? _inflight;

  @override
  void initState() {
    super.initState();
    _ctl = TextEditingController(text: widget.value);
    _saved = widget.value;
    _focus.addListener(() {
      if (!_focus.hasFocus) _save(); // 칸을 벗어날 때
    });
  }

  @override
  void didUpdateWidget(AutoSaveField old) {
    super.didUpdateWidget(old);
    // 서버 값이 바뀌었고 이 칸을 고치는 중이 아니면 새 값으로(남이 고친 것 · 폴링)
    if (widget.value != old.value && !_focus.hasFocus && _ctl.text == _saved && _state != SaveState.saving) {
      _ctl.text = widget.value;
      _saved = widget.value;
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    // 화면을 나갈 때 남은 것 저장(결과는 화면이 없으니 조용히)
    final v = _ctl.text;
    if (widget.enabled && v != _saved) widget.onSave(v).catchError((_) {});
    _ctl.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _changed(String _) {
    _timer?.cancel();
    _timer = Timer(widget.debounce, _save); // 입력을 멈추고 1초
  }

  Future<void> _save() async {
    _timer?.cancel();
    if (!widget.enabled) return;
    await _inflight; // 한 번에 하나 — 앞 저장이 끝난 뒤 지금 글자로
    if (!mounted) return;
    final v = _ctl.text;
    if (v == _saved) return; // 같은 값 = 부르지 않음
    setState(() => _state = SaveState.saving);
    final f = widget.onSave(v);
    _inflight = f.catchError((_) {});
    try {
      await f;
      _saved = v;
      if (mounted) setState(() => _state = SaveState.saved);
    } on ApiError catch (e) {
      if (mounted) setState(() => _state = SaveState.failed); // 쓴 글자는 그대로
      widget.onError?.call(e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = SaveStatus(_state, onRetry: _save);
    final field = TextField(
      controller: _ctl,
      focusNode: _focus,
      enabled: widget.enabled,
      minLines: widget.minLines,
      maxLines: widget.maxLines,
      keyboardType: widget.keyboardType,
      style: Typo.body400,
      onChanged: _changed,
      onSubmitted: (_) => _save(),
      // 테두리 · 바탕은 앱 테마(웹 Input 과 같게) — 못 고침 = gray-100 · 저장 못 함 = red 테두리
      decoration: InputDecoration(
        hintText: widget.hint,
        fillColor: widget.enabled ? null : Ms.gray100,
        enabledBorder: _state == SaveState.failed
            ? OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: Ms.red))
            : null,
      ),
    );
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      if (widget.label != null || _state != SaveState.idle)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(children: [
            if (widget.label != null) Expanded(child: Text(widget.label!, style: Typo.body400.copyWith(color: Ms.gray600))) else const Spacer(),
            status,
          ]),
        ),
      field,
    ]);
  }
}
