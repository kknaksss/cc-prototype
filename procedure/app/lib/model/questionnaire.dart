// 문진(SPEC-004 §6.15) — GET /api/questionnaires/{reservationId} 응답 · KOS 양식(pages[] · translsMap) 그대로.
// 질문 = id(또는 questionId) · title · answers[] / 답 = id · title · inputType(CHECK_BOX · SELECT_BOX · INPUT_BOX) · isSubText · translsMap
// 보여 주는 글자만 번역 · 제출 title · parentQuestionTitle 은 원문(한국어 — KOS 와 같게 · app-kos-report §4)
import 'board.dart' show Json;

Json _o(Object? v) => v is Map ? v.cast<String, dynamic>() : const {};
List<Json> _l(Object? v) => v is List ? [for (final e in v) if (e is Map) e.cast<String, dynamic>()] : const [];

// translsMap.<field>.translation[lang] — 없으면 원문
String trOf(Json item, String field, String lang, String fallback) {
  final t = _o(_o(_o(item['translsMap'])[field])['translation'])[lang];
  return t is String && t.trim().isNotEmpty ? t : fallback;
}

// 약관 번역 키는 ja · en · zh(간체 · 번체 둘 다 zh) · 그 밖 원문(§6.15 ⑤)
String agreementLang(String lang) => switch (lang) {
      'ja' => 'ja',
      'en' => 'en',
      'zh-Hans' || 'zh-Hant' => 'zh',
      _ => '',
    };

class QAnswer {
  final Json raw;
  const QAnswer(this.raw);
  String get id => '${raw['id'] ?? ''}';
  String get title => '${raw['title'] ?? ''}';
  String get inputType => '${raw['inputType'] ?? 'CHECK_BOX'}';
  bool get isSubText => raw['isSubText'] == true;
  bool get isInput => inputType == 'INPUT_BOX';
  String label(String lang) => trOf(raw, 'title', lang, title);
}

class QQuestion {
  final Json raw;
  final List<QAnswer> answers;
  QQuestion(this.raw) : answers = [for (final a in _l(raw['answers'])) QAnswer(a)];
  String get id => '${raw['id'] ?? raw['questionId'] ?? ''}';
  String get title => '${raw['title'] ?? ''}';
  String label(String lang) => trOf(raw, 'title', lang, title);
  // 하나만 고르기 = 답이 모두 SELECT_BOX · 글 입력 = INPUT_BOX 하나
  bool get single => answers.isNotEmpty && answers.every((a) => a.inputType.endsWith('SELECT_BOX'));
  bool get input => answers.length == 1 && answers.first.isInput;
  // 필수 표시 = KOS 값(있으면)
  bool get required => raw['required'] == true || raw['isRequired'] == true || raw['essential'] == true;
}

class QPage {
  final Json raw;
  final List<QQuestion> questions;
  QPage(this.raw) : questions = [for (final q in _l(raw['questions'])) QQuestion(q)];
  String label(String lang) => trOf(raw, 'title', lang, '${raw['title'] ?? ''}');
}

class QForm {
  final int reservationId;
  final String customerName;
  final String language;
  final List<String> options;
  final List<QPage> pages;
  final List<Json> agreements;
  final Json prefill;
  final bool todaySubmitted;
  const QForm({
    required this.reservationId,
    required this.customerName,
    required this.language,
    required this.options,
    required this.pages,
    required this.agreements,
    required this.prefill,
    this.todaySubmitted = false,
  });

  factory QForm.fromJson(Json j) {
    final l = _o(j['language']);
    final opts = [for (final x in (l['options'] is List ? l['options'] as List : const [])) '$x'];
    return QForm(
      reservationId: (j['reservationId'] as num?)?.toInt() ?? 0,
      customerName: '${j['customerName'] ?? ''}',
      language: '${l['code'] ?? 'en'}',
      options: opts.isEmpty ? const ['ko', 'ja', 'zh-Hans', 'zh-Hant', 'en', 'id'] : opts,
      pages: [for (final p in _l(_o(j['form'])['pages'])) QPage(p)].where((p) => p.questions.isNotEmpty).toList(),
      agreements: _l(j['agreements']),
      prefill: _o(j['prefill']),
      todaySubmitted: j['todaySubmitted'] == true,
    );
  }
}

// 고객 입력 — 질문 id → 고른 답 id 들 · 답 id → 자유 글(subText · inputText)
class QAnswers {
  final Map<String, Set<String>> picked = {};
  final Map<String, String> text = {};

  void toggle(QQuestion q, QAnswer a) {
    final s = picked.putIfAbsent(q.id, () => <String>{});
    if (q.single) {
      final had = s.contains(a.id);
      s.clear();
      if (!had) s.add(a.id);
    } else {
      s.contains(a.id) ? s.remove(a.id) : s.add(a.id);
    }
  }

  bool isPicked(QQuestion q, QAnswer a) => picked[q.id]?.contains(a.id) ?? false;

  // 그 쪽 필수 질문이 다 답했나
  bool pageDone(QPage p) => p.questions.where((q) => q.required).every((q) => q.input
      ? (text[q.answers.first.id] ?? '').trim().isNotEmpty
      : (picked[q.id]?.isNotEmpty ?? false));

  // 제출 answers[] — 고른 선택지 한 줄씩(+ INPUT_BOX 글) · 키 7개 · title 은 원문
  List<Json> toJson(List<QPage> pages) => [
        for (final p in pages)
          for (final q in p.questions)
            for (final a in q.answers)
              if (a.isInput ? (text[a.id] ?? '').trim().isNotEmpty : isPicked(q, a))
                {
                  'parentQuestionId': q.raw['id'] ?? q.raw['questionId'],
                  'parentQuestionTitle': q.title,
                  'id': a.raw['id'],
                  'title': a.title,
                  'inputType': a.inputType,
                  'inputText': a.isInput ? text[a.id]!.trim() : '',
                  'subText': !a.isInput && a.isSubText ? (text[a.id] ?? '').trim() : '',
                },
      ];
}
