import { useState } from 'react'
import './App.css'

type StepState =
  | 'passed'
  | 'blocked'
  | 'pending'
  | 'unknown'

type PipelineStep = {
  name: string
  description: string
  state: StepState
  label: string
}

type IntentItem = {
  sku: string
  quantity: number
}

type AuthorizationSnapshot = {
  authorization_id: string
  max_amount_paise: number
  allowed_merchants: string[]
  allowed_categories: string[]
  allowed_skus: string[]
  max_quantity: number
  currency: string
  active: boolean
  revoked: boolean
}

type TransactionRecord = {
  transaction_id: string
  intent_id: string
  user_id: string
  agent_id: string
  merchant_id: string
  amount_paise: number
  currency: string
  items: IntentItem[]
  intent_hash: string
  authorization_snapshot?: AuthorizationSnapshot | null
  idempotency_key: string
  razorpay_order_id?: string | null
  razorpay_payment_id?: string | null
  state: string
  created_at: string
  updated_at: string
}

type OrchestrationResult = {
  transaction: TransactionRecord
  mandate: {
    user_id: string
    agent_id: string
    merchant_id: string
    amount_paise: number
    intent_hash: string
    nonce: string
    issued_at: string
    expires_at: string
    signature: string
  }
  status: string
}

type AuditEvent = {
  sequence: number
  event_id: string
  event_type: string
  transaction_id: string
  intent_id: string
  user_id: string
  agent_id: string
  state: string
  intent_hash?: string | null
  occurred_at: string
  details: Record<string, unknown>
  previous_event_hash: string
  event_hash: string
}

function formatAuditTime(value: string): string {
  return new Date(value).toLocaleTimeString(
    'en-IN',
    {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    },
  )
}

const USER_ID = 'user_123'
const AGENT_ID = 'agent_001'
const MERCHANT_ID = 'merchant_001'

const APPROVED_AMOUNT = 450000
const BLOCKED_AMOUNT = 850000

const approvedMessage =
  'Buy exactly one shoe_001 from merchant_001 for ₹4500.'

const blockedMessage =
  'Buy shoe_001 from merchant_001 for ₹8500.'

function formatRupees(amountPaise: number): string {
  return `₹${(amountPaise / 100).toLocaleString('en-IN')}`
}

function shortHash(value: string): string {
  if (value.length <= 16) {
    return value
  }

  return `${value.slice(0, 8)}...${value.slice(-8)}`
}

function StepIcon({ state }: { state: StepState }) {
  if (state === 'passed') {
    return <span className="step-icon step-icon-passed">✓</span>
  }

  if (state === 'blocked') {
    return <span className="step-icon step-icon-blocked">!</span>
  }

  if (state === 'unknown') {
    return <span className="step-icon step-icon-blocked">?</span>
  }

  return <span className="step-icon step-icon-pending">—</span>
}

function stateLabel(state: StepState): string {
  if (state === 'passed') {
    return 'PASSED'
  }

  if (state === 'blocked') {
    return 'BLOCKED'
  }

  if (state === 'unknown') {
    return 'UNKNOWN'
  }

  return 'NOT REACHED'
}

/*
 * Map the authoritative TransactionState to the visible control
 * pipeline. The UI never invents later lifecycle states.
 */
function buildLifecyclePipeline(
  transactionState: string,
  result: OrchestrationResult | null,
): PipelineStep[] {
  const state = transactionState

  const completedBefore = (requiredState: string): boolean => {
    const order = [
      'CREATED',
      'INTENT_VALIDATED',
      'POLICY_APPROVED',
      'MANDATE_VALID',
      'LOCK_ACQUIRED',
      'DISPATCHED',
      'SUCCESS',
      'COMPLETED',
    ]

    const currentIndex = order.indexOf(state)
    const requiredIndex = order.indexOf(requiredState)

    return (
      currentIndex >= 0 &&
      requiredIndex >= 0 &&
      currentIndex >= requiredIndex
    )
  }

  const isUnknown =
    state === 'UNKNOWN' ||
    state === 'RECONCILE_PENDING'

  const razorpayOrder = result?.transaction.razorpay_order_id

  const authorizationState: StepState =
    completedBefore('INTENT_VALIDATED')
      ? 'passed'
      : state === 'CREATED'
        ? 'pending'
        : 'blocked'

  const policyState: StepState =
    completedBefore('POLICY_APPROVED')
      ? 'passed'
      : state === 'INTENT_VALIDATED'
        ? 'pending'
        : 'blocked'

  const mandateState: StepState =
    completedBefore('MANDATE_VALID')
      ? 'passed'
      : state === 'POLICY_APPROVED'
        ? 'pending'
        : 'blocked'

  const idempotencyState: StepState =
    completedBefore('LOCK_ACQUIRED')
      ? 'passed'
      : state === 'MANDATE_VALID'
        ? 'pending'
        : 'blocked'

  let razorpayState: StepState = 'pending'
  let razorpayDescription = 'Not reached'

  if (isUnknown) {
    razorpayState = 'unknown'
    razorpayDescription =
      'Dispatch outcome requires reconciliation'
  } else if (completedBefore('DISPATCHED')) {
    razorpayState = 'passed'
    razorpayDescription = razorpayOrder
      ? `Order created · ${razorpayOrder}`
      : 'Execution reached payment rail'
  } else if (
    state === 'LOCK_ACQUIRED'
  ) {
    razorpayState = 'pending'
    razorpayDescription = 'Ready for Razorpay dispatch'
  } else {
    razorpayState = 'blocked'
    razorpayDescription = 'No API call made'
  }

  return [
    {
      name: 'Authorization',
      description: result?.transaction.authorization_snapshot
        ? `Server-owned authority · ${formatRupees(
            result.transaction.authorization_snapshot.max_amount_paise,
          )} maximum`
        : 'Server-owned payment authority',
      state: authorizationState,
      label: stateLabel(authorizationState),
    },
    {
      name: 'Policy',
      description: 'Merchant, SKU, amount and quantity checks',
      state: policyState,
      label: stateLabel(policyState),
    },
    {
      name: 'Mandate',
      description: completedBefore('MANDATE_VALID')
        ? 'AP2-aligned mandate verified'
        : 'Waiting for policy approval',
      state: mandateState,
      label: stateLabel(mandateState),
    },
    {
      name: 'Idempotency',
      description: completedBefore('LOCK_ACQUIRED')
        ? 'Execution claim acquired'
        : 'Execution claim not yet acquired',
      state: idempotencyState,
      label: stateLabel(idempotencyState),
    },
    {
      name: 'Razorpay',
      description: razorpayDescription,
      state: razorpayState,
      label: stateLabel(razorpayState),
    },
  ]
}

function buildBlockedPipeline(
  reason: string,
): PipelineStep[] {
  return [
    {
      name: 'Authorization',
      description: reason,
      state: 'blocked',
      label: 'BLOCKED',
    },
    {
      name: 'Policy',
      description: 'Execution stopped before policy evaluation',
      state: 'pending',
      label: 'NOT REACHED',
    },
    {
      name: 'Mandate',
      description: 'Not reached',
      state: 'pending',
      label: 'NOT REACHED',
    },
    {
      name: 'Idempotency',
      description: 'Payment execution not claimed',
      state: 'pending',
      label: 'NOT REACHED',
    },
    {
      name: 'Razorpay',
      description: 'No API call made',
      state: 'blocked',
      label: 'BLOCKED',
    },
  ]
}

async function executeScenario(
  userMessage: string,
): Promise<OrchestrationResult> {
  const token = import.meta.env.VITE_AGENTSHIELD_API_TOKEN

  if (!token) {
    throw new Error(
      'VITE_AGENTSHIELD_API_TOKEN is not configured.',
    )
  }

  const response = await fetch(
    '/v1/agent/execute',
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'Idempotency-Key': `frontend-${crypto.randomUUID()}`,
      },
      body: JSON.stringify({
        user_message: userMessage,
        merchant_context: {
          merchant_id: MERCHANT_ID,
          category: 'footwear',
          sku: 'shoe_001',
        },
      }),
    },
  )

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const detail =
      body &&
      typeof body === 'object' &&
      'detail' in body &&
      typeof body.detail === 'string'
        ? body.detail
        : `AgentShield request failed with HTTP ${response.status}.`

    throw new Error(detail)
  }

  return body as OrchestrationResult
}

async function fetchAuditTrail(
  transactionId: string,
): Promise<AuditEvent[]> {
  const token = import.meta.env.VITE_AGENTSHIELD_API_TOKEN

  if (!token) {
    throw new Error(
      'VITE_AGENTSHIELD_API_TOKEN is not configured.',
    )
  }

  const response = await fetch(
    `/v1/transactions/${encodeURIComponent(transactionId)}/audit`,
    {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    },
  )

  const body = await response.json().catch(
    () => null,
  )

  if (!response.ok) {
    const detail =
      body &&
      typeof body === 'object' &&
      'detail' in body &&
      typeof body.detail === 'string'
        ? body.detail
        : `Audit request failed with HTTP ${response.status}.`

    throw new Error(detail)
  }

  return body as AuditEvent[]
}

function App() {
  const [blocked, setBlocked] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] =
    useState<OrchestrationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([])

  const selectedMessage = blocked
    ? blockedMessage
    : approvedMessage

  const selectedAmount = blocked
    ? BLOCKED_AMOUNT
    : APPROVED_AMOUNT

  const displayedAmount =
    result?.transaction.amount_paise ??
    selectedAmount

  const transactionState =
    result?.transaction.state ?? null

  const decision = error
    ? 'BLOCKED'
    : result
      ? result.status === 'SUCCESS' ||
        result.status === 'COMPLETED'
        ? 'COMPLETED'
        : 'APPROVED'
      : 'READY'

  const authorization =
    result?.transaction.authorization_snapshot ??
    null

  const pipeline = error
    ? buildBlockedPipeline(error)
    : transactionState
      ? buildLifecyclePipeline(
          transactionState,
          result,
        )
      : []

  const razorpayOrderId =
    result?.transaction.razorpay_order_id ??
    null

  const intentHash =
    result?.transaction.intent_hash ?? null

  const passedCount =
    pipeline.filter(
      (step) => step.state === 'passed',
    ).length

  const blockedCount =
    pipeline.filter(
      (step) =>
        step.state === 'blocked' ||
        step.state === 'unknown',
    ).length

  const runScenario = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    setAuditEvents([])

    try {
      const response =
        await executeScenario(selectedMessage)

      setResult(response)

      try {
        const events = await fetchAuditTrail(
          response.transaction.transaction_id,
        )

        setAuditEvents(events)
      } catch (auditError) {
        setAuditEvents([])
        console.warn(
          'Audit trail could not be loaded:',
          auditError,
        )
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'AgentShield execution failed.',
      )
    } finally {
      setLoading(false)
    }
  }

  const toggleScenario = () => {
    setBlocked((value) => !value)
    setResult(null)
    setError(null)
    setAuditEvents([])
  }

  const pipelineSummary = error
    ? '1 blocked · 4 not reached'
    : !result
      ? 'Awaiting execution'
      : blockedCount > 0
        ? `${passedCount} passed · ${blockedCount} attention`
        : `${passedCount} / ${pipeline.length} passed`

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <div className="brand-glyph">A</div>

            <div>
              <div className="brand-name">
                AgentShield APEX
              </div>
              <div className="brand-subtitle">
                PAYMENT GOVERNANCE CONTROL PLANE
              </div>
            </div>
          </div>

          <div className="topbar-actions">
            <div className="environment">
              <span className="environment-dot" />
              Local test environment
            </div>

            <div className="avatar">P</div>
          </div>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <div className="nav-group">
            <div className="nav-label">Workspace</div>

            <button
              className="nav-item active"
              type="button"
            >
              <span className="nav-indicator" />
              Overview
            </button>

            <button className="nav-item" type="button">
              Transactions
            </button>

            <button className="nav-item" type="button">
              Payment authority
            </button>

            <button className="nav-item" type="button">
              Audit trail
            </button>
          </div>

          <div className="sidebar-footer">
            <div className="sidebar-footer-label">
              Authenticated principal
            </div>
            <div className="sidebar-principal">
              {USER_ID}
            </div>
            <div className="sidebar-agent">
              {AGENT_ID}
            </div>
          </div>
        </aside>

        <main className="content">
          <div className="page-header">
            <div>
              <div className="page-kicker">
                OVERVIEW
              </div>

              <h1>Payment control</h1>

              <p>
                Every AI-initiated payment is evaluated before money can move.
              </p>
            </div>

            <div className="topbar-actions">
              <button
                className={`scenario-button ${
                  blocked
                    ? 'scenario-button-reset'
                    : ''
                }`}
                type="button"
                onClick={toggleScenario}
                disabled={loading}
              >
                {blocked
                  ? 'Use approved scenario'
                  : 'Use blocked scenario'}
              </button>

              <button
                className="scenario-button"
                type="button"
                onClick={runScenario}
                disabled={loading}
              >
                {loading
                  ? 'Running...'
                  : 'Run governance check'}
              </button>
            </div>
          </div>

          {error && (
            <section className="decision-banner decision-banner-blocked">
              <div>
                <div className="decision-label">
                  GOVERNANCE DECISION
                </div>

                <div className="decision-title">
                  BLOCKED
                </div>

                <div className="decision-description">
                  {error}
                </div>
              </div>

              <div className="decision-amount">
                <span>Requested</span>
                <strong>
                  {formatRupees(selectedAmount)}
                </strong>
              </div>
            </section>
          )}

          {!error && (
            <section className="decision-banner decision-banner-approved">
              <div>
                <div className="decision-label">
                  GOVERNANCE DECISION
                </div>

                <div className="decision-title">
                  {decision}
                </div>

                <div className="decision-description">
                  {result
                    ? `Server transaction state: ${result.transaction.state}.`
                    : 'Ready to send this request through the real AgentShield control plane.'}
                </div>
              </div>

              <div className="decision-amount">
                <span>Requested</span>
                <strong>
                  {formatRupees(displayedAmount)}
                </strong>
              </div>
            </section>
          )}

          <section className="request-grid">
            <div className="card request-card">
              <div className="card-header">
                <div>
                  <div className="card-kicker">
                    AI REQUEST
                  </div>

                  <h2>{selectedMessage}</h2>
                </div>

                <span
                  className={`status-badge ${
                    error
                      ? 'status-badge-blocked'
                      : result
                        ? 'status-badge-approved'
                        : ''
                  }`}
                >
                  {loading
                    ? 'RUNNING'
                    : decision}
                </span>
              </div>

              <div className="request-details">
                <div>
                  <span className="field-label">
                    USER
                  </span>
                  <span className="field-value">
                    {USER_ID}
                  </span>
                </div>

                <div>
                  <span className="field-label">
                    AGENT
                  </span>
                  <span className="field-value">
                    {AGENT_ID}
                  </span>
                </div>

                <div>
                  <span className="field-label">
                    MERCHANT
                  </span>
                  <span className="field-value">
                    {result?.transaction.merchant_id ??
                      MERCHANT_ID}
                  </span>
                </div>

                <div>
                  <span className="field-label">
                    SKU
                  </span>
                  <span className="field-value">
                    {result?.transaction.items[0]?.sku ??
                      'shoe_001'}
                  </span>
                </div>
              </div>
            </div>

            <div className="card amount-card">
              <div className="card-kicker">
                PAYMENT
              </div>

              <div className="payment-amount">
                {formatRupees(displayedAmount)}
              </div>

              <div className="payment-caption">
                INR · quantity{' '}
                {result?.transaction.items[0]?.quantity ??
                  1}
              </div>

              <div className="amount-limit">
                <div className="limit-row">
                  <span>Authorized maximum</span>

                  <strong>
                    {authorization
                      ? formatRupees(
                          authorization.max_amount_paise,
                        )
                      : '—'}
                  </strong>
                </div>

                <div className="limit-track">
                  <div
                    className={`limit-fill ${
                      error
                        ? 'limit-fill-blocked'
                        : ''
                    }`}
                    style={{
                      width: `${
                        authorization
                          ? Math.min(
                              100,
                              (displayedAmount /
                                authorization.max_amount_paise) *
                                100,
                            )
                          : 100
                      }%`,
                    }}
                  />
                </div>
              </div>
            </div>
          </section>

          <section className="card pipeline-card">
            <div className="section-heading">
              <div>
                <div className="card-kicker">
                  CONTROL PIPELINE
                </div>

                <h2>Execution checks</h2>
              </div>

              <span className="pipeline-summary">
                {pipelineSummary}
              </span>
            </div>

            <div className="pipeline">
              {pipeline.length === 0 && (
                <div className="pipeline-step">
                  <div className="pipeline-rail">
                    <StepIcon state="pending" />
                  </div>

                  <div className="pipeline-step-body">
                    <div className="pipeline-step-title-row">
                      <span className="pipeline-step-name">
                        Awaiting execution
                      </span>

                      <span className="pipeline-step-state pipeline-step-state-pending">
                        NOT STARTED
                      </span>
                    </div>

                    <div className="pipeline-step-description">
                      Run the governance check to evaluate this request.
                    </div>
                  </div>
                </div>
              )}

              {pipeline.map((step, index) => (
                <div
                  className="pipeline-step"
                  key={step.name}
                >
                  <div className="pipeline-rail">
                    <StepIcon state={step.state} />

                    {index < pipeline.length - 1 && (
                      <span
                        className={`pipeline-connector ${
                          step.state === 'blocked' ||
                          step.state === 'unknown'
                            ? 'pipeline-connector-muted'
                            : ''
                        }`}
                      />
                    )}
                  </div>

                  <div className="pipeline-step-body">
                    <div className="pipeline-step-title-row">
                      <span className="pipeline-step-name">
                        {step.name}
                      </span>

                      <span
                        className={`pipeline-step-state pipeline-step-state-${step.state}`}
                      >
                        {step.label}
                      </span>
                    </div>

                    <div className="pipeline-step-description">
                      {step.description}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="lower-grid">
            <div className="card">
              <div className="card-kicker">
                TRANSACTION
              </div>

              <div className="technical-value">
                {result?.transaction.transaction_id ??
                  'Awaiting transaction'}
              </div>

              <div className="data-list">
                <div className="data-row">
                  <span>State</span>
                  <strong>
                    {transactionState ??
                      (error ? 'BLOCKED' : 'READY')}
                  </strong>
                </div>

                <div className="data-row">
                  <span>Razorpay order</span>
                  <strong>
                    {razorpayOrderId ?? '—'}
                  </strong>
                </div>

                <div className="data-row">
                  <span>Authorization</span>
                  <strong>
                    {authorization?.authorization_id ??
                      'Not resolved'}
                  </strong>
                </div>

                <div className="data-row">
                  <span>Intent hash</span>
                  <strong className="technical-value-small">
                    {intentHash
                      ? shortHash(intentHash)
                      : '—'}
                  </strong>
                </div>
              </div>
            </div>

            <div className="card authority-card">
              <div className="card-kicker">
                PAYMENT AUTHORITY
              </div>

              <div className="authority-header">
                <div>
                  <h2>Server owned</h2>

                  <p>
                    Financial bounds enforced independently of the model.
                  </p>
                </div>

                <span className="authority-status">
                  {authorization?.active &&
                  !authorization.revoked
                    ? 'ACTIVE'
                    : 'NOT RESOLVED'}
                </span>
              </div>

              <div className="authority-grid">
                <div>
                  <span className="field-label">
                    MAX AMOUNT
                  </span>

                  <strong>
                    {authorization
                      ? formatRupees(
                          authorization.max_amount_paise,
                        )
                      : '—'}
                  </strong>
                </div>

                <div>
                  <span className="field-label">
                    ALLOWED SKU
                  </span>

                  <strong>
                    {authorization
                      ? authorization.allowed_skus.join(', ')
                      : '—'}
                  </strong>
                </div>

                <div>
                  <span className="field-label">
                    MAX QUANTITY
                  </span>

                  <strong>
                    {authorization
                      ? authorization.max_quantity
                      : '—'}
                  </strong>
                </div>

                <div>
                  <span className="field-label">
                    CURRENCY
                  </span>

                  <strong>
                    {authorization?.currency ?? '—'}
                  </strong>
                </div>
              </div>
            </div>
          </section>

          {auditEvents.length > 0 && (
            <section className="card audit-card">
              <div className="section-heading">
                <div>
                  <div className="card-kicker">
                    AUDIT TRAIL
                  </div>

                  <h2>Immutable execution record</h2>
                </div>

                <span className="pipeline-summary">
                  {auditEvents.length} events
                </span>
              </div>

              <div className="audit-list">
                {auditEvents.map((event) => (
                  <div
                    className="audit-event"
                    key={event.event_id}
                  >
                    <div className="audit-sequence">
                      #{event.sequence}
                    </div>

                    <div className="audit-event-main">
                      <div className="audit-event-top">
                        <strong>
                          {event.event_type}
                        </strong>

                        <span className="audit-time">
                          {formatAuditTime(
                            event.occurred_at,
                          )}
                        </span>
                      </div>

                      <div className="audit-event-meta">
                        <span>{event.state}</span>

                        <span className="technical-value-small">
                          {shortHash(event.event_hash)}
                        </span>
                      </div>

                      {Object.keys(event.details).length > 0 && (
                        <div className="audit-details">
                          {Object.entries(event.details).map(
                            ([key, value]) => (
                              <span
                                className="audit-detail"
                                key={key}
                              >
                                <b>{key}</b>
                                {String(value)}
                              </span>
                            ),
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <footer className="footer">
            <span>AgentShield APEX</span>
            <span>
              Deterministic payment governance
            </span>
            <span>
              Razorpay execution rail
            </span>
          </footer>
        </main>
      </div>
    </div>
  )
}

export default App