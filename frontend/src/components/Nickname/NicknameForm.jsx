import React, { useState } from 'react';
import './NicknameForm.css';

const NicknameForm = ({ onSubmit, isLoading = false, error = null }) => {
  const [nickname, setNickname] = useState('');
  const [validationError, setValidationError] = useState('');

  const validateNickname = (name) => {
    if (!name.trim()) {
      return 'Nickname is required';
    }
    if (name.length < 2) {
      return 'Nickname must be at least 2 characters';
    }
    if (name.length > 20) {
      return 'Nickname must be less than 20 characters';
    }
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
      return 'Nickname can only contain letters, numbers, hyphens, and underscores';
    }
    return '';
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmedNickname = nickname.trim();
    const validationError = validateNickname(trimmedNickname);
    
    if (validationError) {
      setValidationError(validationError);
      return;
    }
    
    setValidationError('');
    onSubmit(trimmedNickname);
  };

  const handleInputChange = (e) => {
    const value = e.target.value;
    setNickname(value);
    
    // Clear validation error when user starts typing
    if (validationError) {
      setValidationError('');
    }
  };

  return (
    <div className="nickname-form-container">
      <div className="nickname-form">
        <h1>Join Friend Hub Chat</h1>
        <p className="subtitle">Choose a nickname to get started</p>
        
        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <input
              type="text"
              value={nickname}
              onChange={handleInputChange}
              placeholder="Enter your nickname"
              maxLength={20}
              autoFocus
              disabled={isLoading}
              className={validationError || error ? 'error' : ''}
            />
            {(validationError || error) && (
              <div className="error-message">
                {validationError || error}
              </div>
            )}
          </div>
          
          <button 
            type="submit" 
            disabled={!nickname.trim() || isLoading || !!validationError}
            className="join-button"
          >
            {isLoading ? 'Joining...' : 'Join Chat'}
          </button>
        </form>
        
        <div className="nickname-rules">
          <p>Nickname rules:</p>
          <ul>
            <li>2-20 characters long</li>
            <li>Letters, numbers, hyphens, and underscores only</li>
            <li>Must be unique</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default NicknameForm;