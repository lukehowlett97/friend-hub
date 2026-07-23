import React, { useState } from 'react';
import './TagChipInput.css';

/**
 * TagChipInput - A reusable component for editing tags with a chip interface.
 * 
 * Props:
 *   - value: string (comma or space separated tags, or from TagChipInput.parse())
 *   - onChange: function(newValue) called when tags change
 *   - onSubmit: optional function(tags) called when user submits (enter key or button)
 *   - placeholder: string for the input field
 *   - disabled: boolean
 *   - allowFreeform: boolean (allow any tag, default: true)
 *   - maxTags: number (default: 8)
 *   - suggestedTags: string[] (optional list of suggested tags to show as quick-add buttons)
 */
export default function TagChipInput({
  value = '',
  onChange = () => {},
  onSubmit = null,
  placeholder = 'Add tags...',
  disabled = false,
  allowFreeform = true,
  maxTags = 8,
  suggestedTags = [],
}) {
  const [inputValue, setInputValue] = useState('');

  // Parse comma/space-separated string into array of tags
  const parseTagString = (str) => {
    return str
      .split(/[,\s]+/)
      .map((tag) => tag.trim().toLowerCase().replace(/^#/, ''))
      .filter(Boolean);
  };

  // Current tags from value prop
  const currentTags = parseTagString(value);

  const handleInputChange = (e) => {
    setInputValue(e.target.value);
  };

  const handleAddTag = (tag = null) => {
    const tagToAdd = (tag || inputValue).trim().toLowerCase().replace(/^#/, '');
    
    if (!tagToAdd || !allowFreeform) return;
    if (currentTags.includes(tagToAdd)) return;
    if (currentTags.length >= maxTags) return;

    const newTags = [...currentTags, tagToAdd];
    const newValue = newTags.join(', ');
    
    onChange(newValue);
    setInputValue('');
  };

  const handleRemoveTag = (tagToRemove) => {
    const newTags = currentTags.filter((tag) => tag !== tagToRemove);
    onChange(newTags.join(', '));
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddTag();
      if (onSubmit) {
        onSubmit(currentTags);
      }
    } else if (e.key === ',') {
      e.preventDefault();
      handleAddTag();
    }
  };

  const handleSubmitClick = () => {
    handleAddTag();
    if (onSubmit) {
      onSubmit(currentTags);
    }
  };

  return (
    <div className="tag-chip-input">
      <div className="tag-chip-display">
        {currentTags.map((tag) => (
          <span key={tag} className="tag-chip">
            {tag}
            {!disabled && (
              <button
                type="button"
                className="tag-chip-remove"
                onClick={() => handleRemoveTag(tag)}
                aria-label={`Remove tag: ${tag}`}
              >
                ×
              </button>
            )}
          </span>
        ))}
      </div>

      <input
        className="tag-chip-input-field"
        type="text"
        value={inputValue}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled || currentTags.length >= maxTags}
      />

      {suggestedTags.length > 0 && (
        <div className="tag-chip-suggestions">
          {suggestedTags.map((tag) => {
            const isSelected = currentTags.includes(tag);
            const isMaxed = currentTags.length >= maxTags;
            return (
              <button
                key={tag}
                type="button"
                className={`tag-chip-suggestion ${isSelected ? 'selected' : ''}`}
                onClick={() => {
                  if (isSelected) {
                    handleRemoveTag(tag);
                  } else if (!isMaxed) {
                    const newTags = [...currentTags, tag];
                    onChange(newTags.join(', '));
                  }
                }}
                disabled={disabled || (isMaxed && !isSelected)}
              >
                #{tag}
              </button>
            );
          })}
        </div>
      )}

      {onSubmit && (
        <button
          type="button"
          className="tag-chip-submit"
          onClick={handleSubmitClick}
          disabled={disabled}
        >
          Save
        </button>
      )}
    </div>
  );
}

/**
 * Helper to convert comma-separated string to array
 */
TagChipInput.parse = (value) => {
  return value
    .split(/[,\s]+/)
    .map((tag) => tag.trim().toLowerCase().replace(/^#/, ''))
    .filter(Boolean);
};

/**
 * Helper to format array back to string
 */
TagChipInput.format = (tags) => {
  return Array.isArray(tags) ? tags.join(', ') : tags;
};
