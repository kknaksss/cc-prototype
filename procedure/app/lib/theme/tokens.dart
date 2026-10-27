// Ceramique 토큰 — 원천 = procedure/front/app/styles/ceramique-theme.css + medikit 1.4.0 base.css · tailwind 글자 크기(SPEC-004 §6.6)
import 'package:flutter/material.dart';

abstract final class Ms {
  // [data-product="ceramique"]
  static const primary = Color(0xFF2498BD);
  static const primary50 = Color(0xFFE9F5F8);
  static const primary100 = Color(0xFFE9F5F8);
  static const primary300 = Color(0xFFD3F4FE);
  static const primary500 = Color(0xFFB2E3F2);
  static const primaryHover = Color(0xFF1D7F9E);

  static const white = Color(0xFFFFFFFF);
  static const black = Color(0xFF000000);
  static const gray100 = Color(0xFFFBFBFB);
  static const gray200 = Color(0xFFF3F3F3);
  static const gray300 = Color(0xFFE3E3E3);
  static const gray400 = Color(0xFFD6D6D6);
  static const gray500 = Color(0xFFCFCFCF);
  static const gray600 = Color(0xFF9F9F9F);
  static const gray700 = Color(0xFF6E6E6E);
  static const gray800 = Color(0xFF3E3E3E);

  static const red = Color(0xFFFF4E51);
  static const red100 = Color(0xFFFFEFEF);
  static const red300 = Color(0xFFFFE1E1);
  static const red500 = Color(0xFFFFC4C5);
  static const yellow = Color(0xFFFD9400);
  static const yellow100 = Color(0xFFFFF7EC);
  static const yellow300 = Color(0xFFFFE4C0);
  static const purple = Color(0xFFAC47FF);
  static const purple100 = Color(0xFFF8F0FF);
  static const purple500 = Color(0xFFBF71FF);

  // 상담(cons) — 웹 예약 현황 2계층 색(procedure/front ceramique-theme · SPEC-005 §5.1)
  static const cons = Color(0xFF15803D);
  static const cons100 = Color(0xFFE7F4EC);

  static const dim = Color(0x52000000); // rgba(0,0,0,0.32) — 시트 · 드로어 뒤
}

// medikit 글자 단계(tailwind typo-*) — 크기 · 굵기 · 줄높이
abstract final class Typo {
  static TextStyle _t(double size, FontWeight w, double h) =>
      TextStyle(fontFamily: 'Pretendard', fontSize: size, fontWeight: w, height: h, color: Ms.gray800, letterSpacing: 0);

  static final titleMd600 = _t(20, FontWeight.w600, 1.4);
  static final titleSm600 = _t(18, FontWeight.w600, 1.5);
  static final headingMd600 = _t(16, FontWeight.w600, 1.5);
  static final headingMd500 = _t(16, FontWeight.w500, 1.5);
  static final headingMd400 = _t(16, FontWeight.w400, 1.5);
  static final headingSm500 = _t(14, FontWeight.w500, 1.5);
  static final headingSm400 = _t(14, FontWeight.w400, 1.5);
  static final body600 = _t(14, FontWeight.w600, 1.6);
  static final body500 = _t(14, FontWeight.w500, 1.6);
  static final body400 = _t(14, FontWeight.w400, 1.6);
  static final caption600 = _t(12, FontWeight.w600, 1.3);
  static final caption500 = _t(12, FontWeight.w500, 1.3);
  static final caption400 = _t(12, FontWeight.w400, 1.3);
}

// 숫자 고정폭(font-variant-numeric: tabular-nums)
const tabular = [FontFeature.tabularFigures()];

ThemeData ceramiqueTheme() {
  final base = ThemeData(
    useMaterial3: true,
    fontFamily: 'Pretendard',
    colorScheme: ColorScheme.fromSeed(seedColor: Ms.primary, primary: Ms.primary, surface: Ms.white),
    scaffoldBackgroundColor: Ms.gray100,
    splashFactory: NoSplash.splashFactory,
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(fontFamily: 'Pretendard', bodyColor: Ms.gray800, displayColor: Ms.gray800),
    dividerColor: Ms.gray200,
  );
}

// 반응형 글자 배율(실기기 E2E T4) — 폰(짧은 변 < 600) = 1 · 태블릿 = 짧은 변 / 700(1.15 ~ 1.3).
// 아이패드 11"(834) ≈ 1.19 · 13"(1032) = 1.3 · mini(744) = 1.15. Typo · 숫자 타이머 등 모든 Text 에 MediaQuery.textScaler 로 걸린다
double uiScale(Size size) {
  final short = size.shortestSide;
  if (short < 600) return 1.0;
  return (short / 700).clamp(1.15, 1.3);
}
