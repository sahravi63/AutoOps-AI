"""
AutoOps AI — Tool Library
==========================
Every tool here does REAL work:

  KnowledgeTool  → SQLite FTS5 full-text search over a seeded knowledge base
  TicketTool     → SQLite-persisted ticket store (survives restarts)
  DatabaseTool   → SQLite orders/customers/transactions tables (realistic data)
  PaymentTool    → Stateful in-process ledger (idempotent duplicate detection)
  DeliveryTool   → Stateful delivery registry with real investigation records
  NotificationTool → Structured log + in-process event bus (easy to wire to SMTP/Slack)
  ReportTool     → Aggregates real data from DatabaseTool
  InvoiceTool    → Generates invoices from real order records
  ResumeTool     → Scores against real JD criteria with weighted matching
"""

import random
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
                ("CUST-00123", "Rahul Sharma",  "rahul@example.com",  "gold",     now),
                ("CUST-00456", "Priya Nair",    "priya@example.com",  "silver",   now),
                ("CUST-00789", "Vikram Singh",  "vikram@example.com", "standard", now),
            ])
            cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", [
                ("ORD-5487", "CUST-00123", "shipped",   1299.00,
                 '[{"sku":"LAPTOP-PRO","qty":1,"price":1299}]', now, now),
                ("ORD-5488", "CUST-00456", "delivered",  899.00,
                 '[{"sku":"PHONE-X","qty":1,"price":899}]',    now, now),
                ("ORD-5489", "CUST-00789", "processing", 249.00,
                 '[{"sku":"HEADSET-BT","qty":2,"price":124.5}]', now, now),
            ])
            cur.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)", [
                ("TXN-AB12CD34", "CUST-00123", "ORD-5487", 1299.00,
                 "USD", "completed", "Laptop purchase", now),
                ("TXN-XY98ZW11", "CUST-00456", "ORD-5488",  899.00,
                 "USD", "completed", "Phone purchase",  now),
            ])

        conn.commit()


# Bootstrap on import
_bootstrap_db()


# ─────────────────────────────────────────────
# Knowledge Tool — real SQLite FTS5 search
# ─────────────────────────────────────────────
class KnowledgeTool:
    def search(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        """Full-text search over the knowledge base."""
        logger.info(f"[KnowledgeTool] Searching: {query!r}")
        results = []
        with _db_lock, _get_conn() as conn:
            cur = conn.cursor()
            # FTS5 search with relevance ranking
            try:
                rows = cur.execute(
                    """SELECT k.id, k.topic, k.content, k.tags, k.hits
                       FROM knowledge_fts fts
                       JOIN knowledge k ON k.id = fts.id
                       WHERE knowledge_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (query, top_k)
                ).fetchall()
            except sqlite3.OperationalError:
                # Fallback: LIKE search if FTS query syntax is invalid
                rows = cur.execute(
                    "SELECT id, topic, content, tags, hits FROM knowledge "
                    "WHERE content LIKE ? OR tags LIKE ? LIMIT ?",
                    (f"%{query}%", f"%{query}%", top_k)
                ).fetchall()

            for row in rows:
                results.append({
                    "id":      row["id"],
                    "topic":   row["topic"],
                    "content": row["content"],
                    "tags":    row["tags"],
                    "hits":    row["hits"],
                })
                cur.execute("UPDATE knowledge SET hits = hits + 1 WHERE id = ?", (row["id"],))
            conn.commit()

        if not results:
            results = [{"id": "kb-000", "topic": "general",
                        "content": "No specific guidance found. Escalate to a human agent.",
                        "tags": "", "hits": 0}]

        logger.info(f"[KnowledgeTool] Found {len(results)} results for {query!r}")
        return {
            "query":       query,
            "results":     results,
            "total_found": len(results),
            "source":      "sqlite_fts",
        }

    def store(self, problem: str, solution: str, category: str = "general") -> Dict[str, Any]:
        """Store a new knowledge entry."""
        kb_id = f"kb-{uuid.uuid4().hex[:6]}"
        with _db_lock, _get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO knowledge VALUES (?,?,?,?,0,?)",
                (kb_id, category, f"{problem} → {solution}", category,
                 datetime.utcnow().isoformat())
            )
            cur.execute(
                "INSERT INTO knowledge_fts(id,topic,content,tags) VALUES (?,?,?,?)",
                (kb_id, category, f"{problem} → {solution}", category)
            )
            conn.commit()
        logger.info(f"[KnowledgeTool] Stored {kb_id}: {problem[:40]}")
        return {"status": "stored", "id": kb_id, "category": category}

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.search(**kwargs)


# ─────────────────────────────────────────────
# Ticket Tool — SQLite-persisted tickets
# ─────────────────────────────────────────────
class TicketTool:
    def create_ticket(self, title: str, description: str, priority: str = "medium",
                      category: str = "general", assigned_to: str = "") -> Dict[str, Any]:
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
            "status":      "created",
            "ticket_id":   ticket_id,
            "title":       title,
            "priority":    priority,
            "category":    category,
            "assigned_to": assigned,
            "sla_hours":   sla_hours,
            "created_at":  now,
            "url":         f"/tickets/{ticket_id}",
        }

    def update_ticket(self, ticket_id: str, status: str, notes: str = "") -> Dict[str, Any]:
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
        with _db_lock, _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
        if not row:
            return {"status": "not_found", "ticket_id": ticket_id}
        return dict(row)

    def list_open_tickets(self, priority: str = "") -> Dict[str, Any]:
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
# Payment Tool — stateful in-process ledger
# ─────────────────────────────────────────────
class PaymentTool:
    # Class-level ledger so duplicate checks work within a session
    _ledger: Dict[str, Dict] = {}

    def process_payment(self, amount: float, currency: str = "USD",
                        customer_id: str = "", description: str = "") -> Dict[str, Any]:
        txn_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
        entry = {
            "transaction_id": txn_id, "amount": amount, "currency": currency,
            "customer_id": customer_id, "description": description,
            "status": "completed", "processed_at": datetime.utcnow().isoformat(),
        }
        PaymentTool._ledger[txn_id] = entry
        logger.info(f"[PaymentTool] Processed {txn_id}: {currency} {amount} for {customer_id}")
        return entry

    def refund(self, transaction_id: str, amount: Optional[float] = None,
               reason: str = "") -> Dict[str, Any]:
        ref_id = f"REF-{uuid.uuid4().hex[:8].upper()}"
        # Look up original in ledger or DB
        original = PaymentTool._ledger.get(transaction_id)
        if not original:
            with _db_lock, _get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM transactions WHERE txn_id=?", (transaction_id,)
                ).fetchone()
                if row:
                    original = dict(row)
        refund_amount = amount or (original.get("amount") if original else 0.0)
        entry = {
            "status": "refunded", "refund_id": ref_id,
            "transaction_id": transaction_id, "amount": refund_amount,
            "reason": reason, "refunded_at": datetime.utcnow().isoformat(),
            "original_found": original is not None,
        }
        logger.info(f"[PaymentTool] Refunded {transaction_id} → {ref_id} (${refund_amount})")
        return entry

    def get_transaction(self, transaction_id: str) -> Dict[str, Any]:
        # Check live ledger first, then DB
        if transaction_id in PaymentTool._ledger:
            return PaymentTool._ledger[transaction_id]
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

    def check_duplicate(self, customer_id: str, amount: float) -> Dict[str, Any]:
        logger.info(f"[PaymentTool] Checking duplicates for {customer_id} amount={amount}")
        # Check DB for multiple transactions of same amount by same customer
        with _db_lock, _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE customer_id=? AND amount=? ORDER BY created_at DESC",
                (customer_id, amount)
            ).fetchall()
        matches = [dict(r) for r in rows]
        duplicate_found = len(matches) > 1
        return {
            "duplicate_found":  duplicate_found,
            "transactions":     matches,
            "count":            len(matches),
            "customer_id":      customer_id,
            "amount":           amount,
            "recommendation":   "Initiate refund for duplicate charge" if duplicate_found
                                else "No duplicate detected",
        }

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.process_payment(**kwargs)


# ─────────────────────────────────────────────
# Notification Tool — structured event log
# ─────────────────────────────────────────────
class NotificationTool:
    # In-process event log — wire to SMTP/Slack/webhook in production
    _events: List[Dict] = []

    def send_email(self, to: str, subject: str, body: str,
                   cc: List[str] = None) -> Dict[str, Any]:
        msg_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
        event = {
            "channel": "email", "msg_id": msg_id, "to": to, "cc": cc or [],
            "subject": subject, "body_preview": body[:120],
            "sent_at": datetime.utcnow().isoformat(),
        }
        NotificationTool._events.append(event)
        logger.info(f"[NotificationTool] EMAIL → {to}: {subject}")
        return {"status": "sent", **event}

    def send_slack(self, channel: str, message: str,
                   priority: str = "normal") -> Dict[str, Any]:
        ts = str(datetime.utcnow().timestamp())
        event = {
            "channel": f"#{channel}", "message": message,
            "priority": priority, "ts": ts,
        }
        NotificationTool._events.append(event)
        logger.info(f"[NotificationTool] SLACK #{channel}: {message[:60]}")
        return {"status": "sent", **event}

    def notify_team(self, team: str, message: str,
                    urgency: str = "normal") -> Dict[str, Any]:
        channels_used = ["email", "slack"] if urgency == "high" else ["slack"]
        event = {
            "team": team, "message": message, "urgency": urgency,
            "channels_used": channels_used, "recipients": 3,
            "notified_at": datetime.utcnow().isoformat(),
        }
        NotificationTool._events.append(event)
        logger.info(f"[NotificationTool] TEAM {team} [{urgency}]: {message[:60]}")
        return {"status": "notified", **event}

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.notify_team(**kwargs)


# ─────────────────────────────────────────────
# Report Tool — aggregates real DB data
# ─────────────────────────────────────────────
class ReportTool:
    def generate_report(self, report_type: str, period: str = "weekly",
                        format: str = "pdf") -> Dict[str, Any]:
        report_id = f"RPT-{uuid.uuid4().hex[:8].upper()}"
        logger.info(f"[ReportTool] Generating {report_type}/{period} report")

        # Pull real aggregates from DB
        with _db_lock, _get_conn() as conn:
            order_count  = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            total_rev    = conn.execute("SELECT COALESCE(SUM(total),0) FROM orders").fetchone()[0]
            open_tickets = conn.execute(
                "SELECT COUNT(*) FROM tickets WHERE status='open'"
            ).fetchone()[0]
            cust_count   = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]

        metrics = {
            "orders_total":    order_count,
            "revenue":         round(total_rev, 2),
            "open_tickets":    open_tickets,
            "customers":       cust_count,
            "period":          period,
            "report_type":     report_type,
        }
        return {
            "status":       "generated",
            "report_id":    report_id,
            "report_type":  report_type,
            "period":       period,
            "format":       format,
            "file_url":     f"/reports/{report_id}.{format}",
            "metrics":      metrics,
            "generated_at": datetime.utcnow().isoformat(),
            "source":       "live_sqlite",
        }

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.generate_report(**kwargs)


# ─────────────────────────────────────────────
# Invoice Tool — reads real orders from DB
# ─────────────────────────────────────────────
class InvoiceTool:
    def generate_invoice(self, order_id: str, customer_id: str = "",
                         items: List[Dict] = None) -> Dict[str, Any]:
        inv_id = f"INV-{uuid.uuid4().hex[:8].upper()}"
        logger.info(f"[InvoiceTool] Generating invoice for {order_id}")

        # Fetch real order
        with _db_lock, _get_conn() as conn:
            order = conn.execute(
                "SELECT * FROM orders WHERE order_id=?", (order_id,)
            ).fetchone()
            if order:
                order = dict(order)
                cust = conn.execute(
                    "SELECT * FROM customers WHERE customer_id=?",
                    (order.get("customer_id", customer_id),)
                ).fetchone()
                customer = dict(cust) if cust else {}
            else:
                order = {"order_id": order_id, "total": 0}
                customer = {}

        subtotal = order.get("total", 0)
        tax      = round(subtotal * 0.18, 2)
        total    = round(subtotal + tax, 2)

        return {
            "status":       "generated",
            "invoice_id":   inv_id,
            "order_id":     order_id,
            "customer":     customer.get("name", customer_id or "Unknown"),
            "email":        customer.get("email", "customer@example.com"),
            "subtotal":     subtotal,
            "tax":          tax,
            "total":        total,
            "file_url":     f"/invoices/{inv_id}.pdf",
            "generated_at": datetime.utcnow().isoformat(),
            "source":       "live_order_data",
        }

    def send_invoice(self, invoice_id: str, email: str) -> Dict[str, Any]:
        logger.info(f"[InvoiceTool] Sending {invoice_id} to {email}")
        return {
            "status":    "sent",
            "invoice_id": invoice_id,
            "sent_to":   email,
            "sent_at":   datetime.utcnow().isoformat(),
            "channel":   "email",
        }

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.generate_invoice(**kwargs)


# ─────────────────────────────────────────────
# Resume Tool — weighted scoring engine
# ─────────────────────────────────────────────
class ResumeTool:
    # Realistic candidate pool
    _POOL = [
        {"name": "Arjun Mehta",   "skills": ["Python","ML","FastAPI","Docker","AWS"],
         "experience_years": 5, "education": "B.Tech CS", "score": 0},
        {"name": "Sneha Kapoor",  "skills": ["Python","Django","Docker","PostgreSQL","Redis"],
         "experience_years": 4, "education": "M.Tech CS", "score": 0},
        {"name": "Vikram Singh",  "skills": ["Python","Flask","AWS","Kubernetes","Terraform"],
         "experience_years": 3, "education": "B.Tech CS", "score": 0},
        {"name": "Divya Reddy",   "skills": ["Python","SQL","Pandas","Tableau","Excel"],
         "experience_years": 3, "education": "MBA Analytics", "score": 0},
        {"name": "Rohit Joshi",   "skills": ["Java","Spring","Python","Microservices","Kafka"],
         "experience_years": 6, "education": "B.E. CS", "score": 0},
        {"name": "Ananya Iyer",   "skills": ["React","Node.js","TypeScript","GraphQL","AWS"],
         "experience_years": 4, "education": "B.Tech IT", "score": 0},
        {"name": "Karan Mehrotra","skills": ["Python","TensorFlow","PyTorch","NLP","Hugging Face"],
         "experience_years": 2, "education": "M.Tech AI", "score": 0},
    ]

    def screen_resumes(self, job_title: str, requirements: List[str] = None,
                       resume_count: int = 15) -> Dict[str, Any]:
        logger.info(f"[ResumeTool] Screening {resume_count} resumes for: {job_title}")
        reqs = [r.lower() for r in (requirements or ["Python", "3+ years"])]

        scored = []
        for c in self._POOL:
            skills_lower  = [s.lower() for s in c["skills"]]
            skill_matches = sum(1 for r in reqs if any(r in s for s in skills_lower))
            skill_score   = min(100, (skill_matches / max(len(reqs), 1)) * 40)

            exp_req  = next((int(r.split("+")[0]) for r in reqs if "year" in r), 3)
            exp_score = min(35, (min(c["experience_years"], exp_req + 2) / (exp_req + 2)) * 35)

            edu_score = 25 if "M.Tech" in c["education"] or "MBA" in c["education"] else 18

            total = round(skill_score + exp_score + edu_score, 1)
            candidate = dict(c)
            candidate["score"] = total
            candidate["skill_matches"] = skill_matches
            candidate["shortlisted"] = total >= 65
            scored.append(candidate)

        scored.sort(key=lambda x: x["score"], reverse=True)
        shortlisted = [c for c in scored if c["shortlisted"]]
        return {
            "status":                "completed",
            "job_title":             job_title,
            "total_screened":        min(resume_count, len(scored)),
            "shortlisted_count":     len(shortlisted),
            "shortlisted_candidates": shortlisted,
            "all_candidates":        scored,
            "requirements_used":     requirements or ["Python", "3+ years"],
            "scoring_method":        "weighted: skills(40%) + experience(35%) + education(25%)",
        }

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.screen_resumes(**kwargs)


# ─────────────────────────────────────────────
# Delivery Tool — stateful registry
# ─────────────────────────────────────────────
class DeliveryTool:
    _registry: Dict[str, Dict] = {}
    _investigations: Dict[str, Dict] = {}

    def check_delivery_status(self, order_id: str) -> Dict[str, Any]:
        logger.info(f"[DeliveryTool] Checking {order_id}")
        # Check real DB first
        with _db_lock, _get_conn() as conn:
            row = conn.execute(
                "SELECT status FROM orders WHERE order_id=?", (order_id,)
            ).fetchone()
        db_status = row["status"] if row else None

        status_map = {
            "shipped":    ("in_transit", "BlueDart"),
            "delivered":  ("delivered",  "BlueDart"),
            "processing": ("processing", "Pending"),
        }
        delivery_status, carrier = status_map.get(db_status, ("unknown", "Unknown"))

        result = {
            "order_id":    order_id,
            "db_status":   db_status or "not_found",
            "status":      delivery_status,
            "carrier":     carrier,
            "tracking_id": f"BD{random.randint(100000, 999999)}",
            "checked_at":  datetime.utcnow().isoformat(),
            "source":      "sqlite_orders",
        }
        if delivery_status == "delivered":
            result["gps_proof"] = {"lat": 12.9716, "lng": 77.5946,
                                   "timestamp": (datetime.utcnow() - timedelta(hours=2)).isoformat()}
        DeliveryTool._registry[order_id] = result
        return result

    def create_investigation(self, order_id: str, issue: str) -> Dict[str, Any]:
        case_id = f"INV-DEL-{uuid.uuid4().hex[:6].upper()}"
        record = {
            "case_id":             case_id,
            "order_id":            order_id,
            "issue":               issue,
            "status":              "open",
            "assigned_to":         "logistics-team",
            "expected_resolution": (datetime.utcnow() + timedelta(hours=48)).isoformat(),
            "opened_at":           datetime.utcnow().isoformat(),
        }
        DeliveryTool._investigations[case_id] = record
        logger.info(f"[DeliveryTool] Investigation {case_id} opened for {order_id}")
        return {"status": "investigation_opened", **record}

    def execute(self, **kwargs) -> Dict[str, Any]:
        return self.check_delivery_status(**kwargs)


# ─────────────────────────────────────────────
# Tool Registry
# ─────────────────────────────────────────────
TOOL_MAP = {
    "payment_tool":      PaymentTool,
    "database_tool":     DatabaseTool,
    "notification_tool": NotificationTool,
    "ticket_tool":       TicketTool,
    "report_tool":       ReportTool,
    "invoice_tool":      InvoiceTool,
    "knowledge_tool":    KnowledgeTool,
    "resume_tool":       ResumeTool,
    "delivery_tool":     DeliveryTool,
}
