// 의사 호출 시트(SPEC-004 §6.4) — 모바일 = 바텀 시트 · 태블릿 = 가운데 시트
// 「호출할 시술」 = pickable 시술만 켜짐 · 「누구에게」 = 모든 의사 + 원장(비어 있는 원장 먼저) · 하나만 · 다시 누르면 해제
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../model/board.dart';
import '../screens/board_screen.dart' show isTablet;
import '../theme/tokens.dart';
import '../view/view.dart';
import 'ui.dart';
import 'sheet.dart';

Future<void> openCallSheet(BuildContext context, {required int visitId, required Set<int> preselect}) {
  final app = AppScope.read(context);
  final sheet = AppScope(state: app, child: CallSheet(visitId: visitId, preselect: preselect));
  if (isTablet(context)) {
    return showDialog(
      context: context,
      barrierColor: Ms.dim,
      builder: (_) => Dialog(
        backgroundColor: Ms.white,
        insetPadding: const EdgeInsets.all(40),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 560, maxHeight: 640), child: sheet),
      ),
    );
  }
  return showAppSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Ms.white,
    barrierColor: Ms.dim,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.88),
    builder: (_) => sheet,
  );
}

// 받을 대상 — null = 아직 안 고름 · -1 = 모든 의사 · 그 밖 = 원장 id
class CallSheet extends StatefulWidget {
  final int visitId;
  final Set<int> preselect;
  const CallSheet({super.key, required this.visitId, required this.preselect});
  @override
  State<CallSheet> createState() => _CallSheetState();
}

class _CallSheetState extends State<CallSheet> {
  late final Set<int> _picks = {...widget.preselect};
  int? _to;
  bool _sending = false;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final tablet = isTablet(context);
    return ListenableBuilder(
      listenable: app.stream,
      builder: (context, _) {
        final b = app.stream.board;
        BoardCard? c;
        for (final x in b?.cards ?? const <BoardCard>[]) {
          if (x.visitId == widget.visitId) c = x;
        }
        if (b == null || c == null) return const SizedBox(height: 120);
        final card = c;
        // 지금 고를 수 없게 된 시술은 뺀다(스냅샷이 바뀌면)
        final pickable = {for (final p in procsOnly(card)) if (p.pickable) p.id};
        final picks = _picks.where(pickable.contains).toList();
        final procs = procsOnly(card)..sort((a, b) => a.sequence.compareTo(b.sequence));
        final docs = [...b.doctors]..sort((x, y) => (x.busy ? 1 : 0) - (y.busy ? 1 : 0));
        final toName = _to == null ? '' : _to == -1 ? '모든 의사' : docName(b, _to);
        final off = _to == null || picks.isEmpty || _sending;
        final cta = _to == null ? '의사를 선택하세요' : '$toName 호출 · ${picks.length}건';

        return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Ms.gray200))),
            child: Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
              Text('의사 호출', style: Typo.titleSm600),
              const SizedBox(width: 8),
              Flexible(
                child: Text(tablet ? '${card.room.title} · ${card.customer.name}' : card.room.title,
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.caption400.copyWith(color: Ms.gray600)),
              ),
            ]),
          ),
          Flexible(
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
              children: [
                // 「호출할 시술」 머리 + [전체 선택](pickable 만 · E2E A2)
                Row(children: [
                  Expanded(child: Text('호출할 시술', style: Typo.caption600.copyWith(color: Ms.gray700))),
                  if (pickable.isNotEmpty) _selectAll(pickable, picks.length == pickable.length),
                ]),
                const SizedBox(height: 8),
                if (pickable.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text('호출할 대기 시술이 없어요', style: Typo.body400.copyWith(color: Ms.gray600)),
                  ),
                for (final p in procs) ...[
                  _procRow(b, p, pickable.contains(p.id), picks.contains(p.id)),
                  const SizedBox(height: 8),
                ],
                const SizedBox(height: 6),
                Text('누구에게', style: Typo.caption600.copyWith(color: Ms.gray700)),
                const SizedBox(height: 8),
                _docRow(key: -1, name: '모든 의사', av: 'ALL', sub: '먼저 수락한 원장', free: null),
                for (final d in docs) ...[
                  const SizedBox(height: 8),
                  _docRow(
                    key: d.id,
                    name: d.name,
                    av: d.name.isEmpty ? '?' : d.name.characters.first,
                    sub: d.busy ? '${d.busyRoom ?? ''} 시술 중'.trim() : '비어있음',
                    free: !d.busy,
                  ),
                ],
              ],
            ),
          ),
          Container(
            padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + MediaQuery.paddingOf(context).bottom),
            decoration: const BoxDecoration(border: Border(top: BorderSide(color: Ms.gray200))),
            child: Row(children: [
              SizedBox(
                width: 96,
                child: MsButton('취소', variant: BtnVariant.outlined, color: BtnColor.gray, expand: true, onPressed: () => Navigator.of(context).pop()),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: MsButton(cta, expand: true, onPressed: off ? null : () => _send(app, card, picks, toName)),
              ),
            ]),
          ),
        ]);
      },
    );
  }

  Future<void> _send(AppState app, BoardCard c, List<int> picks, String toName) async {
    setState(() => _sending = true);
    final target = _to == -1 ? (kind: 'all', doctorId: null) : (kind: 'one', doctorId: _to);
    final label = _to == -1 ? '모든 의사 호출' : '$toName 호출';
    final ok = await app.run(() => app.api.createCall(c.visitId, picks, target), '${c.room.title} ${picks.length}개 시술 · $label');
    if (!mounted) return;
    if (ok) {
      Navigator.of(context).pop();
    } else {
      setState(() => _sending = false);
    }
  }

  Widget _selectAll(Set<int> pickable, bool all) => GestureDetector(
        key: const Key('select-all'),
        behavior: HitTestBehavior.opaque,
        onTap: () => setState(() {
          _picks
            ..clear()
            ..addAll(toggleAll(_picks, pickable));
        }),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            _check(all),
            const SizedBox(width: 6),
            Text('전체 선택', style: Typo.caption600.copyWith(color: all ? Ms.primary : Ms.gray700)),
          ]),
        ),
      );

  Widget _check(bool on) => Container(
        width: 20,
        height: 20,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: on ? Ms.primary : Ms.white,
          borderRadius: BorderRadius.circular(4),
          border: Border.all(color: on ? Ms.primary : Ms.gray400),
        ),
        child: const Text('✓', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Ms.white, height: 1)),
      );

  Widget _procRow(Board b, Procedure p, bool enabled, bool on) {
    final line = procLine(b, p);
    return Opacity(
      opacity: enabled ? 1 : 0.5,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: enabled ? () => setState(() => on ? _picks.remove(p.id) : _picks.add(p.id)) : null,
        child: Container(
          constraints: const BoxConstraints(minHeight: 48),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: on ? Ms.primary100 : enabled ? Ms.white : Ms.gray100,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: on ? Ms.primary : Ms.gray300),
          ),
          child: Row(children: [
            Container(
              width: 20,
              height: 20,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: on ? Ms.primary : Ms.white,
                borderRadius: BorderRadius.circular(4),
                border: Border.all(color: on ? Ms.primary : Ms.gray400),
              ),
              child: const Text('✓', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Ms.white, height: 1)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(p.title, style: Typo.body500.copyWith(color: enabled ? Ms.gray800 : Ms.gray600)),
                Text(line.text, style: Typo.caption400.copyWith(color: Ms.gray500)),
              ]),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _docRow({required int key, required String name, required String av, required String sub, required bool? free}) {
    final on = _to == key;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => setState(() => _to = on ? null : key),
      child: Container(
        constraints: const BoxConstraints(minHeight: 48),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: on ? Ms.primary100 : Ms.white,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: on ? Ms.primary : Ms.gray300),
        ),
        child: Row(children: [
          Container(
            width: 28,
            height: 28,
            alignment: Alignment.center,
            decoration: BoxDecoration(color: key == -1 ? Ms.gray700 : Ms.purple100, shape: BoxShape.circle),
            child: Text(av, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: key == -1 ? Ms.white : Ms.purple)),
          ),
          const SizedBox(width: 10),
          Text(name, style: Typo.body500),
          const Spacer(),
          Text(sub,
              style: free == true ? Typo.caption500.copyWith(color: Ms.primary) : Typo.caption400.copyWith(color: Ms.gray500)),
        ]),
      ),
    );
  }
}

// [전체 선택] — pickable 이 다 골라져 있으면 모두 해제, 아니면 pickable 전부(웹 카드 「전체 선택」과 같은 동작)
Set<int> toggleAll(Set<int> picks, Set<int> pickable) =>
    pickable.isNotEmpty && pickable.every(picks.contains) ? <int>{} : {...pickable};
