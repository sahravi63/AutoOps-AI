"""
AutoOps AI — Campus Payment Remediation Tool Library
======================================================
Focused tools for Bursar's Office payment failure remediation:

  PaymentTool      → process_payment, refund, get_transaction, check_duplicate (Stripe/TouchNet integration)
  TicketTool       → create_ticket, update_ticket (ServiceNow/Jira ITSM integration)
  NotificationTool → send_email, send_slack, notify_team (Slack/Email webhooks)
  DatabaseTool     → query, update, insert (student records, payment history)
"""

import os
import random
import requests
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Shared SQLite database (one file, all tools) ────────────────────────────
_DB_PATH = Path(__file__).parent.parent.parent / "autoops.db"
_db_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _bootstrap_db() -> None:
    """Create tables and seed realistic data on first run."""
    with _db_lock, _get_conn() as conn:
        cur = conn.cursor()

        # ── Knowledge base (FTS5 full-text search) ───────────────────────
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id      TEXT PRIMARY KEY,
            topic   TEXT NOT NULL,
            content TEXT NOT NULL,
            tags    TEXT,
            hits    INTEGER DEFAULT 0,
            created TEXT
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
            USING fts5(id UNINDEXED, topic, content, tags);
        """)

        # Seed KB if empty
        if cur.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0:
            kb_rows = [
                ("kb-001", "payment_failure",
                 "Payment failed but money deducted: (1) Verify transaction in gateway logs. "
                 "(2) Confirm deduction in bank statement. (3) If confirmed, initiate refund "
                 "via payment portal within 2 business days. (4) Create support ticket. "
                 "(5) Email customer with refund ID and ETA. SLA: 2 hours.",
                 "payment refund deduction gateway"),
                ("kb-002", "duplicate_charge",
                 "Duplicate charge resolution: (1) Run check_duplicate to find original and "
                 "duplicate transaction IDs. (2) Refund the duplicate transaction immediately. "
                 "(3) Send email confirmation to customer with both transaction IDs. "
                 "(4) Log in audit trail. Policy: full refund, no questions asked.",
                 "duplicate charge refund billing"),
                ("kb-003", "delivery_not_received",
                 "Delivery dispute — item not received: (1) Pull GPS proof from carrier API. "
                 "(2) If GPS shows delivered, request photo evidence. (3) If unresolved in "
                 "24h, open investigation with logistics team. (4) Offer reship or full "
                 "refund. SLA: resolution within 48 hours.",
                 "delivery shipment tracking courier undelivered"),
                ("kb-004", "invoice_generation",
                 "Invoice generation SOP: (1) Fetch order from database. (2) Calculate taxes "
                 "(18% GST for IN, applicable VAT for other regions). (3) Generate PDF via "
                 "invoice_tool. (4) Email to customer billing address. (5) Store copy in "
                 "document store. Retention: 7 years.",
                 "invoice billing tax pdf"),
                ("kb-005", "server_outage",
                 "P1 outage response: (1) Check service health endpoint immediately. "
                 "(2) Review error logs (last 15 min). (3) Attempt service restart. "
                 "(4) If restart fails, failover to standby. (5) Notify DevOps + management. "
                 "(6) Post incident report within 1 hour. SLA: 15 min acknowledgement.",
                 "outage incident crash server down p1"),
                ("kb-006", "resume_screening",
                 "Resume screening process: (1) Extract skills using NLP. (2) Score against "
                 "JD requirements (skills 40%, experience 35%, education 25%). (3) Shortlist "
                 "top 20% (minimum score 75). (4) Schedule interviews for shortlisted. "
                 "(5) Send rejection emails to others within 5 days.",
                 "resume cv candidate hire recruit screening"),
                ("kb-007", "refund_policy",
                 "Refund policy: Full refund within 7 days of purchase, no questions asked. "
                 "50% refund between 7–30 days. No refund after 30 days except for defects. "
                 "Digital products: 24h window. Processing time: 3–5 business days.",
                 "refund policy return money back"),
                ("kb-008", "data_privacy",
                 "Data handling: All PII must be encrypted at rest (AES-256). Logs must not "
                 "contain customer passwords or card numbers. GDPR right-to-erasure requests "
                 "must be fulfilled within 30 days. Breach notification: 72 hours to regulator.",
                 "privacy gdpr data security pii"),
            ]
            cur.executemany(
                "INSERT INTO knowledge VALUES (?,?,?,?,0,?)",
                [(r[0], r[1], r[2], r[3], datetime.utcnow().isoformat()) for r in kb_rows]
            )
            cur.executemany(
                "INSERT INTO knowledge_fts(id,topic,content,tags) VALUES (?,?,?,?)",
                [(r[0], r[1], r[2], r[3]) for r in kb_rows]
            )

        # ── Tickets ──────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id   TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            description TEXT,
            priority    TEXT DEFAULT 'medium',
            category    TEXT DEFAULT 'general',
            status      TEXT DEFAULT 'open',
            assigned_to TEXT,
            notes       TEXT,
            created_at  TEXT,
            updated_at  TEXT,
            sla_hours   INTEGER
        )""")

        # ── Orders ───────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id    TEXT PRIMARY KEY,
            customer_id TEXT,
            status      TEXT,
            total       REAL,
            items       TEXT,
            created_at  TEXT,
            updated_at  TEXT
        )""")

        # ── Customers ────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            name        TEXT,
            email       TEXT,
            tier        TEXT DEFAULT 'standard',
            created_at  TEXT
        )""")

        # ── Transactions ─────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id      TEXT PRIMARY KEY,
            customer_id TEXT,
            order_id    TEXT,
            amount      REAL,
            currency    TEXT DEFAULT 'USD',
            status      TEXT DEFAULT 'completed',
            description TEXT,
            created_at  TEXT
        )""")

        # Seed realistic data if empty
        if cur.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            now = datetime.utcnow().isoformat()
            cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", [
                ("STU-00123", "Rahul Sharma",  "rahul@university.edu",  "undergraduate",     now),
                ("STU-00456", "Priya Nair",    "priya@university.edu",  "graduate",   now),
                ("STU-00789", "Vikram Singh",  "vikram@university.edu", "undergraduate", now),
            ])
            cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", [
                ("TUITION-FALL-2024", "STU-00123", "enrolled",   2999.00,
                 '[{"item":"Fall Tuition","qty":1,"price":2999}]', now, now),
                ("TUITION-SPRING-2025", "STU-00456", "enrolled",  1499.00,
                 '[{"item":"Spring Tuition","qty":1,"price":1499}]',    now, now),
                ("TUITION-FALL-2024", "STU-00789", "enrolled",  2499.00,
                 '[{"item":"Fall Tuition","qty":1,"price":2499}]', now, now),
            ])
            cur.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)", [
                ("TXN-AB12CD34", "STU-00123", "TUITION-FALL-2024", 2999.00,
                 "USD", "failed", "Tuition payment failed", now),
                ("TXN-XY98ZW11", "STU-00456", "TUITION-SPRING-2025",  1499.00,
                 "USD", "completed", "Tuition payment",  now),
            ])

        conn.commit()


# Bootstrap on import
_bootstrap_db()


# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Ticket Tool — SQLite-persisted tickets
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Ticket Tool — SQLite-persisted tickets
# ─────────────────────────────────────────────
class TicketTool:
    def __init__(self):
        self.instance_url = os.getenv("SERVICENOW_INSTANCE_URL", "").rstrip("/")
        self.user = os.getenv("SERVICENOW_USER", "")
        self.password = os.getenv("SERVICENOW_PASSWORD", "")
        self.webhook_url = os.getenv("ITSM_WEBHOOK_URL", "")

    def _servicenow_headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def _servicenow_request(self, method: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.instance_url or not self.user or not self.password:
            raise RuntimeError("ServiceNow integration is not configured")
        url = f"{self.instance_url}{path}"
        response = requests.request(
            method, url, auth=(self.user, self.password), json=payload,
            headers=self._servicenow_headers(), timeout=15
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"ServiceNow API error {response.status_code}: {response.text}"
            )
        return response.json().get("result", {})

    def create_ticket(self, title: str, description: str, priority: str = "medium",
                      category: str = "general", assigned_to: str = "") -> Dict[str, Any]:
        if self.instance_url and self.user and self.password:
            urgency_map = {"low": "3", "medium": "2", "high": "1", "critical": "1"}
            incident = {
                "short_description": title,
                "description": description,
                "urgency": urgency_map.get(priority, "2"),
                "assignment_group": assigned_to or "Bursar Office",
                "category": category,
            }
            result = self._servicenow_request("POST", "/api/now/table/incident", incident)
            ticket_id = result.get("number") or f"SN-{uuid.uuid4().hex[:6].upper()}"
            ticket_url = result.get("sys_url") or f"{self.instance_url}/nav_to.do?uri=incident.do?sys_id={result.get('sys_id')}"
            logger.info(f"[TicketTool] ServiceNow ticket created {ticket_id}")
            return {
                "status": "created",
                "ticket_id": ticket_id,
                "title": title,
                "priority": priority,
                "category": category,
                "assigned_to": assigned_to or "Bursar Office",
                "created_at": datetime.utcnow().isoformat(),
                "url": ticket_url,
                "source": "servicenow",
            }

        ticket_id = f"OPS-{random.randint(1000, 9999)}"
        sla_map = {"low": 48, "medium": 24, "high": 4, "critical": 1}
        sla_hours = sla_map.get(priority, 24)
        now = datetime.utcnow().isoformat()
        assigned = assigned_to or "support-team"
        with _db_lock, _get_conn() as conn:
            conn.execute(
                "INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ticket_id, title, description, priority, category,
                 "open", assigned, "", now, now, sla_hours)
            )
            conn.commit()
        logger.info(f"[TicketTool] Created {ticket_id}: {title[:50]} [{priority}]")
        return {
            "status": "created",
            "ticket_id": ticket_id,
            "title": title,
            "priority": priority,
            "category": category,
            "assigned_to": assigned,
            "sla_hours": sla_hours,
            "created_at": now,
            "url": f"/tickets/{ticket_id}",
            "source": "local",
        }

    def update_ticket(self, ticket_id: str, status: str, notes: str = "") -> Dict[str, Any]:
        if self.instance_url and self.user and self.password:
            payload = {"state": status, "work_notes": notes}
            result = self._servicenow_request(
                "PATCH", f"/api/now/table/incident/{ticket_id}", payload
            )
            logger.info(f"[TicketTool] ServiceNow ticket updated {ticket_id} → {status}")
            return {"status": "updated", "ticket_id": ticket_id,
                    "new_status": status, "notes": notes, "source": "servicenow", "result": result}

        now = datetime.utcnow().isoformat()
        with _db_lock, _get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tickets SET status=?, notes=?, updated_at=? WHERE ticket_id=?",
                (status, notes, now, ticket_id)
            )
            if cur.rowcount == 0:
                return {"status": "not_found", "ticket_id": ticket_id}
            conn.commit()
        logger.info(f"[TicketTool] Updated {ticket_id} → {status}")
        return {"status": "updated", "ticket_id": ticket_id,
                "new_status": status, "notes": notes, "updated_at": now}

    def get_ticket(self, ticket_id: str) -> Dict[str, Any]:
        if self.instance_url and self.user and self.password:
            return self._servicenow_request("GET", f"/api/now/table/incident/{ticket_id}", {})

        with _db_lock, _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
        if not row:
            return {"status": "not_found", "ticket_id": ticket_id}
        return dict(row)

    def list_open_tickets(self, priority: str = "") -> Dict[str, Any]:
        if self.instance_url and self.user and self.password:
            path = "/api/now/table/incident?sysparm_query=active=true"
            if priority:
                path += f"^urgency={priority}"
            result = self._servicenow_request("GET", path, {})
            return {"status": "ok", "count": len(result.get("result", [])), "tickets": result.get("result", [])}

        with _db_lock, _get_conn() as conn:
            if priority:
                rows = conn.execute(
                    "SELECT * FROM tickets WHERE status='open' AND priority=? ORDER BY created_at DESC LIMIT 20",
                    (priority,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tickets WHERE status='open' ORDER BY created_at DESC LIMIT 20"
                ).fetchall()
        tickets = [dict(r) for r in rows]
        return {"status": "ok", "count": len(tickets), "tickets": tickets}

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.create_ticket(**kwargs)


# ─────────────────────────────────────────────
# Database Tool — real SQLite queries
# ─────────────────────────────────────────────
class DatabaseTool:
    def query(self, table: str, filters: Dict[str, Any] = None,
              limit: int = 10) -> Dict[str, Any]:
        allowed = {"orders", "customers", "transactions", "tickets"}
        if table not in allowed:
            return {"error": f"Unknown table '{table}'. Allowed: {allowed}"}

        with _db_lock, _get_conn() as conn:
            cur = conn.cursor()
            if filters:
                where_parts = [f"{k}=?" for k in filters]
                rows = cur.execute(
                    f"SELECT * FROM {table} WHERE {' AND '.join(where_parts)} LIMIT ?",
                    list(filters.values()) + [limit]
                ).fetchall()
            else:
                rows = cur.execute(
                    f"SELECT * FROM {table} LIMIT ?", (limit,)
                ).fetchall()

        data = [dict(r) for r in rows]
        logger.info(f"[DatabaseTool] Queried {table}: {len(data)} rows")
        return {"table": table, "rows": data, "total_count": len(data),
                "filters_applied": filters or {}, "source": "sqlite"}

    def update(self, table: str, record_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"orders", "customers", "transactions", "tickets"}
        if table not in allowed:
            return {"error": f"Unknown table '{table}'"}
        pk_map = {"orders": "order_id", "customers": "customer_id",
                  "transactions": "txn_id", "tickets": "ticket_id"}
        pk = pk_map[table]
        now = datetime.utcnow().isoformat()
        data["updated_at"] = now
        sets = ", ".join(f"{k}=?" for k in data)
        with _db_lock, _get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE {table} SET {sets} WHERE {pk}=?",
                        list(data.values()) + [record_id])
            conn.commit()
        logger.info(f"[DatabaseTool] Updated {table} {record_id}")
        return {"status": "updated", "table": table, "record_id": record_id,
                "updated_fields": list(data.keys()), "updated_at": now}

    def insert(self, table: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if table not in {"orders", "customers", "transactions"}:
            return {"error": f"Insert not allowed on '{table}'"}
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        with _db_lock, _get_conn() as conn:
            conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})",
                         list(data.values()))
            conn.commit()
        logger.info(f"[DatabaseTool] Inserted into {table}")
        return {"status": "inserted", "table": table, "data": data}

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.query(**kwargs)


# ─────────────────────────────────────────────
# Payment Tool — Stripe sandbox + local ledger fallback
# ─────────────────────────────────────────────
class PaymentTool:
    # Class-level ledger so duplicate checks work within a session
    _ledger: Dict[str, Dict] = {}
    _refund_cache: Dict[str, Dict] = {}

    def __init__(self):
        self.stripe_api_key = os.getenv("STRIPE_API_KEY", "").strip()
        self.stripe_api_url = "https://api.stripe.com/v1"
        self.approval_threshold = int(os.getenv("REFUND_APPROVAL_THRESHOLD", "2000"))
        self.dry_run_mode = os.getenv("DRY_RUN_MODE", "false").lower() in ("1", "true", "yes")

    def _stripe_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self.stripe_api_key}"}
        if request_id:
            headers["Idempotency-Key"] = request_id
        return headers

    def _stripe_request(self, method: str, path: str, data: Dict[str, Any] = None,
                        request_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.stripe_api_key:
            raise RuntimeError("Stripe API key not configured for Stripe sandbox mode")
        url = f"{self.stripe_api_url}{path}"
        response = requests.request(
            method, url, auth=(self.stripe_api_key, ""), data=data or {},
            headers=self._stripe_headers(request_id)
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Stripe API error {response.status_code}: {response.text}"
            )
        return response.json()

    def process_payment(self, amount: float, currency: str = "USD",
                        customer_id: str = "", description: str = "",
                        request_id: Optional[str] = None) -> Dict[str, Any]:
        if request_id and request_id in PaymentTool._ledger:
            return PaymentTool._ledger[request_id]

        txn_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
        entry = {
            "transaction_id": txn_id,
            "amount": amount,
            "currency": currency,
            "customer_id": customer_id,
            "description": description,
            "status": "completed",
            "processed_at": datetime.utcnow().isoformat(),
            "source": "ledger",
        }
        PaymentTool._ledger[txn_id] = entry
        if request_id:
            PaymentTool._ledger[request_id] = entry
        logger.info(f"[PaymentTool] Processed {txn_id}: {currency} {amount} for {customer_id}")
        return entry

    def refund(self, transaction_id: str, amount: Optional[float] = None,
               reason: str = "", approved: bool = False,
               request_id: Optional[str] = None,
               dry_run: Optional[bool] = None) -> Dict[str, Any]:
        dry_run = self.dry_run_mode if dry_run is None else dry_run

        if request_id and request_id in PaymentTool._refund_cache:
            return PaymentTool._refund_cache[request_id]

        original = PaymentTool._ledger.get(transaction_id)
        if not original:
            with _db_lock, _get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM transactions WHERE txn_id=?", (transaction_id,)
                ).fetchone()
                if row:
                    original = dict(row)

        refund_amount = amount or (original.get("amount") if original else 0.0)
        if refund_amount > self.approval_threshold and not approved:
            message = (
                f"Refund ${refund_amount} exceeds approval threshold ${self.approval_threshold}. "
                "Require manual approval before processing."
            )
            logger.warning(f"[PaymentTool] {message}")
            result = {
                "status": "approval_required",
                "transaction_id": transaction_id,
                "requested_amount": refund_amount,
                "threshold": self.approval_threshold,
                "message": message,
            }
            if request_id:
                PaymentTool._refund_cache[request_id] = result
            return result

        if self.stripe_api_key and not dry_run:
            data = {"charge": transaction_id}
            if refund_amount:
                data["amount"] = int(refund_amount * 100)
            if reason:
                data["metadata[reason]"] = reason[:250]
            stripe_response = self._stripe_request(
                "POST", "/refunds", data=data, request_id=request_id
            )
            result = {
                "status": stripe_response.get("status", "unknown"),
                "refund_id": stripe_response.get("id"),
                "transaction_id": transaction_id,
                "amount": refund_amount,
                "reason": reason,
                "source": "stripe",
                "raw_response": stripe_response,
            }
        else:
            ref_id = f"REF-{uuid.uuid4().hex[:8].upper()}"
            result = {
                "status": "refunded",
                "refund_id": ref_id,
                "transaction_id": transaction_id,
                "amount": refund_amount,
                "reason": reason,
                "refunded_at": datetime.utcnow().isoformat(),
                "original_found": original is not None,
                "source": "dry_run" if dry_run else "ledger",
            }

        if request_id:
            PaymentTool._refund_cache[request_id] = result

        logger.info(f"[PaymentTool] Refunded {transaction_id} -> {result.get('refund_id')} (${refund_amount})")
        return result

    def get_transaction(self, transaction_id: str) -> Dict[str, Any]:
        if transaction_id in PaymentTool._ledger:
            return PaymentTool._ledger[transaction_id]

        if self.stripe_api_key:
            try:
                charge = self._stripe_request("GET", f"/charges/{transaction_id}")
                logger.info(f"[PaymentTool] Stripe charge found {transaction_id}")
                return {
                    "transaction_id": transaction_id,
                    "status": charge.get("status", "unknown"),
                    "amount": charge.get("amount") / 100 if charge.get("amount") else None,
                    "currency": charge.get("currency"),
                    "customer_id": charge.get("customer"),
                    "source": "stripe",
                    "raw_response": charge,
                }
            except Exception as exc:
                logger.warning(f"[PaymentTool] Stripe lookup failed: {exc}")

        with _db_lock, _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE txn_id=?", (transaction_id,)
            ).fetchone()
        if row:
            logger.info(f"[PaymentTool] Found {transaction_id} in DB")
            return dict(row)

        logger.warning(f"[PaymentTool] Transaction {transaction_id} not found")
        return {"transaction_id": transaction_id, "status": "not_found",
                "message": "Transaction not in ledger or database"}

    def verify_refund_status(self, transaction_id: str, refund_id: str) -> bool:
        if self.stripe_api_key:
            try:
                refund = self._stripe_request("GET", f"/refunds/{refund_id}")
                return refund.get("status") == "succeeded"
            except Exception as exc:
                logger.warning(f"[PaymentTool] Refund verification failed: {exc}")
                return False
        return True

    def check_duplicate(self, customer_id: str, amount: float) -> Dict[str, Any]:
        logger.info(f"[PaymentTool] Checking duplicates for {customer_id} amount={amount}")
        with _db_lock, _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE customer_id=? AND amount=? ORDER BY created_at DESC",
                (customer_id, amount)
            ).fetchall()
        matches = [dict(r) for r in rows]
        duplicate_found = len(matches) > 1
        return {
            "duplicate_found":  duplicate_found,
            "transactions": matches,
            "count": len(matches),
            "customer_id": customer_id,
            "amount": amount,
            "recommendation": "Initiate refund for duplicate charge" if duplicate_found else "No duplicate detected",
        }

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.process_payment(**kwargs)


# ─────────────────────────────────────────────
# Notification Tool — structured event log
# ─────────────────────────────────────────────
class NotificationTool:
    # In-process event log — wire to SMTP/Slack/webhook in production
    _events: List[Dict] = []

    def __init__(self):
        self.slack_webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
        self.email_webhook = os.getenv("EMAIL_WEBHOOK_URL", "").strip()

    def _post_webhook(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not url:
            raise RuntimeError("Webhook URL not configured")
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code >= 300:
            raise RuntimeError(f"Webhook failed {resp.status_code}: {resp.text}")
        return {"status": "sent", "response_status": resp.status_code}

    def send_email(self, to: str, subject: str, body: str,
                   cc: List[str] = None) -> Dict[str, Any]:
        msg_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
        payload = {
            "to": to,
            "cc": cc or [],
            "subject": subject,
            "body": body,
            "message_id": msg_id,
            "sent_at": datetime.utcnow().isoformat(),
        }
        if self.email_webhook:
            result = self._post_webhook(self.email_webhook, payload)
            payload.update(result)
            payload["source"] = "webhook"
        else:
            payload["status"] = "sent"
            payload["source"] = "local"
        NotificationTool._events.append(payload)
        logger.info(f"[NotificationTool] EMAIL → {to}: {subject}")
        return payload

    def send_slack(self, channel: str, message: str,
                   priority: str = "normal") -> Dict[str, Any]:
        ts = str(datetime.utcnow().timestamp())
        payload = {
            "channel": f"#{channel}",
            "text": message,
            "priority": priority,
            "ts": ts,
        }
        if self.slack_webhook:
            result = self._post_webhook(self.slack_webhook, payload)
            payload.update(result)
            payload["source"] = "slack_webhook"
        else:
            payload["status"] = "sent"
            payload["source"] = "local"
        NotificationTool._events.append(payload)
        logger.info(f"[NotificationTool] SLACK #{channel}: {message[:60]}")
        return payload

    def notify_team(self, team: str, message: str,
                    urgency: str = "normal") -> Dict[str, Any]:
        channels_used = ["email", "slack"] if urgency == "high" else ["slack"]
        results = []
        if "slack" in channels_used:
            results.append(self.send_slack(team, message, priority=urgency))
        if "email" in channels_used:
            results.append(self.send_email(f"{team}@university.edu", f"{team} alert", message))
        event = {
            "team": team,
            "message": message,
            "urgency": urgency,
            "channels_used": channels_used,
            "notified_at": datetime.utcnow().isoformat(),
            "results": results,
        }
        NotificationTool._events.append(event)
        logger.info(f"[NotificationTool] TEAM {team} [{urgency}]: {message[:60]}")
        return event

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.notify_team(**kwargs)


# ─────────────────────────────────────────────
# Invoice Tool — reads real orders from DB
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Delivery Tool — stateful registry
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Delivery Tool — stateful registry
# ─────────────────────────────────────────────
# Queue Tool — durable trigger queue for webhook events
# ─────────────────────────────────────────────

class QueueTool:
    """Durable work queue for webhook-triggered payment remediation jobs."""

    def __init__(self):
        self._bootstrap_queue()

    def _bootstrap_queue(self) -> None:
        with _db_lock, _get_conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                job_id       TEXT PRIMARY KEY,
                task         TEXT NOT NULL,
                context      TEXT,
                status       TEXT NOT NULL,
                attempts     INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                next_run_at  TEXT,
                created_at   TEXT,
                updated_at   TEXT,
                last_error   TEXT,
                source       TEXT
            )""")
            conn.commit()

    def enqueue_task(
        self,
        task: str,
        context: Dict[str, Any],
        source: str = "webhook",
        max_attempts: int = 3,
        delay_seconds: int = 0,
    ) -> Dict[str, Any]:
        job_id = f"JOB-{uuid.uuid4().hex[:10].upper()}"
        now = datetime.utcnow().isoformat()
        next_run = (datetime.utcnow() + timedelta(seconds=delay_seconds)).isoformat()
        with _db_lock, _get_conn() as conn:
            conn.execute(
                "INSERT INTO task_queue VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id, task, json.dumps(context), "pending",
                    0, max_attempts, next_run, now, now, "", source,
                )
            )
            conn.commit()

        logger.info(f"[QueueTool] Enqueued job {job_id} from {source}")
        return {"job_id": job_id, "status": "pending", "next_run_at": next_run}

    def fetch_next_task(self) -> Optional[Dict[str, Any]]:
        now = datetime.utcnow().isoformat()
        with _db_lock, _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM task_queue WHERE status='pending' AND next_run_at<=? ORDER BY next_run_at ASC LIMIT 1",
                (now,)
            ).fetchone()
        if not row:
            return None
        task = dict(row)
        task["context"] = json.loads(task["context"] or "{}")
        return task

    def mark_job_started(self, job_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with _db_lock, _get_conn() as conn:
            conn.execute(
                "UPDATE task_queue SET status='in_progress', updated_at=? WHERE job_id=?",
                (now, job_id)
            )
            conn.commit()

    def mark_job_result(
        self,
        job_id: str,
        success: bool,
        error: str = "",
        retry_delay_seconds: int = 0,
    ) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat()
        with _db_lock, _get_conn() as conn:
            row = conn.execute(
                "SELECT attempts, max_attempts FROM task_queue WHERE job_id=?",
                (job_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown job_id: {job_id}")
            attempts, max_attempts = row
            attempts += 1
            status = "completed" if success else (
                "dead_letter" if attempts >= max_attempts else "pending"
            )
            next_run = None
            if not success and status == "pending":
                next_run = (datetime.utcnow() + timedelta(seconds=retry_delay_seconds)).isoformat()
            else:
                next_run = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE task_queue SET status=?, attempts=?, next_run_at=?, updated_at=?, last_error=? WHERE job_id=?",
                (status, attempts, next_run, now, error, job_id)
            )
            conn.commit()

        logger.info(
            f"[QueueTool] Job {job_id} marked {status} (attempts={attempts}/{max_attempts})"
        )
        return {"job_id": job_id, "status": status, "attempts": attempts, "next_run_at": next_run}

    def list_jobs(self, status: str = "pending") -> Dict[str, Any]:
        with _db_lock, _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM task_queue WHERE status=? ORDER BY created_at DESC LIMIT 50",
                (status,)
            ).fetchall()
        jobs = [dict(r) for r in rows]
        for job in jobs:
            job["context"] = json.loads(job.get("context") or "{}")
        return {"count": len(jobs), "jobs": jobs}


# ─────────────────────────────────────────────
# Tool Registry
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Code Generation Tool — AI-powered development
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────

class CodeTool:
    """AI-powered code generation and file operations for software development."""

    def __init__(self):
        from app.llm_client import llm_complete
        self.llm_complete = llm_complete

    def generate_code(self, description: str, language: str = "python",
                     framework: str = "", requirements: str = "") -> Dict[str, Any]:
        """Generate code based on natural language description."""
        prompt = f"""Generate {language} code for: {description}

Requirements: {requirements}
Framework: {framework if framework else 'standard library'}

Return ONLY the code, no explanations or markdown."""

        code = self.llm_complete(prompt, max_tokens=2000)
        if code and code.startswith("```"):
            # Extract code from markdown
            lines = code.split("\n")
            if lines[0].startswith("```"):
                code = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        return {
            "language": language,
            "framework": framework,
            "code": code or "# Generated code placeholder",
            "description": description
        }

    def create_file(self, filename: str, content: str, directory: str = ".") -> Dict[str, Any]:
        """Create a file with the given content."""
        import os
        filepath = os.path.join(directory, filename)

        # Create directory if it doesn't exist
        os.makedirs(directory, exist_ok=True)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return {
                "status": "created",
                "filepath": filepath,
                "size": len(content),
                "lines": len(content.split("\n"))
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def read_file(self, filename: str, directory: str = ".") -> Dict[str, Any]:
        """Read the contents of a file."""
        import os
        filepath = os.path.join(directory, filename)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            return {
                "status": "read",
                "filepath": filepath,
                "content": content,
                "size": len(content),
                "lines": len(content.split("\n"))
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def run_command(self, command: str, cwd: str = ".") -> Dict[str, Any]:
        """Execute a shell command."""
        import subprocess
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=30
            )
            return {
                "status": "completed" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "Command timed out"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Tool registry, allowlist, and RBAC policy
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────

TOOL_ACTION_WHITELIST = {
    "payment_tool": ["process_payment", "refund", "get_transaction", "check_duplicate"],
    "ticket_tool": ["create_ticket", "update_ticket", "get_ticket", "list_open_tickets"],
    "notification_tool": ["send_email", "send_slack", "notify_team"],
    "database_tool": ["query", "update", "insert"],
    "code_tool": ["generate_code", "create_file", "read_file", "run_command"],
}

TOOL_SCOPES = {
    "payment_tool":      ["system", "bursar", "finance"],
    "ticket_tool":       ["system", "bursar", "ops"],
    "notification_tool": ["system", "bursar", "ops", "support"],
    "database_tool":     ["system", "bursar"],
    "code_tool":         ["system", "developer"],
}

TOOL_MAP = {
    "payment_tool":      PaymentTool,
    "database_tool":     DatabaseTool,
    "notification_tool": NotificationTool,
    "ticket_tool":       TicketTool,
    "code_tool":         CodeTool,  # NEW: Software development
}
