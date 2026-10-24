/** 75 → "1:15", -12 → "-0:12". */
export function mmss(seconds: number): string {
  const sign = seconds < 0 ? '-' : ''
  const s = Math.floor(Math.abs(seconds))
  return `${sign}${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export const LANG_LABEL: Record<string, string> = { id: 'Indonesian', zh: 'Mandarin', en: 'English' }
