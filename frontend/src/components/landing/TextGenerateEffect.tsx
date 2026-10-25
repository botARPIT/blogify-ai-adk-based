import React from 'react';

interface TextGenerateEffectProps {
  words: string;
  className?: string;
  highlight?: string;
}

const TextGenerateEffect: React.FC<TextGenerateEffectProps> = ({ words, className = '', highlight }) => {
  let wordIndex = 0;
  return <span className={`text-generate ${className}`} aria-label={words.replaceAll('\n', ' ')}>
    <span aria-hidden="true">{words.split('\n').map((line, lineIndex, lines) => <React.Fragment key={`line-${lineIndex}`}>
      {line.split(/\s+/).map((word, index, lineWords) => {
        const currentIndex = wordIndex++;
        const cleanWord = word.replace(/[.,!?;:]+$/, '');
        const content = <>{cleanWord}{word.slice(cleanWord.length)}</>;
        return <React.Fragment key={`${word}-${currentIndex}`}>
          {highlight === cleanWord ? <em className="text-generate-word" style={{ animationDelay: `${currentIndex * 75}ms` }}>{content}</em> : <span className="text-generate-word" style={{ animationDelay: `${currentIndex * 75}ms` }}>{content}</span>}{index < lineWords.length - 1 ? ' ' : ''}
        </React.Fragment>;
      })}{lineIndex < lines.length - 1 && <br />}
    </React.Fragment>)}</span>
  </span>;
};

export default TextGenerateEffect;
