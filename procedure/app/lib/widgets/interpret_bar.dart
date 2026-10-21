// 바닥 고정 통역 바(SPEC-004 §6.3 #7) — 「빠른 말하기 · <언어>」 + 문장 칩 6개(§5 · 기기 TTS) + [통역하기]
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../interpret/langs.dart';
import '../theme/tokens.dart';
import 'ui.dart';

// 문장 칩 줄 — 누르면 고객 언어로 읽는다. 그 언어 음성이 없으면 토스트
class PhraseChips extends StatefulWidget {
  final String langCode;
  final bool traditional;
  final double height;
  final bool icon;
  final void Function(Phrase p, String translated)? onSaid;
  const PhraseChips({super.key, required this.langCode, required this.traditional, this.height = 40, this.icon = true, this.onSaid});
  @override
  State<PhraseChips> createState() => _PhraseChipsState();
}

class _PhraseChipsState extends State<PhraseChips> {
  String? _playing;

  Future<void> _say(Phrase p) async {
    final app = AppScope.read(context);
    final tr = p.tr[phraseKey(widget.langCode, widget.traditional)] ?? p.ko;
    setState(() => _playing = p.ko);
    final ok = await app.speech.say(tr, widget.langCode, widget.traditional);
    if (!ok) {
      app.toaster.show('이 기기에 ${langName(widget.langCode)} 음성이 없어요');
    } else {
      widget.onSaid?.call(p, tr);
    }
    await Future<void>.delayed(const Duration(milliseconds: 1600));
    if (mounted && _playing == p.ko) setState(() => _playing = null);
  }

  @override
  Widget build(BuildContext context) => SizedBox(
        height: widget.height,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: phrases.length,
          separatorBuilder: (_, _) => const SizedBox(width: 6),
          itemBuilder: (_, i) {
            final p = phrases[i];
            final on = _playing == p.ko;
            return GestureDetector(
              onTap: () => _say(p),
              child: Container(
                padding: EdgeInsets.fromLTRB(widget.icon ? 10 : 12, 0, widget.icon ? 14 : 12, 0),
                decoration: BoxDecoration(
                  color: on ? Ms.primary : Ms.white,
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(color: on ? Ms.primary : Ms.gray300),
                ),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  if (widget.icon) ...[
                    Icon(Icons.volume_up_rounded, size: 14, color: on ? Ms.white : Ms.gray800),
                    const SizedBox(width: 6),
                  ],
                  Text(p.ko, style: (on ? Typo.caption600 : Typo.caption500).copyWith(color: on ? Ms.white : Ms.gray800, fontSize: 13)),
                ]),
              ),
            );
          },
        ),
      );
}

class InterpretBar extends StatelessWidget {
  final bool tablet;
  final String langCode;
  final bool traditional;
  final String? lastTalk;
  final VoidCallback onOpen;
  const InterpretBar({super.key, required this.tablet, required this.langCode, required this.traditional, this.lastTalk, required this.onOpen});

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    final name = langLabel(langCode, traditional);
    if (tablet) {
      return Container(
        padding: EdgeInsets.fromLTRB(24, 10, 24, 10 + bottom),
        decoration: const BoxDecoration(color: Ms.white, border: Border(top: BorderSide(color: Ms.gray200))),
        child: Row(children: [
          Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('통역 · $name', style: Typo.caption600.copyWith(color: Ms.gray700)),
            if (lastTalk != null) Text(lastTalk!, style: Typo.caption400.copyWith(color: Ms.gray600)),
          ]),
          const SizedBox(width: 12),
          Expanded(child: PhraseChips(langCode: langCode, traditional: traditional)),
          const SizedBox(width: 12),
          SizedBox(width: 160, child: MsButton('통역하기', size: BtnSize.lg, expand: true, onPressed: onOpen)),
        ]),
      );
    }
    return Container(
      padding: EdgeInsets.fromLTRB(12, 10, 12, 10 + (bottom > 0 ? bottom : 10)),
      decoration: const BoxDecoration(color: Ms.white, border: Border(top: BorderSide(color: Ms.gray200))),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Row(children: [
            Text('빠른 말하기 · $name', style: Typo.caption600.copyWith(color: Ms.gray700)),
            const SizedBox(width: 8),
            if (lastTalk != null)
              Expanded(child: Text(lastTalk!, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.caption400.copyWith(color: Ms.gray600))),
          ]),
        ),
        const SizedBox(height: 8),
        PhraseChips(langCode: langCode, traditional: traditional),
        const SizedBox(height: 8),
        MsButton('통역하기', size: BtnSize.lg, expand: true, onPressed: onOpen),
      ]),
    );
  }
}
