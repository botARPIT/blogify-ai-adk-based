# Postmortem: The Budget Ledger Lied and We Believed It

**Date:** 2026-05-09
**Severity:** P1 — Users blocked from generating blogs despite having sufficient budget; budget balance displayed to users was incorrect after failed sessions
**Author:** Engineering
**Status:** Resolved — Full state machine migration deployed

---

## What Happened

Users with 100 tokens remaining were seeing "Insufficient budget" errors. After a failed blog generation, the frontend displayed a balance that was lower than it should have been. Budget that was reserved for a session that failed was not being returned.

In parallel, the API was getting noticeably slower on budget-related calls as accounts accumulated more activity. `GET /budget` was taking 400–900ms for accounts with ~200 ledger entries.

Two separate bugs. Same root cause.

---

## The Ledger Architecture

Budget state was maintained via an `append-only` ledger table. Every event — grant, deduction, reservation, release — appended a row. The current balance was computed by summing all rows:

```python
# BudgetRepository.get_balance()
result = await db.execute(
    select(func.sum(BudgetLedger.amount)).where(
        BudgetLedger.account_id == account_id
    )
)
return result.scalar() or 0
```

This is O(N) on every balance check. For an active user, this touches hundreds of rows per API call.

Reservations worked by appending a negative entry. Releasing a reservation was supposed to append a positive entry to cancel it out. Committing a charge appended a permanent negative. The system was meant to stay balanced because every debit had a corresponding credit on failure.

---

## Bug 1: Reservation Release Was Unscoped

When a session failed, the worker called `budget_service.release_reservation()`. That method appended a `+amount` credit to the ledger. But it used the account-level reservation total, not the session-specific reservation.

The actual entry looked like this:

```python
await ledger.append(account_id=account_id, amount=+reserved_amount, note="RELEASE")
```

Where `reserved_amount` came from `get_current_reservation_total(account_id)` — the sum of all active reservations. This was wrong if multiple sessions were running. You'd release more than the failed session actually held, accidentally crediting budget from other in-flight sessions.

In single-session scenarios, this was invisible. Under concurrent load, it overcredited budget for some accounts and left others with stuck reservations that never got released.

---

## Bug 2: Race Window Between Reserve and Deduct

The reservation check and the budget commit were not atomic. The sequence:

```
1. Check balance >= cost                    ← SELECT
2. Append reservation (negative entry)      ← INSERT
3. ... time passes, job runs ...
4. Append deduction (negative entry)        ← INSERT
5. Append reservation release (positive)    ← INSERT
```

Steps 1 and 2 were not wrapped in a transaction with a row-level lock. Two concurrent session requests for the same account could both pass step 1 (both see sufficient balance), both proceed to step 2, and together exhaust budget that neither individually would have consumed fully. A classic double-spend window.

Under normal single-user load this didn't manifest. Under concurrent load (two browser tabs, or automated API clients), it was reproducible.

---

## Bug 3: O(N) Balance Query

This one was not a correctness bug. It was a performance bug that was going to become a correctness risk. As accounts accumulated activity, the ledger grew unbounded. Balance queries scaled linearly with ledger length.

At 200 entries: 400ms. At 1000 entries (a heavy user over a week): estimated 2–3s. This would eventually hit DB query timeouts.

More critically, a slow balance query meant the window between "check balance" and "reserve" stretched longer, making the race in Bug 2 more likely to manifest.

---

## What We Discussed

### Option 1: Keep Ledger, Fix the Release Bug Only
Scope the release to a specific session_id. Add a session-level reservation entry and only release that specific row (or mark it released, then query unresolved reservations only).

This fixes Bug 1 but leaves Bug 2 and Bug 3 open.

### Option 2: Ledger + Database-Side Atomic Reserve
Wrap the check-and-reserve in a transaction with `SELECT ... FOR UPDATE` on the account row. This serializes reservations per account.

Fixes Bug 2. Doesn't fix Bug 3 (still O(N) for balance).

### Option 3: Materialized Balance Table + SessionReservation Sub-table (What We Did)
Drop ledger summation as the source of truth. Introduce a `BudgetAccount` table with an `authoritative_balance` column. Introduce a `SessionReservation` table where each in-flight session holds a row. The actual balance available to a user is `authoritative_balance - sum(active_reservations)`.

All mutations go through a strict state machine:
- `GRANT` — increases `authoritative_balance` (admin action)
- `RESERVE` — inserts a `SessionReservation` row (locks funds for a session)
- `COMMIT` — decrements `authoritative_balance` by the actual cost, deletes the `SessionReservation`
- `RELEASE` — deletes the `SessionReservation` (returns reserved funds without charging)

Balance check is now O(1):

```python
account = await db.get(BudgetAccount, account_id)
active_reservations = await db.execute(
    select(func.sum(SessionReservation.reserved_amount)).where(
        SessionReservation.account_id == account_id,
        SessionReservation.status == 'active'
    )
)
available = account.authoritative_balance - (active_reservations.scalar() or 0)
```

---

## Why We Chose Option 3

Options 1 and 2 are patches. They address specific bug expressions but don't change the underlying architecture. We'd fix the release scoping, then a month later hit a different edge case — maybe a crash between the "check" and the "reserve" leaves a ghost reservation, or a DB restart mid-transaction corrupts ledger state in a way that's hard to diagnose.

The ledger-as-source-of-truth pattern is fundamentally fragile here because it requires reconstructing state by reading all history. Any gap in that history (missed append, duplicate append, wrong-amount append) silently corrupts the derived balance.

A `BudgetAccount` with an `authoritative_balance` column is the balance. It's not derived. You can't end up with a wrong balance because a row is missing — the balance is a first-class column that gets explicitly updated with each terminal operation.

The `SessionReservation` table handles in-flight state cleanly. Each session either has an active reservation (funds locked) or it doesn't. The reaper cleans up reservations for sessions that died without reaching a terminal state. There's no "sum all the releases and check if they match the reservations" math involved.

---

## Migration Strategy

We couldn't just swap the schema. The old ledger table had live accounting history. We wrote migration 103 to:

1. Create `BudgetAccount` with `authoritative_balance`
2. Create `SessionReservation`
3. Backfill `authoritative_balance` from the ledger sum for existing accounts
4. Leave the ledger table intact (read-only, historical reference)

All new operations write to the new tables. The old `BudgetRepository.get_balance()` method was deleted. New `BudgetAccountRepository` and `SessionReservationRepository` were introduced.

---

## After the Fix

Balance queries are now sub-millisecond. A user with 10,000 ledger entries has the same query time as a new user.

Release on failure is session-scoped. `RELEASE` means "delete the `SessionReservation` row for this specific session_id." There's nothing to sum, nothing to scope — it's a primary key delete.

The state machine enforces correctness by construction. You can't commit a session that was never reserved. You can't double-reserve the same session. The unique constraint on `SessionReservation(session_id, status='active')` makes that impossible at the database level.

---

## Lessons

**Append-only ledgers are great for audit trails. They're bad for derived state.** If your authoritative answer to "what is X?" requires summing all events that happened to X, you will eventually have a performance problem and a correctness risk. Ledgers and materialized views serve different purposes. We were using a ledger where we needed a materialized view.

**The cost of fixing the root architecture is almost always lower than the compounding cost of patching its symptoms.** We could have spent a week chasing ledger scoping bugs. We spent two days replacing the ledger pattern with a direct state table. The second approach gives us a cleaner invariant and no future bugs of this class.

**In-flight state deserves its own table.** "A session has reserved X tokens" is a fact that exists for a bounded period (the duration of a session). It belongs in a table where each row has a clear lifecycle, not as a synthetic derived value from a sum of positive and negative ledger entries.
