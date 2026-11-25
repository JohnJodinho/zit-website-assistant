import type { Rating } from "./types";

export function shouldSubmitRating(current: Rating | null, next: -1 | 1): boolean {
  return current !== next;
}
