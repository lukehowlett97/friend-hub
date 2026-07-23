import React, { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import './InviteShareCard.css';

// Shown once after an invite/PIN-reset is generated. Bundles the shareable link,
// a scannable QR, copy, and native share — covering both in-person (QR) and
// messaging-app (link/share) handoff. The raw code stays available as a fallback.
export default function InviteShareCard({ inviteUrl, inviteCode, displayName }) {
  const [copied, setCopied] = useState(false);
  const url = inviteUrl || '';

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const share = async () => {
    const text = displayName
      ? `You're invited to Friend Hub, ${displayName}. Tap to set a PIN and join:`
      : "You're invited to Friend Hub. Tap to set a PIN and join:";
    if (navigator.share) {
      try {
        await navigator.share({ title: 'Friend Hub invite', text, url });
      } catch {
        // user dismissed the share sheet — nothing to do
      }
    } else {
      copy();
    }
  };

  return (
    <div className="invite-share-card">
      <p className="invite-share-warning">
        Share this now — it’s only shown once
        {displayName ? ` and is for ${displayName}` : ''}.
      </p>

      {url && (
        <div className="invite-share-qr">
          <QRCodeSVG value={url} size={140} level="M" includeMargin />
          <span>Scan to join</span>
        </div>
      )}

      {url && (
        <div className="invite-share-link">
          <input type="text" value={url} readOnly onFocus={e => e.target.select()} />
          <button type="button" onClick={copy}>{copied ? 'Copied!' : 'Copy link'}</button>
          <button type="button" onClick={share}>Share</button>
        </div>
      )}

      <p className="invite-share-code">
        Or give them the code: <code>{inviteCode}</code>
      </p>
    </div>
  );
}
