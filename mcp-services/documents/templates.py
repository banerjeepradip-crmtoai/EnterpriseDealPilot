"""The one approved proposal template.

Not agent-editable — an agent fills in blanks from a signed quote and
screened evidence; it does not write free-form commercial language. See
the architecture doc's "MVP cut line": one proposal template.

Rendered as a single self-contained HTML document (inline CSS, inline SVG
logo — no external requests, no fonts/images fetched over the network) so
it looks like a real proposal when opened from the attached ContentVersion,
not a plain-text dump. The logo mark is abstract on purpose: a hub node
(the Deal Orchestrator) connected to three satellite nodes (the specialist
agents) — it's meant to represent what the system actually is, not a
placeholder shape.

Every `{...}` below except literal CSS/SVG braces (all doubled, `{{`/`}}`,
since this is a str.format() template) is filled in by
mcp-services/documents/client.py's generate_proposal from an authoritative,
signed quote — never typed freehand by an agent.
"""

PROPOSAL_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Proposal — {customer_name}</title>
<style>
  :root {{
    --navy: #1c2b4a;
    --navy-soft: #eef1f6;
    --gold: #b8860b;
    --ink: #22262f;
    --ink-soft: #5b6270;
    --rule: #dde1e8;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: #f4f5f7;
    color: var(--ink);
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 15px;
    line-height: 1.6;
  }}
  .sheet {{
    max-width: 720px;
    margin: 2.5rem auto;
    background: #ffffff;
    border: 1px solid var(--rule);
    box-shadow: 0 1px 3px rgba(28, 43, 74, 0.08);
  }}
  .letterhead {{
    display: flex;
    align-items: center;
    gap: 0.9rem;
    padding: 1.6rem 2.2rem;
    background: var(--navy);
    color: #ffffff;
  }}
  .letterhead .wordmark {{
    font-family: 'Segoe UI', -apple-system, Helvetica, Arial, sans-serif;
    font-size: 1.15rem;
    font-weight: 700;
    letter-spacing: 0.01em;
  }}
  .letterhead .tagline {{
    font-family: 'Segoe UI', -apple-system, Helvetica, Arial, sans-serif;
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #b9c3d6;
    margin-top: 0.15rem;
  }}
  .goldbar {{ height: 4px; background: var(--gold); }}
  .body {{ padding: 2.1rem 2.2rem 2.4rem; }}
  .doctitle {{
    font-family: 'Segoe UI', -apple-system, Helvetica, Arial, sans-serif;
    font-size: 0.72rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--ink-soft);
    margin: 0 0 0.3rem;
  }}
  h1 {{
    font-size: 1.6rem;
    margin: 0 0 1.6rem;
    color: var(--navy);
  }}
  h2 {{
    font-family: 'Segoe UI', -apple-system, Helvetica, Arial, sans-serif;
    font-size: 0.76rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--gold);
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.4rem;
    margin: 1.9rem 0 0.8rem;
  }}
  p {{ margin: 0 0 0.9rem; }}
  table.quote {{ width: 100%; border-collapse: collapse; margin-top: 0.3rem; }}
  table.quote td {{ padding: 0.5rem 0; border-bottom: 1px solid var(--rule); font-size: 0.95rem; }}
  table.quote td.label {{ color: var(--ink-soft); }}
  table.quote td.value {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.quote tr.total td {{ border-bottom: none; border-top: 2px solid var(--navy); padding-top: 0.7rem; font-weight: 700; font-size: 1.05rem; color: var(--navy); }}
  .context-block {{
    background: var(--navy-soft);
    border-left: 3px solid var(--navy);
    padding: 0.8rem 1rem;
    font-size: 0.93rem;
    color: var(--ink-soft);
  }}
  .validity {{
    margin-top: 1.9rem;
    padding-top: 1rem;
    border-top: 1px dashed var(--rule);
    font-size: 0.85rem;
    color: var(--ink-soft);
  }}
  .footer {{
    font-family: 'Segoe UI', -apple-system, Helvetica, Arial, sans-serif;
    font-size: 0.72rem;
    color: var(--ink-soft);
    text-align: center;
    padding: 1rem;
  }}
</style>
</head>
<body>
  <div class="sheet">
    <div class="letterhead">
      <svg width="34" height="34" viewBox="0 0 34 34" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <circle cx="17" cy="17" r="4.5" fill="#ffffff"></circle>
        <circle cx="6" cy="8" r="3" fill="#b9c3d6"></circle>
        <circle cx="28" cy="8" r="3" fill="#b9c3d6"></circle>
        <circle cx="17" cy="29" r="3" fill="#b9c3d6"></circle>
        <line x1="17" y1="17" x2="6" y2="8" stroke="#b9c3d6" stroke-width="1.4"></line>
        <line x1="17" y1="17" x2="28" y2="8" stroke="#b9c3d6" stroke-width="1.4"></line>
        <line x1="17" y1="17" x2="17" y2="29" stroke="#b9c3d6" stroke-width="1.4"></line>
      </svg>
      <div>
        <div class="wordmark">DealPilot</div>
        <div class="tagline">Governed Sales Proposal</div>
      </div>
    </div>
    <div class="goldbar"></div>
    <div class="body">
      <p class="doctitle">Prepared for</p>
      <h1>{customer_name}</h1>
      <p style="color: var(--ink-soft); margin-top: -1rem;">Opportunity: {opportunity_name}</p>

      <h2>Business need</h2>
      <p>{use_case}</p>

      <h2>Recommended solution</h2>
      <table class="quote">
        <tr><td class="label">Bundle</td><td class="value">{bundle_name}</td></tr>
        <tr><td class="label">Quantity</td><td class="value">{quantity}</td></tr>
        <tr><td class="label">Unit price</td><td class="value">${unit_price:.2f}</td></tr>
        <tr><td class="label">Subtotal</td><td class="value">${subtotal:.2f}</td></tr>
        <tr><td class="label">Discount</td><td class="value">{discount_pct:.0f}% (&minus;${discount_amount:.2f})</td></tr>
        <tr class="total"><td>Total</td><td class="value">${grand_total:.2f}</td></tr>
      </table>

      <h2>Additional context</h2>
      <div class="context-block">{context}</div>

      <p class="validity">This proposal is valid until <strong>{expiry}</strong>.</p>
    </div>
  </div>
  <p class="footer">Generated by DealPilot from a signed, tamper-verified quote &mdash; no figure above was typed by hand.</p>
</body>
</html>
"""
