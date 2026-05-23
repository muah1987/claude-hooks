---
description: Write, review, or convert code to GovLang -- the governance programming language for GOV_OS
argument-hint: [write|review|convert|explain] [description or file path]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# GovLang

Write, review, convert, or explain GovLang code. GovLang is a statically typed, compiled language for governance systems combining Go concurrency, Python readability, and TypeScript type safety.

## Variables

ACTION: $ARGUMENTS

## Instructions

- If no `ACTION` is provided, ask the user what they need (write new code, review existing code, convert from another language, or explain a concept).
- Parse ACTION as: `<action> <target>` (e.g., "write visa processing service", "review PGT/services/mod_08", "convert this Python to GovLang", "explain channels")
- All code MUST follow the GovLang specification at `docs/architecture/govlang-spec.md`
- All governance code MUST use compiler directives (#[audit], #[policy], #[encrypted]) where applicable
- File extension: `.gov`

## GovLang Quick Reference

### Syntax Fundamentals

```govlang
// Variables and constants
let name: string = "Ali"              // mutable (default)
let mut counter = 0                   // explicitly mutable
const MAX_RETRY: int = 3             // compile-time constant

// Functions
fn add(a: int, b: int) -> int {
    return a + b
}

// Async functions (always return Result)
async fn fetch(id: NationalID) -> Result<Citizen, DbError> {
    let record = await db.query(id)?
    return Ok(Citizen.from(record))
}

// Closures
let square = |x: int| -> int { x * x }
let adults = citizens.filter(|c| c.age() >= 18)
```

### Type System

```govlang
// Primitives: int, int8-64, uint, uint8-64, float32, float64, bool, string, byte, rune
// Null-safe: Option<T> (Some/None), Result<T,E> (Ok/Err) -- NO null

// Governance types (built-in)
let id: NationalID = NationalID("SA-1990-0001-4821")
let fee: Money = Money(150.00, Currency.SAR)         // fixed-point, never float
let gold: GoldWeight = GoldWeight(1000.0, Unit.Troy_Ounce)
let contract: ContractID = ContractID("GOV-PROC-2026-00142")
let hash: AuditHash = AuditHash.from_bytes(sha3_256(data))
let policy: PolicyID = PolicyID("BUDGET-APPROVAL-TIER-3")
let now: Timestamp = Timestamp.now()                 // nanosecond precision
let today: Date = Date(2026, 2, 8)                   // supports Hijri: Date.hijri(1447, 8, 10)

// Compound types
let ids: Array<int, 5> = [1, 2, 3, 4, 5]            // fixed-size
let names: List<string> = ["Ali", "Fatima"]          // dynamic
let scores: Map<string, int> = {"math": 95}          // hash map
let tags: Set<string> = {"urgent", "reviewed"}       // unique set
let record: Tuple<string, int> = ("Ali", 30)         // heterogeneous

// Generics with trait bounds
fn process<T: Serializable>(data: T) -> Result<T, Error> { ... }
class Repository<T: Storable> { ... }
```

### Control Flow

```govlang
// If/else (also works as expression)
let status = if app.approved { "Active" } else { "Pending" }

// Pattern matching (MUST be exhaustive)
match visa_application.status {
    Submitted => begin_review(app)
    Approved => issue_visa(app)
    Rejected(reason) => notify(app, reason)
}

// Match with guards
match transaction.amount {
    amount if amount > Money(1_000_000, Currency.SAR) => require_three_signatures(txn)
    _ => process_standard(txn)
}

// Loops
for citizen in citizens { update(citizen) }
for i in 0..10 { print(i) }          // exclusive end
for i in 1..=12 { process(i) }       // inclusive end
for id, record in registry { validate(id, record) }
while queue.has_pending() { process(queue.next()) }
loop { match event_bus.poll() { Event.Shutdown => break, _ => handle() } }

// Error propagation with ?
let account = find_account(id)?       // returns Err early if failed
```

### Concurrency

```govlang
// Goroutines (lightweight green threads, M:N scheduling)
go process_application(app)
go || { let result = compute(); ch.send(result) }

// Typed channels (CSP model)
let ch = chan<int>(100)               // buffered
let sync_ch = chan<string>()          // unbuffered (synchronous)
ch.send(42)
let value = ch.recv()
ch.close()

// Select (multiplex channels)
select {
    app = app_ch.recv() => process(app)
    payment = pay_ch.recv() => record(payment)
    timeout(30.seconds) => log.warn("timeout")
}

// Async/await (I/O-bound)
async fn query(region: string) -> Result<List<Citizen>, DbError> {
    let conn = await db.connect()?
    let records = await conn.query("SELECT * WHERE region = ?", region)?
    return Ok(records)
}

// Synchronization
let counter = Mutex<int>(0)
let registry = RwLock<Map<NationalID, Citizen>>(Map.new())
let wg = WaitGroup.new()
```

### Object System (NO inheritance -- composition only)

```govlang
// Classes
class Citizen {
    id: NationalID
    name: string
    status: CitizenStatus

    fn new(id: NationalID, name: string) -> Self {
        return Self { id, name, status: CitizenStatus.Active }
    }
    pub fn is_adult(self) -> bool { self.age() >= 18 }
    pub fn update_address(mut self, addr: Address) { self.address = Some(addr) }
}

// Interfaces (contracts)
interface Auditable {
    fn audit_id(self) -> string
    fn audit_description(self) -> string
}

// Implementation
class Citizen implements Auditable, Serializable {
    fn audit_id(self) -> string { "CITIZEN:" + self.id.to_string() }
    fn audit_description(self) -> string { "Citizen " + self.name }
}

// Enums with associated data (algebraic data types)
enum VisaType {
    Tourist(duration: int)
    Work(employer: BusinessID, profession: string)
    Study(institution: EducationID, program: string)
    Diplomatic(mission: DiplomaticMissionID)
}

// Composition (NOT inheritance)
class GovernmentEmployee {
    citizen: Citizen                   // embedded
    department: Department
    clearance_level: ClearanceLevel
}
```

### Modules and Visibility

```govlang
module CitizenRegistry {
    pub class Citizen { ... }          // public -- accessible from imports
    fn validate(data: Input) { ... }   // private (default)
    priv const KEY: string = "..."     // explicitly private
}

import CitizenRegistry
import { Citizen, register } from CitizenRegistry
import CitizenRegistry as CR
import gov.crypto
import { sha3_256, ed25519_sign } from gov.crypto
```

### Governance Compiler Directives (CRITICAL)

```govlang
// #[audit] -- auto-generates immutable audit trail entries for every call
#[audit]
async fn transfer_funds(from: AccountID, to: AccountID, amount: Money) -> Result<Receipt, Error> {
    // Compiler auto-generates: pre-call entry (who, what, when), post-call entry (result, duration)
}

// #[policy(PolicyName)] -- enforces governance policy BEFORE function executes
#[policy(BudgetApproval)]
#[audit]
fn approve_expenditure(request: ExpenditureRequest) -> Result<Approval, PolicyError> {
    // Only executes if BudgetApproval policy allows it
}

// #[encrypted] -- auto-encrypts field at rest (ChaCha20-Poly1305) and in transit
class CitizenRecord {
    name: string
    #[encrypted] biometric_data: bytes
    #[encrypted] health_records: List<HealthRecord>
    #[encrypted] financial_accounts: List<AccountID>
}

// #[requires_signatures(n)] -- multi-party approval (per 10-CONTRACT-SYSTEM)
#[requires_signatures(3)]
#[audit]
async fn execute_procurement(contract: ProcurementContract) -> Result<Execution, Error> {
    // Runtime verifies 3 Ed25519 signatures before body executes
}

// #[immutable] -- value cannot be modified after creation (compile-time enforced)
#[immutable]
class LegalVerdict {
    case_id: string
    verdict: VerdictType
    issued_at: Timestamp
    signature: bytes
}

// #[pure] -- no side effects (no I/O, no mutation, no randomness)
#[pure]
fn calculate_tax(income: Money, rate: float64) -> Money {
    return income * rate
}

// #[kernel] -- FFI bridge to C kernel code (Layer 2 only)
#[kernel]
extern fn ioctl(fd: int, cmd: uint, arg: *void) -> int
```

### Contract State Machine (built-in keyword)

```govlang
contract ProcurementContract {
    states: [Draft, Submitted, UnderReview, Approved, Active, Completed, Disputed]
    transitions: {
        Draft -> Submitted: submit(submitter: OfficialID)
        Submitted -> UnderReview: assign_reviewer(reviewer: OfficialID)
        UnderReview -> Approved: approve() #[requires_signatures(3)]
        UnderReview -> Draft: reject(reason: string)
        Approved -> Active: activate(start_date: Date)
        Active -> Completed: complete(report: Report)
        Active -> Disputed: dispute(complaint: Complaint)
        Disputed -> Active: resolve(resolution: Resolution) #[requires_signatures(3)]
    }
    data: {
        contract_id: ContractID
        parties: List<PartyID>
        value: Money
    }
}
// Compiler generates: state enum, transition methods, compile-time validation, audit logging
```

### Temporal Queries (built-in audit history)

```govlang
// Query state at a specific point in time
let historical = await gov.audit.as_of(Date(2025, 6, 15)) {
    citizen_registry.find(citizen_id)
}

// Query changes within a time range
let changes = await gov.audit.changes_between(
    entity_id: citizen_id,
    from: Date(2025, 1, 1),
    to: Date(2025, 12, 31)
)
```

### Memory Management

```govlang
// Garbage collected (concurrent, generational mark-sweep)
// Arena allocator for batch operations
arena {
    for record in records {
        let parsed = parse(record)     // arena-allocated
        results.push(parsed.clone())   // cloned to heap
    }
}  // all arena memory freed at once

// Manual memory only in kernel modules (unsafe blocks)
unsafe {
    let ptr = alloc(1024)
    write_bytes(ptr, data, data.len())
    dealloc(ptr)
}
```

### Standard Library (gov.* namespace, zero external deps)

| Module | Purpose |
|--------|---------|
| `gov.crypto` | SHA-3, SHA-256, ChaCha20-Poly1305, Ed25519, CRYSTALS-Kyber, HMAC, HKDF, secure random |
| `gov.db` | PostgreSQL wire protocol v3, query building, parameterized queries |
| `gov.net` | HTTP server/client, TLS 1.3, DNS resolver |
| `gov.json` | JSON parser/writer |
| `gov.audit` | Immutable hash-linked audit chain, temporal queries |
| `gov.policy` | RBAC engine, policy evaluation, separation of duties |
| `gov.identity` | NationalID validation, authentication, sessions, TOTP MFA |
| `gov.money` | Fixed-point monetary arithmetic, riba detection, currency conversion |
| `gov.contract` | Contract state machine, three-signature validation |
| `gov.discovery` | Service registration/lookup |
| `gov.health` | Health check framework |
| `gov.metrics` | Counter/gauge/histogram metrics |
| `gov.trace` | Distributed tracing |
| `gov.config` | Configuration management |

### Naming Conventions (enforced by `gov fmt`)

| Entity | Convention | Example |
|--------|-----------|---------|
| Variables, functions | `snake_case` | `citizen_name`, `process_visa` |
| Types, classes, interfaces, enums | `PascalCase` | `CitizenRecord`, `VisaType` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Modules | `PascalCase` | `CitizenRegistry` |
| Files | `snake_case.gov` | `citizen_registry.gov` |

### Logical Operators (keyword-based for readability)

```govlang
if citizen.active and not citizen.suspended or citizen.exempt { ... }
// NOT: if (citizen.active && !citizen.suspended || citizen.exempt)
```

### Special Operators

| Operator | Purpose | Example |
|----------|---------|---------|
| `..` | Range (exclusive) | `0..10` |
| `..=` | Range (inclusive) | `1..=12` |
| `\|>` | Pipe | `data \|> transform \|> validate` |
| `?.` | Optional chain | `user?.address?.city` |
| `??` | Null coalesce | `name ?? "unknown"` |
| `?` | Error propagate | `call()?` |

### Toolchain

| Tool | Purpose |
|------|---------|
| `govlang` | Compiler (LLVM-based, .gov -> native) |
| `gov build` | Build system (incremental) |
| `gov test` | Testing framework |
| `gov fmt` | Code formatter |
| `gov doc` | Documentation generator |
| `gov` | Package manager (internal registry only) |

### Key Rules

1. **No null** -- use `Option<T>` (Some/None) instead
2. **No exceptions** -- use `Result<T, E>` (Ok/Err) with `?` propagation
3. **No inheritance** -- use interfaces + composition
4. **No external packages** -- all dependencies from internal registry
5. **No float for money** -- `Money` type uses fixed-point arithmetic
6. **Newlines terminate statements** -- semicolons optional
7. **Match must be exhaustive** -- compiler enforces all cases covered
8. **#[audit] is mandatory** for governance state mutations
9. **#[policy] required** for operations needing authorization
10. **#[encrypted] required** for PII and sensitive data fields

## Workflow

### For "write" action:
1. Understand the requirement
2. Identify which governance modules and Gov_rules apply
3. Design the data model (structs, enums)
4. Write GovLang code with appropriate compiler directives
5. Include error handling (Result/Option)
6. Add concurrency where applicable (goroutines, channels)
7. Verify all governance code has #[audit] on mutations

### For "review" action:
1. Read the existing GovLang code
2. Check syntax correctness against the spec
3. Verify compiler directives (#[audit], #[policy], #[encrypted])
4. Check error handling patterns (Result<T,E>, ? operator)
5. Verify naming conventions
6. Report issues and suggestions

### For "convert" action:
1. Read the source code in the original language
2. Map types to GovLang equivalents
3. Convert control flow (if/match/for/while)
4. Replace exceptions with Result<T,E>
5. Add governance directives where applicable
6. Apply GovLang naming conventions

### For "explain" action:
1. Identify the GovLang concept being asked about
2. Provide a clear explanation with examples
3. Show how it relates to governance requirements
4. Compare to equivalent concepts in Go/Python/TypeScript

## Report

```
## GovLang Output

**Action**: [write|review|convert|explain]
**Target**: [description]

### Code / Analysis
[GovLang code or review findings]

### Governance Compliance
- Audit directives: [present/missing]
- Policy enforcement: [present/missing/N/A]
- Encryption: [present/missing/N/A]
- Error handling: [Result<T,E> used correctly]

### Notes
- [relevant observations]
```
