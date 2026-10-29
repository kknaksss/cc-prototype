// 앱 안 사람 · 방 이름 검색(SPEC-007 §10.14 「초성 검색」 · r4 처분 OQ-961 — 전달 시트 · 새 대화 · 초대 세 곳이 이 함수 하나)
// 검색어 글자마다: 한글 초성(ㄱ ~ ㅎ · 겹자음 ㄲ ㄸ ㅃ ㅆ ㅉ)이면 이름 글자의 초성과 같으면 맞음 · 그 밖의 글자는 같은 글자면 맞음 ·
// 이름 안 이어지는 자리에 맞으면 남김(「ㄱㄴ」 → 「가나다」 · 「김ㄴ」 → 「김나래」) · 대소문자 · 앞뒤 공백 무시. 새 패키지 없음
const _initials = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'];
final _initialSet = _initials.toSet();

// 한글 음절(U+AC00 ~ U+D7A3)의 초성 · 아니면 null
String? initialOf(int rune) => rune >= 0xAC00 && rune <= 0xD7A3 ? _initials[(rune - 0xAC00) ~/ 588] : null;

bool _same(int q, int n) {
  final qs = String.fromCharCode(q);
  if (_initialSet.contains(qs)) return initialOf(n) == qs || q == n;
  return q == n;
}

bool nameMatches(String name, String query) {
  final q = query.trim().toLowerCase().runes.toList();
  if (q.isEmpty) return true;
  final n = name.toLowerCase().runes.toList();
  for (var i = 0; i + q.length <= n.length; i++) {
    var ok = true;
    for (var j = 0; j < q.length && ok; j++) {
      ok = _same(q[j], n[i + j]);
    }
    if (ok) return true;
  }
  return false;
}
