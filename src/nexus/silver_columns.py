"""The canonical invoice: the one model every accounting and ERP source is mapped onto in silver."""
CANONICAL = ["company_id", "source_invoice_id", "doc_type", "status", "issue_date", "due_date", "subtotal", "tax",
             "amount_due", "currency", "account_id", "paid_date", "source_modified_at", "sync_seq"]
