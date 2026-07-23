import React, { useState } from 'react';
import './RegisterForm.css';

const USERNAME_RE = /^[a-z0-9_][a-z0-9_-]*$/;

function validate({ username, nickname, invite_code }) {
  const errs = {};
  if (!username.trim()) {
    errs.username = 'Username is required';
  } else if (username.length < 3 || username.length > 32) {
    errs.username = 'Username must be 3–32 characters';
  } else if (!USERNAME_RE.test(username)) {
    errs.username = 'Lowercase letters, numbers, underscores, and hyphens only';
  }
  if (!nickname.trim()) {
    errs.nickname = 'Nickname is required';
  } else if (nickname.trim().length < 2 || nickname.trim().length > 64) {
    errs.nickname = 'Nickname must be 2–64 characters';
  }
  if (!invite_code.trim()) {
    errs.invite_code = 'Invite code is required';
  }
  return errs;
}

export default function RegisterForm({ onRegister }) {
  const [fields, setFields] = useState({ username: '', nickname: '', invite_code: '' });
  const [fieldErrors, setFieldErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const set = (key) => (e) => {
    const value = key === 'username' ? e.target.value.toLowerCase() : e.target.value;
    setFields(f => ({ ...f, [key]: value }));
    setFieldErrors(fe => ({ ...fe, [key]: '' }));
    setFormError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const errs = validate(fields);
    if (Object.keys(errs).length) {
      setFieldErrors(errs);
      return;
    }
    setIsSubmitting(true);
    setFormError('');
    try {
      await onRegister({
        username: fields.username.trim(),
        nickname: fields.nickname.trim(),
        invite_code: fields.invite_code.trim(),
      });
    } catch (err) {
      setFormError(err.message || 'Registration failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="register-form-container">
      <div className="register-form">
        <h1>Friend Hub</h1>
        <p className="subtitle">Create your account to join</p>

        {formError && <div className="form-error">{formError}</div>}

        <form onSubmit={handleSubmit} noValidate>
          <div className="input-group">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              value={fields.username}
              onChange={set('username')}
              placeholder="e.g. luke"
              maxLength={32}
              autoFocus
              autoCapitalize="none"
              autoCorrect="off"
              disabled={isSubmitting}
              className={fieldErrors.username ? 'error' : ''}
            />
            {fieldErrors.username && <div className="field-error">{fieldErrors.username}</div>}
          </div>

          <div className="input-group">
            <label htmlFor="nickname">Nickname</label>
            <input
              id="nickname"
              type="text"
              value={fields.nickname}
              onChange={set('nickname')}
              placeholder="e.g. Chat GBeanT"
              maxLength={64}
              disabled={isSubmitting}
              className={fieldErrors.nickname ? 'error' : ''}
            />
            {fieldErrors.nickname && <div className="field-error">{fieldErrors.nickname}</div>}
          </div>

          <div className="input-group">
            <label htmlFor="invite_code">Invite Code</label>
            <input
              id="invite_code"
              type="password"
              value={fields.invite_code}
              onChange={set('invite_code')}
              placeholder="Enter invite code"
              disabled={isSubmitting}
              className={fieldErrors.invite_code ? 'error' : ''}
            />
            {fieldErrors.invite_code && <div className="field-error">{fieldErrors.invite_code}</div>}
          </div>

          <button
            type="submit"
            className="register-button"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Joining…' : 'Join Friend Hub'}
          </button>
        </form>

        <p className="invite-hint">You need an invite code to join.</p>
      </div>
    </div>
  );
}
