import { useCallback, useRef, useState } from "react";

/**
 * Online state for a page that polls the Pi.
 *
 * One slow or lost answer is normal on a busy Pi or Wi-Fi; only `misses`
 * failed polls in a row turn the state offline, so the UI does not flash
 * "Afventer" and empty its panels for a single miss.
 */
export function usePollHealth(misses = 2): [boolean, (ok: boolean) => void] {
  const [online, setOnline] = useState(false);
  const failed = useRef(0);
  const report = useCallback((ok: boolean) => {
    failed.current = ok ? 0 : failed.current + 1;
    if (ok) setOnline(true);
    else if (failed.current >= misses) setOnline(false);
  }, [misses]);
  return [online, report];
}

/**
 * Wraps a poll so a new round is skipped while the previous one is still
 * waiting. Without it a slow Pi gets an ever longer queue of requests.
 */
export function useSinglePoll(poll: () => Promise<void>): () => Promise<void> {
  const running = useRef(false);
  return useCallback(async () => {
    if (running.current) return;
    running.current = true;
    try { await poll(); } finally { running.current = false; }
  }, [poll]);
}
