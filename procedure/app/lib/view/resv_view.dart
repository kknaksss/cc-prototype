// 예약 현황 표시 계산 — 웹 reservations/view.tsx 의 시각 · 금액 · 국가 · 정원 글자(SPEC-005 §5 · §6). 규칙은 back 값
import '../model/reservation.dart';
import 'time.dart';

String _pad(int n) => n.toString().padLeft(2, '0');

// ISO → 그날 KST 분(0 ~ 1440)
int? kstMin(String? iso) {
  final t = toMs(iso);
  if (t == null) return null;
  final d = DateTime.fromMillisecondsSinceEpoch(t, isUtc: true).add(const Duration(hours: 9));
  return d.hour * 60 + d.minute;
}

int hmToMin(String v) {
  final p = v.split(':');
  return (int.tryParse(p[0]) ?? 0) * 60 + (p.length > 1 ? int.tryParse(p[1]) ?? 0 : 0);
}

String minToHm(int m) => '${_pad(m ~/ 60)}:${_pad(m % 60)}';

// YYYY-MM-DD ± n 일
String shiftDate(String date, int n) {
  final p = date.split('-').map(int.parse).toList();
  final d = DateTime.utc(p[0], p[1], p[2] + n);
  return '${d.year}-${_pad(d.month)}-${_pad(d.day)}';
}

const _wd = ['월', '화', '수', '목', '금', '토', '일'];

// 「2026. 10. 26. (월)」
String dateTitle(String date) {
  final p = date.split('-').map(int.parse).toList();
  final d = DateTime.utc(p[0], p[1], p[2]);
  return '${p[0]}. ${p[1]}. ${p[2]}. (${_wd[d.weekday - 1]})';
}

// 오늘(KST) YYYY-MM-DD
String todayKst([DateTime? now]) {
  final d = (now ?? DateTime.now()).toUtc().add(const Duration(hours: 9));
  return '${d.year}-${_pad(d.month)}-${_pad(d.day)}';
}

// 칸 머리 정원 — 「{구역} {N}명」 을 · 로 · 없음 = 「- 명」
String capacityText(ResvColumn col, List<Zone> zones) {
  if (col.capacities.isEmpty) return '- 명';
  int order(int id) => zones.where((z) => z.zoneId == id).firstOrNull?.order ?? 0;
  String title(int id) => zones.where((z) => z.zoneId == id).firstOrNull?.title ?? '';
  final caps = [...col.capacities]..sort((a, b) => order(a.$1).compareTo(order(b.$1)));
  return caps.map((c) => [title(c.$1), '${c.$2}명'].where((x) => x.isNotEmpty).join(' ')).join(' · ');
}

// 금액 — KRW 는 「₩」 + 천 단위 쉼표 · 모르면 「-」
String money(num? v, String? currency) {
  if (v == null) return '-';
  final neg = v < 0;
  final s = v.abs().round().toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => ',');
  final n = (neg ? '-' : '') + s;
  return currency == null || currency.isEmpty || currency == 'KRW' ? '₩$n' : '$n $currency';
}

String moneyOf(Amount? a, bool total) => a == null ? '-' : money(total ? a.total : a.paid, a.currency);

// 국가 이름(웹 NATIONS 표 그대로) — 표에 없으면 코드
const nations = {
  'KR': '한국',
  'CN': '중국',
  'TW': '대만',
  'HK': '홍콩',
  'MO': '마카오',
  'JP': '일본',
  'US': '미국',
  'CA': '캐나다',
  'GB': '영국',
  'AU': '호주',
  'NZ': '뉴질랜드',
  'IE': '아일랜드',
  'SG': '싱가포르',
  'MY': '말레이시아',
  'TH': '태국',
  'VN': '베트남',
  'PH': '필리핀',
  'ID': '인도네시아',
  'MN': '몽골',
  'KZ': '카자흐스탄',
  'UZ': '우즈베키스탄',
  'KH': '캄보디아',
  'MM': '미얀마',
  'LA': '라오스',
  'BN': '브루나이',
  'IN': '인도',
  'NP': '네팔',
  'BD': '방글라데시',
  'PK': '파키스탄',
  'LK': '스리랑카',
  'AE': '아랍에미리트',
  'SA': '사우디아라비아',
  'QA': '카타르',
  'KW': '쿠웨이트',
  'IL': '이스라엘',
  'TR': '튀르키예',
  'RU': '러시아',
  'UA': '우크라이나',
  'DE': '독일',
  'FR': '프랑스',
  'IT': '이탈리아',
  'ES': '스페인',
  'PT': '포르투갈',
  'NL': '네덜란드',
  'BE': '벨기에',
  'CH': '스위스',
  'AT': '오스트리아',
  'SE': '스웨덴',
  'NO': '노르웨이',
  'DK': '덴마크',
  'FI': '핀란드',
  'PL': '폴란드',
  'CZ': '체코',
  'HU': '헝가리',
  'GR': '그리스',
  'RO': '루마니아',
  'MX': '멕시코',
  'BR': '브라질',
  'AR': '아르헨티나',
  'CL': '칠레',
  'CO': '콜롬비아',
  'PE': '페루',
  'EG': '이집트',
  'ZA': '남아프리카공화국',
  'NG': '나이지리아',
  'KE': '케냐',
  'MA': '모로코',
};
String nationName(String? code) => code == null || code.isEmpty ? '' : nations[code.toUpperCase()] ?? code;

// 국기 — 웹은 flag-icons 그림 · 앱은 iOS 국기 그림 글자(지역 표시 문자 둘). 표에 없는 코드 = null(회색 상자 + 코드)
String? flagEmoji(String? code) {
  final c = (code ?? '').toUpperCase();
  if (!nations.containsKey(c)) return null;
  return String.fromCharCodes(c.codeUnits.map((u) => 0x1F1E6 + u - 0x41));
}

// 폰 시간대 목록(§6.10 · 시안 M:58-108) — 30분 단위 · 그 시간대에 시작하는 카드 · 축 06:00 ~ 22:00
class SlotRow {
  final int min;
  final List<ResvCard> cards;
  const SlotRow(this.min, this.cards);
  String get label => minToHm(min);
}

List<SlotRow> slotRows(ResvBoard b, {int? groupFilter, bool filterOn = false, int step = 30}) {
  final start = hmToMin(b.axis?.start ?? '06:00');
  final end = hmToMin(b.axis?.end ?? '22:00');
  final cards = b.cards.where((c) => !filterOn || c.groupId == groupFilter).toList()
    ..sort((x, y) => (kstMin(x.start) ?? 0).compareTo(kstMin(y.start) ?? 0));
  return [
    for (var m = start; m < end; m += step)
      SlotRow(m, cards.where((c) {
        final s = kstMin(c.start);
        return s != null && s >= m && s < m + step;
      }).toList()),
  ];
}

// 지금 시간대(오늘만) — 그 줄로 스크롤 · 파란 바탕
int? nowSlot(ResvBoard b, {int step = 30}) {
  if (!b.isToday) return null;
  final m = kstMin(b.now);
  return m == null ? null : m - m % step;
}
