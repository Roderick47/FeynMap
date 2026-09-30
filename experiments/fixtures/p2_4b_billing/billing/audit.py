def payment_reference(invoice_id, remaining_cents):
    return f"PAYMENT:{invoice_id}:{remaining_cents}"
