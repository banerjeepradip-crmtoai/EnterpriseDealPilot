"""The one approved proposal template.

Not agent-editable — an agent fills in blanks from a signed quote and
screened evidence; it does not write free-form commercial language. See
the architecture doc's "MVP cut line": one proposal template.
"""

PROPOSAL_TEMPLATE = """\
PROPOSAL — {customer_name}
Opportunity: {opportunity_name}

Use case
--------
{use_case}

Recommended solution
---------------------
Bundle: {bundle_name}
Quantity: {quantity}
Unit price: ${unit_price:.2f}
Subtotal: ${subtotal:.2f}
Discount: {discount_pct:.0f}% (-${discount_amount:.2f})
Total: ${grand_total:.2f}

Additional context
-------------------
{context}

This proposal is valid until {expiry}.
"""
