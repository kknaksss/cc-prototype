// 수락(SPEC-004 §3.4 · §6.2 · §6.3 #2)
//   의사 = 자기 자신으로(본문 doctorId 없음)
//   관리자(A-15) = 웹 호출 탭과 같은 규칙 — 전체 호출은 원장 고르기 · 지정 호출은 지정 원장으로(원장 고정)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../model/board.dart';
import '../theme/tokens.dart';
import '../view/view.dart';
import 'ui.dart';
import 'sheet.dart';

// 관리자가 이 호출을 수락할 때 쓸 원장 — 지정 호출이면 그 원장, 전체 호출이면 null(골라야 함)
int? fixedDoctor(OpenCall k) => k.kind == 'one' ? k.targetDoctorId : null;

// 수락 요청의 doctorId — 의사 = null(자기 자신) · 관리자 = 고른/지정 원장
int? acceptDoctorId(Me me, OpenCall k, {int? picked}) => me.admin ? (picked ?? fixedDoctor(k)) : null;

// [수락] 누름 — 관리자 + 전체 호출이면 원장 고르기 시트
Future<void> acceptCall(BuildContext context, Board b, BoardCard c, OpenCall k) async {
  final app = AppScope.read(context);
  final me = app.me;
  if (me.admin && fixedDoctor(k) == null) {
    await pickDoctorToAccept(context, b, c, k);
    return;
  }
  final doctorId = acceptDoctorId(me, k);
  final who = doctorId == null ? '' : '${docName(b, doctorId)} ';
  await app.run(() => app.api.accept(k.callId, doctorId: doctorId), '${c.room.title} $who수락');
}

// 관리자 · 전체 호출 — 원장 하나를 고르고 [<원장> 수락 · N건]
Future<void> pickDoctorToAccept(BuildContext context, Board b, BoardCard c, OpenCall k) {
  final app = AppScope.read(context);
  return showAppSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Ms.white,
    barrierColor: Ms.dim,
    constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.8, maxWidth: 560),
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (_) => AppScope(state: app, child: _DoctorPicker(board: b, card: c, call: k)),
  );
}

class _DoctorPicker extends StatefulWidget {
  final Board board;
  final BoardCard card;
  final OpenCall call;
  const _DoctorPicker({required this.board, required this.card, required this.call});
  @override
  State<_DoctorPicker> createState() => _DoctorPickerState();
}

class _DoctorPickerState extends State<_DoctorPicker> {
  int? _pick;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final b = widget.board, c = widget.card, k = widget.call;
    final n = k.procedures.length;
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Container(
        padding: const EdgeInsets.all(16),
        decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Ms.gray200))),
        child: Text('누구로 수락할까요 · ${c.room.title}', style: Typo.titleSm600),
      ),
      Flexible(
        child: ListView(shrinkWrap: true, padding: const EdgeInsets.fromLTRB(16, 12, 16, 12), children: [
          for (final d in doctorsFreeFirst(b))
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => setState(() => _pick = _pick == d.id ? null : d.id),
                child: Container(
                  constraints: const BoxConstraints(minHeight: 48),
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: _pick == d.id ? Ms.primary100 : Ms.white,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: _pick == d.id ? Ms.primary : Ms.gray300),
                  ),
                  child: Row(children: [
                    Expanded(child: Text(d.name, style: Typo.body500)),
                    Text(d.busy ? '${d.busyRoom ?? ''} 시술 중'.trim() : '비어있음',
                        style: d.busy ? Typo.caption400.copyWith(color: Ms.gray500) : Typo.caption500.copyWith(color: Ms.primary)),
                  ]),
                ),
              ),
            ),
        ]),
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
            child: MsButton(
              _pick == null ? '원장을 선택하세요' : '${docName(b, _pick)} 수락 · $n건',
              expand: true,
              onPressed: _pick == null
                  ? null
                  : () {
                      final id = _pick!;
                      Navigator.of(context).pop();
                      app.run(() => app.api.accept(k.callId, doctorId: id), '${c.room.title} ${docName(b, id)} 수락');
                    },
            ),
          ),
        ]),
      ),
    ]);
  }
}
