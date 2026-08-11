package com.callshield.bridge

/**
 * Advisory screening result. The applied action and mode are immutable Phase 4
 * invariants rather than values supplied by a caller or daemon response.
 */
data class ScreeningResult(
    val riskScore: Int,
    val confidence: Int,
    val verdict: String,
    val recommendedAction: String,
    val reason: String,
    val latencyMs: Int
) {
    val appliedAction: String = "ALLOW"
    val mode: String = "DRY_RUN"

    fun shouldApplyBlock(): Boolean = false

    companion object {
        fun fromProtocolResponse(response: Protocol.ScreeningResponse): ScreeningResult {
            return ScreeningResult(
                riskScore = response.riskScore.coerceIn(0, 100),
                confidence = response.confidence.coerceIn(0, 100),
                verdict = response.verdict,
                recommendedAction = response.recommendedAction,
                reason = response.reason,
                latencyMs = response.latencyMs.coerceAtLeast(0)
            )
        }

        fun unknown(reason: String, latencyMs: Int = 0): ScreeningResult {
            return ScreeningResult(
                riskScore = 0,
                confidence = 0,
                verdict = "UNKNOWN",
                recommendedAction = "ALLOW",
                reason = reason,
                latencyMs = latencyMs.coerceAtLeast(0)
            )
        }
    }
}
