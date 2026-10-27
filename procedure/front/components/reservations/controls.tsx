'use client';

// 예약 현황 입력 컨트롤 — 브라우저 기본 select · date · time 대신 DS(medikit) 컴포넌트(E2E #2 · #9 · #23)
// select → ComboBox(size m · 36px) · date → Popover + Calendar(DatePicker 꼴) · time → ComboBox 30분 목록(medikit 에 TimePicker 없음 — 코디 답 ①)
import { useState } from 'react';
import { Calendar, CalendarIcon, ComboBox, Popover, PopoverContent, PopoverTrigger, type ComboboxOption } from '@medisolve-ai/medikit';
import { pad } from '@/lib/time';

// ComboBox 는 「선택 안 함」 을 빈 값으로 못 고른다(같은 값 다시 누름 = 풀림) — 이 값으로 받아 '' 로 돌린다
const NONE = '__none__';

export interface Opt {
  value: string;
  label: string;
  disabled?: boolean;
}

export function DsSelect({
  value,
  onChange,
  options,
  none,
  placeholder = '선택',
  disabled,
  search,
  className,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Opt[];
  none?: string; // 있으면 맨 위에 빈 값 줄(문구)
  placeholder?: string;
  disabled?: boolean;
  search?: boolean; // 목록이 길 때(국적)
  className?: string;
  ariaLabel?: string;
}) {
  const opts: ComboboxOption[] = [
    ...(none ? [{ value: NONE, label: none, keywords: [none] }] : []),
    ...options.map((o) => ({ value: o.value, label: o.label, disabled: o.disabled, keywords: [o.label, o.value] })),
  ];
  return (
    <ComboBox
      size="m"
      aria-label={ariaLabel}
      options={opts}
      value={value === '' && none ? NONE : value}
      onValueChange={(v: string) => onChange(v === NONE ? '' : v)}
      placeholder={none ?? placeholder}
      hasSearch={!!search}
      hasCheckIcon={false}
      autoInputFocus={!!search}
      disabled={disabled}
      className={'bg-ms-white px-[10px] ' + (className ?? '')}
      classNames={{ optionList: 'max-h-[240px] overflow-y-auto' }}
    />
  );
}

// YYYY-MM-DD ↔ Date(브라우저 날짜 — 시각 없는 값)
export function ymdToDate(v: string | null | undefined): Date | undefined {
  const m = v ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(v) : null;
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : undefined;
}
export const dateToYmd = (d: Date) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());

// DatePicker 와 같은 꼴(높이 36 · 반경 8 · 달력 아이콘) — 생년월일은 연도 이동(Calendar yearNavigation)이 필요해 Popover + Calendar 로 짠다
export function DsDate({
  value,
  onChange,
  placeholder = '날짜 선택',
  disabled,
  birth,
  tone,
  className,
}: {
  value: string; // YYYY-MM-DD 또는 ''
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
  birth?: boolean; // 생년월일 — 연도 이동 · 오늘 뒤 막음
  tone?: string; // 배경 · 테두리 클래스(기본 흰 바탕 · 회색 테두리)
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const sel = ymdToDate(value);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          className={
            'inline-flex h-[36px] w-full items-center justify-between gap-[6px] rounded-[8px] border px-[12px] text-typo-body-400 ' +
            (open ? 'border-primary bg-ms-white ' : (tone ?? 'border-ms-gray-300 bg-ms-white') + ' ') +
            (sel && !disabled ? 'text-ms-black ' : 'text-ms-gray-600 ') +
            (disabled ? 'cursor-not-allowed ' : 'cursor-pointer ') +
            (className ?? '')
          }
          style={{ fontFamily: 'inherit', fontVariantNumeric: 'tabular-nums' }}
        >
          <span>{value || placeholder}</span>
          <CalendarIcon size="sm" className="shrink-0 text-ms-gray-600" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="p-[16px]" align="start">
        <Calendar
          mode="single"
          selected={sel}
          defaultMonth={sel ?? (birth ? new Date(1990, 0, 1) : new Date())}
          yearNavigation={birth}
          disabled={birth ? { after: new Date() } : undefined}
          onSelect={(d) => {
            onChange(d ? dateToYmd(d) : '');
            if (d) setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

// 시각 목록 HH:MM — from ~ to(분) step 간격
export function timeOptions(from = 6 * 60, to = 22 * 60, step = 30): Opt[] {
  const out: Opt[] = [];
  for (let m = from; m <= to; m += step) {
    const v = pad(Math.floor(m / 60)) + ':' + pad(m % 60);
    out.push({ value: v, label: v });
  }
  return out;
}

// KOS snsInfo.snsType(E2E #23 · reservation-read-report §3.1) — 값은 KOS enum · 화면은 한글
export const SNS_LABEL: Record<string, string> = {
  kakaotalk: '카카오톡',
  line: '라인',
  instagram: '인스타그램',
  whatsapp: '왓츠앱',
  wechat: '위챗',
  etc: '기타',
};
export const SNS_TYPES = ['kakaotalk', 'line', 'instagram', 'whatsapp', 'wechat', 'etc'];
export const snsOptions = (types?: string[] | null): Opt[] => (types?.length ? types : SNS_TYPES).map((t) => ({ value: t, label: SNS_LABEL[t] ?? t }));
