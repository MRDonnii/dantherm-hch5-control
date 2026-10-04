/** T2AH is downstream of the afterheater, so it only describes the exchanger while heating is confirmed off. */
export function t2ahRecoveryPercent(
  outdoor: number | null,
  extract: number | null,
  t2ah: number | null,
  afterheatKnown: boolean,
  afterheatActive: boolean,
  bypassActive: boolean,
): number | null {
  if (!afterheatKnown || afterheatActive || bypassActive || outdoor === null || extract === null || t2ah === null) return null;
  const span = extract - outdoor;
  if (span < 3) return null;
  const value = (t2ah - outdoor) / span * 100;
  return value >= 0 && value <= 100 ? Math.round(value) : null;
}
