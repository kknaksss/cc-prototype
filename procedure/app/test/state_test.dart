// 2계층 표(SPEC-004 §6.9 · §8.7) — 웹 reservations/view.tsx · procedures/view.ts 와 같은 입력 → 같은 글자 · 색 이름
import 'package:flutter_test/flutter_test.dart';
import 'package:procedure_app/theme/tokens.dart';
import 'package:procedure_app/view/state.dart';
import 'package:procedure_app/widgets/ui.dart';

void main() {
  test('stateText — 「주 · 부」 꼴 · 부상태 없으면 주만', () {
    expect(stateText(ResvMain.consultation, ResvSub.waiting), '상담 · 대기');
    expect(stateText(ResvMain.procedure, ResvSub.doing), '시술 · 진행');
    expect(stateText(ResvMain.reserved, null), '예약');
    expect(stateText(ResvMain.noshow, null), '부도');
  });

  test('phaseStyle — 대기 = 100 + 그 색 · 진행 = 채움 + 흰 · 완료 = gray-100 + gray-500', () {
    final w = phaseStyle(ResvMain.consultation, Phase.waiting);
    expect((w.chipBg, w.chipFg), (Ms.cons100, Ms.cons));
    expect((w.dotFill, w.dotBorder), (Ms.white, Ms.cons)); // ○
    final d = phaseStyle(ResvMain.procedure, Phase.doing);
    expect((d.chipBg, d.chipFg), (Ms.primary, Ms.white));
    final done = phaseStyle(ResvMain.reception, Phase.done);
    expect((done.chipBg, done.chipFg), (Ms.gray100, Ms.gray500));
    final home = phaseStyle(ResvMain.home, Phase.waiting); // 귀가 대기 칩 = gray-200 + gray-700
    expect((home.chipBg, home.chipFg), (Ms.gray200, Ms.gray700));
  });

  test('headOf · barOf — 귀가 대기 gray-600 / 완료 gray-400(머리) · gray-300(막대) · 부도 외곽선', () {
    expect(headOf(ResvMain.home, ResvSub.waiting).bg, Ms.gray600);
    expect(headOf(ResvMain.home, ResvSub.done).bg, Ms.gray400);
    expect(headOf(ResvMain.home, ResvSub.done).title, '귀가 완료');
    expect(headOf(ResvMain.reception, null).title, '접수 완료');
    expect(headOf(ResvMain.consultation, null).title, '상담 대기');
    expect(headOf(ResvMain.noshow, null).outline, Ms.red);
    expect(barOf(ResvMain.home, ResvSub.done).color, Ms.gray300);
    expect(barOf(ResvMain.reserved, null).color, Ms.purple);
  });

  test('범례 7 · 시술 현황 매핑(웹 STATE_2 · procChip)', () {
    expect(legend.map((l) => mainName[l.main]), ['예약', '접수', '상담', '시술', '귀가', '취소', '부도']);
    expect(visitBadge('waiting').text, '시술 · 대기');
    expect(visitBadge('home').text, '귀가 · 대기');
    expect(procChip('done').text, '완료');
    expect((procChip('done').bg, procChip('done').fg), (Ms.gray100, Ms.gray500));
    expect(procChip('wait').text, '대기');
  });

  test('토스트 [되돌리기] — 버튼 있으면 누를 수 있고 누르면 닫고 실행', () {
    final t = Toaster();
    var n = 0;
    t.show('A-룸1 · 필러 시작', action: '되돌리기', onAction: () => n++);
    expect(t.action, '되돌리기');
    t.tapAction();
    expect(n, 1);
    expect(t.text, isNull);
    t.show('그냥 토스트', action: '되돌리기'); // onAction 없으면 버튼 없음
    expect(t.action, isNull);
    t.dispose();
  });
}
