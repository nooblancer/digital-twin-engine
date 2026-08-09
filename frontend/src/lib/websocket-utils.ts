/**
 * Computes the exponential backoff delay for WebSocket reconnection.
 *
 * Formula: min(1000 * 2^(attempts-1), 30000)
 * - 1s initial delay
 * - 2x multiplier per attempt
 * - 30s maximum cap
 *
 * @param attempts - Number of consecutive reconnection attempts (1-based)
 * @returns Delay in milliseconds before next reconnection attempt
 */
export function computeBackoffDelay(attempts: number): number {
  return Math.min(1000 * Math.pow(2, attempts - 1), 30000);
}
