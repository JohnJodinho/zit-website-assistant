const suggestions = [
  "Which courses do you offer?",
  "How do I apply?",
  "What are the fees for a course?",
  "Tell me about your programmes",
  "How can I contact ZIT?",
];

type Props = {
  onSelect(question: string): void;
};

export function SuggestionChips({ onSelect }: Props) {
  return (
    <section className="suggestion-section" aria-labelledby="suggestion-title">
      <h2 id="suggestion-title">Try asking</h2>
      <div className="suggestion-list">
        {suggestions.map((question) => (
          <button
            className="suggestion-chip"
            key={question}
            onClick={() => onSelect(question)}
            type="button"
          >
            {question}
          </button>
        ))}
      </div>
    </section>
  );
}
