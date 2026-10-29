// 시술 줄 되돌리기(SPEC-004 §6.3 #4 · SPEC-003 §5.13 · D7-65) — 아이콘(진행 줄 [종료] 왼쪽 · 완료 줄 「완료」 칩 왼쪽) →
// 바로 확인 시트(앱엔 호버 없음) · [시작] · [종료] 성공 토스트 [되돌리기]. 켜짐은 스냅샷 canUndoStart · canUndoFinish 만
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../model/board.dart';
import '../screens/board_screen.dart' show isTablet;
import '../theme/tokens.dart';
import 'ui.dart';
import 'sheet.dart';

enum UndoKind { start, finish }

// 웹 UNDO_TITLE · UNDONE 과 같은 글자
const undoTitle = {UndoKind.start: '시술 대기로 되돌리겠습니까?', UndoKind.finish: '시술 중으로 되돌리겠습니까?'};
const undoneText = {UndoKind.start: ' 시술 대기로 되돌림', UndoKind.finish: ' 시술 중으로 되돌림'};

Future<void> runUndo(AppState app, BoardCard c, Procedure p, UndoKind k) => app.run(
    () => k == UndoKind.start ? app.api.undoStart(p.id) : app.api.undoFinish(p.id), '${c.room.title} · ${p.title}${undoneText[k]}');

// [시작] · [종료] — 성공 토스트에 [되돌리기](웹 run(…, undoOf) 와 같음)
Future<void> runStart(AppState app, BoardCard c, Procedure p) => app.run(() => app.api.startProcedure(p.id), '${c.room.title} · ${p.title} 시작',
    '되돌리기', () => runUndo(app, c, p, UndoKind.start));
Future<void> runFinish(AppState app, BoardCard c, Procedure p) => app.run(() => app.api.finishProcedure(p.id), '${c.room.title} · ${p.title} 종료',
    '되돌리기', () => runUndo(app, c, p, UndoKind.finish));

// 확인 시트 — 폰 = 바텀 시트 · 태블릿 = 가운데. [취소] · [되돌리기]
Future<void> confirmUndo(BuildContext context, BoardCard c, Procedure p, UndoKind k) async {
  final app = AppScope.read(context);
  Widget body(BuildContext ctx) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 20),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(undoTitle[k]!, style: Typo.titleSm600),
          const SizedBox(height: 6),
          Text('${c.room.title} · ${p.title}', style: Typo.body400.copyWith(color: Ms.gray700)),
          const SizedBox(height: 20),
          Row(children: [
            Expanded(
                child: MsButton('취소',
                    variant: BtnVariant.outlined, color: BtnColor.gray, size: BtnSize.lg, expand: true, onPressed: () => Navigator.of(ctx).pop(false))),
            const SizedBox(width: 10),
            Expanded(child: MsButton('되돌리기', size: BtnSize.lg, expand: true, onPressed: () => Navigator.of(ctx).pop(true))),
          ]),
        ]),
      );
  final bool? ok;
  if (isTablet(context)) {
    ok = await showDialog<bool>(
      context: context,
      barrierColor: Ms.dim,
      builder: (ctx) => Dialog(
        backgroundColor: Ms.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 440), child: body(ctx)),
      ),
    );
  } else {
    ok = await showAppSheet<bool>(
      context: context,
      backgroundColor: Ms.white,
      barrierColor: Ms.dim,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => SafeArea(top: false, child: Column(mainAxisSize: MainAxisSize.min, children: [const SheetHandle(), body(ctx)])),
    );
  }
  if (ok == true) await runUndo(app, c, p, k);
}

// 26×26 반시계 화살표 아이콘(웹 UndoIcon) — 테두리 없음 · gray-500
class UndoIcon extends StatelessWidget {
  final VoidCallback onTap;
  const UndoIcon({super.key, required this.onTap});

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: '되돌리기',
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onTap,
          child: const SizedBox(width: 36, height: 36, child: Icon(Icons.undo_rounded, size: 22, color: Ms.gray600)),
        ),
      );
}
