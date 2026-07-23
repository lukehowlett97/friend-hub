import React, { useState } from 'react';
import { useAuth } from '../auth/AuthProvider.jsx';
import '../components/Auth/RegisterForm.css';

const PIN_RE = /^\d{6}$/;

export default function WelcomePage() {
  const { claimInvite, pinLogin } = useAuth();
  const [mode, setMode] = useState('choice');
  const [fields, setFields] = useState({ invite_code: '', username: '', pin: '', pin_confirm: '' });
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const set = (key) => (event) => {
    const value = key === 'username' ? event.target.value.toLowerCase() : event.target.value;
    setFields(current => ({ ...current, [key]: value }));
    setError('');
  };

  const submitInvite = async (event) => {
    event.preventDefault();
    if (!PIN_RE.test(fields.pin)) {
      setError('PIN must be exactly 6 digits');
      return;
    }
    if (fields.pin !== fields.pin_confirm) {
      setError('PIN confirmation does not match');
      return;
    }
    setIsSubmitting(true);
    try {
      await claimInvite({
        invite_code: fields.invite_code.trim(),
        pin: fields.pin,
        pin_confirm: fields.pin_confirm,
      });
    } catch (err) {
      setError(err.message || 'Invite claim failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const submitLogin = async (event) => {
    event.preventDefault();
    if (!fields.username.trim() || !PIN_RE.test(fields.pin)) {
      setError('Login failed. Check your details and try again.');
      return;
    }
    setIsSubmitting(true);
    try {
      await pinLogin({ username: fields.username.trim(), pin: fields.pin });
    } catch {
      setError('Login failed. Check your details and try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="register-form-container">
      <div className="register-form">
        <h1>Welcome to Friend Hub</h1>
        {error && <div className="form-error">{error}</div>}

        {mode === 'choice' && (
          <div className="auth-choice-actions">
            <button type="button" className="secondary-auth-button" onClick={() => { window.location.href = '/demo'; }}>
              Try the public demo
            </button>
            <button type="button" className="register-button" onClick={() => setMode('invite')}>
              I have an invite code
            </button>
            <button type="button" className="secondary-auth-button" onClick={() => setMode('login')}>
              I already have an account
            </button>
          </div>
        )}

        {mode === 'invite' && (
          <form onSubmit={submitInvite} noValidate>
            <div className="input-group">
              <label htmlFor="invite_code">Invite code</label>
              <input id="invite_code" value={fields.invite_code} onChange={set('invite_code')} autoFocus disabled={isSubmitting} />
            </div>
            <div className="input-group">
              <label htmlFor="pin">Choose 6-digit PIN</label>
              <input id="pin" type="password" inputMode="numeric" maxLength={6} value={fields.pin} onChange={set('pin')} disabled={isSubmitting} />
            </div>
            <div className="input-group">
              <label htmlFor="pin_confirm">Confirm PIN</label>
              <input id="pin_confirm" type="password" inputMode="numeric" maxLength={6} value={fields.pin_confirm} onChange={set('pin_confirm')} disabled={isSubmitting} />
            </div>
            <button type="submit" className="register-button" disabled={isSubmitting}>
              {isSubmitting ? 'Creating...' : 'Create my account'}
            </button>
            <button type="button" className="link-auth-button" onClick={() => setMode('choice')} disabled={isSubmitting}>Back</button>
          </form>
        )}

        {mode === 'login' && (
          <form onSubmit={submitLogin} noValidate>
            <div className="input-group">
              <label htmlFor="username">Username</label>
              <input id="username" value={fields.username} onChange={set('username')} autoFocus autoCapitalize="none" autoCorrect="off" disabled={isSubmitting} />
            </div>
            <div className="input-group">
              <label htmlFor="login_pin">PIN</label>
              <input id="login_pin" type="password" inputMode="numeric" maxLength={6} value={fields.pin} onChange={set('pin')} disabled={isSubmitting} />
            </div>
            <button type="submit" className="register-button" disabled={isSubmitting}>
              {isSubmitting ? 'Logging in...' : 'Log in'}
            </button>
            <button type="button" className="link-auth-button" onClick={() => setMode('choice')} disabled={isSubmitting}>Back</button>
          </form>
        )}
      </div>
    </div>
  );
}
