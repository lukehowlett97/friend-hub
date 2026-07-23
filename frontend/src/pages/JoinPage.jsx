import React, { useEffect, useState } from 'react';
import { useAuth } from '../auth/AuthProvider.jsx';
import { peekInvite } from '../api/auth.js';
import '../components/Auth/RegisterForm.css';

const PIN_RE = /^\d{6}$/;

// Landing page for shareable invite links (/join/<code>). The code comes from the
// URL, so the invitee only chooses a PIN. We peek the code first to greet them by
// name and to fail fast on expired/used links before they type anything.
export default function JoinPage({ inviteCode, onExpired }) {
  const { claimInvite } = useAuth();
  const [status, setStatus] = useState('checking'); // checking | ready | invalid
  const [displayName, setDisplayName] = useState(null);
  const [room, setRoom] = useState(null);
  const [pin, setPin] = useState('');
  const [pinConfirm, setPinConfirm] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    peekInvite(inviteCode)
      .then(result => {
        if (cancelled) return;
        if (result.valid) {
          setDisplayName(result.display_name);
          setRoom(result.room || null);
          setStatus('ready');
        } else {
          setStatus('invalid');
        }
      })
      .catch(() => {
        if (!cancelled) setStatus('invalid');
      });
    return () => { cancelled = true; };
  }, [inviteCode]);

  const submit = async (event) => {
    event.preventDefault();
    if (!PIN_RE.test(pin)) {
      setError('PIN must be exactly 6 digits');
      return;
    }
    if (pin !== pinConfirm) {
      setError('PIN confirmation does not match');
      return;
    }
    setIsSubmitting(true);
    setError('');
    try {
      await claimInvite({ invite_code: inviteCode, pin, pin_confirm: pinConfirm });
      // Success flips auth state; App re-renders into the authenticated app.
    } catch (err) {
      setError(err.message || 'Invite claim failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="register-form-container">
      <div className="register-form">
        <h1>Friend Hub</h1>

        {status === 'checking' && <p className="subtitle">Checking your invite…</p>}

        {status === 'invalid' && (
          <>
            <div className="form-error">This invite link is invalid, expired, or already used.</div>
            <p className="subtitle">Ask whoever invited you for a fresh link.</p>
            <button type="button" className="secondary-auth-button" onClick={onExpired}>
              Go to login
            </button>
          </>
        )}

        {status === 'ready' && (
          <>
            <p className="subtitle">Welcome to Friend Hub.</p>
            <p className="subtitle">
              You've been invited as{' '}
              {displayName ? <strong>{displayName}</strong> : 'a new member'}
              {room && (
                <>
                  {' '}to join room <strong>{room.name || room.slug || room.id}</strong>
                </>
              )}
              .
            </p>
            <p className="subtitle">
              Set a 6 digit PIN to login. Admins can reset your PIN.
            </p>
            {error && <div className="form-error">{error}</div>}
            <form onSubmit={submit} noValidate>
              <div className="input-group">
                <label htmlFor="join_pin">Choose 6-digit PIN</label>
                <input
                  id="join_pin"
                  type="password"
                  inputMode="numeric"
                  maxLength={6}
                  value={pin}
                  onChange={e => { setPin(e.target.value); setError(''); }}
                  autoFocus
                  disabled={isSubmitting}
                />
              </div>
              <div className="input-group">
                <label htmlFor="join_pin_confirm">Confirm PIN</label>
                <input
                  id="join_pin_confirm"
                  type="password"
                  inputMode="numeric"
                  maxLength={6}
                  value={pinConfirm}
                  onChange={e => { setPinConfirm(e.target.value); setError(''); }}
                  disabled={isSubmitting}
                />
              </div>
              <button type="submit" className="register-button" disabled={isSubmitting}>
                {isSubmitting ? 'Creating…' : 'Create my account'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
