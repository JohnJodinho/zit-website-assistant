import { ThumbsDown, ThumbsUp } from "lucide-react";
import type { Rating } from "../state/types";

type Props = {
  rating: Rating | null;
  onRate(rating: -1 | 1): void;
};

export function FeedbackButtons({ rating, onRate }: Props) {
  return (
    <div className="feedback-actions" aria-label="Rate this response">
      <button
        aria-label="Helpful response"
        aria-pressed={rating === 1}
        className="icon-button"
        onClick={() => onRate(1)}
        type="button"
      >
        <ThumbsUp aria-hidden="true" size={18} />
      </button>
      <button
        aria-label="Not helpful response"
        aria-pressed={rating === -1}
        className="icon-button"
        onClick={() => onRate(-1)}
        type="button"
      >
        <ThumbsDown aria-hidden="true" size={18} />
      </button>
    </div>
  );
}
