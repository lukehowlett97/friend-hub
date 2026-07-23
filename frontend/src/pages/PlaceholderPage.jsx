import React from 'react';

const PlaceholderPage = ({ title }) => (
  <section className="page">
    <header className="page-header">
      <h1>{title}</h1>
    </header>
    <div className="placeholder-panel">Coming soon</div>
  </section>
);

export default PlaceholderPage;
